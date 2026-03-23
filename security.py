"""
Operator authentication and session management for Nexus-Hive.

Implements HMAC-signed session cookies, token-based authentication,
role-based access control, and session lifecycle management for
protecting sensitive API routes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from fastapi import HTTPException, Request

_logger = logging.getLogger("nexus_hive.security")

ROLE_HEADERS: Tuple[str, ...] = ("x-operator-role", "x-operator-roles")
DEFAULT_SESSION_COOKIE: str = "nexus_hive_operator_session"
DEFAULT_SESSION_TTL_SEC: int = 12 * 60 * 60


def operator_token_enabled() -> bool:
    """Check whether operator token authentication is configured.

    Returns:
        True if the NEXUS_HIVE_OPERATOR_TOKEN environment variable is set.
    """
    return bool(str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip())


def operator_allowed_roles() -> list[str]:
    """Return the list of allowed operator roles from environment configuration.

    Returns:
        Lowercase list of allowed role strings, or empty if unconfigured.
    """
    return [
        role.strip().lower()
        for role in str(os.getenv("NEXUS_HIVE_OPERATOR_ALLOWED_ROLES", "")).split(",")
        if role.strip()
    ]


def operator_role_headers() -> list[str]:
    """Return the list of HTTP headers used to convey operator roles.

    Returns:
        List of header name strings.
    """
    return list(ROLE_HEADERS)


def operator_auth_status() -> dict[str, object]:
    """Build a summary of the current operator authentication posture.

    Returns:
        Dictionary with enabled status, required roles, accepted headers,
        role headers, and session cookie name.
    """
    return {
        "enabled": operator_token_enabled(),
        "required_roles": operator_allowed_roles(),
        "accepted_headers": ["authorization: Bearer <token>", "x-operator-token"],
        "role_headers": operator_role_headers(),
        "session_cookie": operator_session_cookie_name(),
    }


def operator_session_cookie_name() -> str:
    """Return the session cookie name, configurable via environment.

    Returns:
        The session cookie name string.
    """
    return (
        str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_COOKIE", "")).strip() or DEFAULT_SESSION_COOKIE
    )


def operator_session_secret() -> str:
    """Return the HMAC signing secret for session cookies.

    Falls back through session secret, operator token, and a local default.

    Returns:
        The secret string used for HMAC signing.
    """
    return (
        str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_SECRET", "")).strip()
        or str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
        or "nexus-hive-local-session-secret"
    )


def operator_session_ttl_sec() -> int:
    """Return the session TTL in seconds, clamped to a 7-day maximum.

    Returns:
        Session TTL in seconds.
    """
    raw: str = str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_TTL_SEC", "")).strip()
    try:
        parsed: int = int(raw)
    except ValueError:
        return DEFAULT_SESSION_TTL_SEC
    if parsed <= 0:
        return DEFAULT_SESSION_TTL_SEC
    return min(parsed, 7 * 24 * 60 * 60)


def operator_session_secure() -> bool:
    """Determine whether the session cookie should use the Secure flag.

    Defaults to True in production (NODE_ENV=production).

    Returns:
        True if the Secure flag should be set.
    """
    configured: str = str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_SECURE", "")).strip().lower()
    if configured in {"1", "true", "yes"}:
        return True
    if configured in {"0", "false", "no"}:
        return False
    return str(os.getenv("NODE_ENV", "")).strip().lower() == "production"


def _to_base64_url(value: str) -> str:
    """Encode a string as URL-safe base64 without padding.

    Args:
        value: The string to encode.

    Returns:
        URL-safe base64-encoded string.
    """
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def _from_base64_url(value: str) -> str:
    """Decode a URL-safe base64 string with re-added padding.

    Args:
        value: The base64-encoded string to decode.

    Returns:
        The decoded string.
    """
    padded: str = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")


def _sign_payload(payload: str) -> str:
    """Create an HMAC-SHA256 signature for a payload string.

    Args:
        payload: The string to sign.

    Returns:
        URL-safe base64-encoded HMAC signature.
    """
    return (
        base64.urlsafe_b64encode(
            hmac.new(
                operator_session_secret().encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )
        .decode("utf-8")
        .rstrip("=")
    )


def _parse_cookie_header(value: str | None) -> dict[str, str]:
    """Parse a Cookie header string into a name-value dictionary.

    Args:
        value: The raw Cookie header value.

    Returns:
        Dictionary mapping cookie names to values.
    """
    cookies: dict[str, str] = {}
    for chunk in str(value or "").split(";"):
        item: str = chunk.strip()
        if not item or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = raw_value.strip()
    return cookies


def _read_operator_session_record(request: Request) -> dict[str, object] | None:
    """Read and validate the operator session from the request cookie.

    Verifies the HMAC signature, checks expiration, and extracts
    session fields.

    Args:
        request: The incoming FastAPI request.

    Returns:
        Session record dictionary, or None if invalid or absent.
    """
    encoded: Optional[str] = _parse_cookie_header(request.headers.get("cookie")).get(
        operator_session_cookie_name()
    )
    if not encoded or "." not in encoded:
        return None
    payload, signature = encoded.split(".", 1)
    expected: str = _sign_payload(payload)
    if not hmac.compare_digest(signature, expected):
        _logger.warning("Session cookie signature mismatch")
        return None
    try:
        parsed = json.loads(_from_base64_url(payload))
    except (ValueError, json.JSONDecodeError):
        _logger.warning("Session cookie payload decode failed")
        return None
    if not isinstance(parsed, dict):
        return None
    expires_at: str = str(parsed.get("expires_at") or "").strip()
    credential: str = str(parsed.get("credential") or "").strip()
    if not credential or not expires_at:
        return None
    if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        _logger.info("Session cookie expired")
        return None
    return {
        "auth_mode": "token",
        "credential": credential,
        "expires_at": expires_at,
        "issued_at": str(parsed.get("issued_at") or "").strip(),
        "roles": [role.strip().lower() for role in parsed.get("roles") or [] if str(role).strip()],
        "subject": str(parsed.get("subject") or "").strip() or None,
    }


def read_operator_session(request: Request) -> dict[str, object] | None:
    """Read the operator session from the request, excluding credential.

    Args:
        request: The incoming FastAPI request.

    Returns:
        Session metadata dictionary without credential, or None.
    """
    record: dict[str, object] | None = _read_operator_session_record(request)
    if not record:
        return None
    return {
        "auth_mode": record["auth_mode"],
        "expires_at": record["expires_at"],
        "issued_at": record["issued_at"],
        "roles": record["roles"],
        "subject": record["subject"],
    }


def apply_operator_session(request: Request) -> dict[str, object] | None:
    """Apply operator session credentials to request headers for downstream auth.

    If a valid session cookie is present, injects the credential and roles
    into the request headers so that route-level auth checks pass.

    Args:
        request: The incoming FastAPI request (mutated in place).

    Returns:
        Session metadata dictionary, or None if no valid session.
    """
    record: dict[str, object] | None = _read_operator_session_record(request)
    if not record:
        return None

    existing_headers: list = list(request.scope.get("headers", []))
    header_names: set[str] = {name.decode("latin-1").lower() for name, _ in existing_headers}
    if "authorization" not in header_names and "x-operator-token" not in header_names:
        existing_headers.append((b"x-operator-token", str(record["credential"]).encode("utf-8")))
    _roles_raw: Any = record.get("roles") or []
    roles_list: list[str] = list(_roles_raw)
    if (
        "x-operator-role" not in header_names
        and "x-operator-roles" not in header_names
        and roles_list
    ):
        existing_headers.append((b"x-operator-roles", ",".join(roles_list).encode("utf-8")))
    request.scope["headers"] = existing_headers
    _logger.debug("Applied operator session for subject=%s", record.get("subject"))
    return {
        "auth_mode": record["auth_mode"],
        "expires_at": record["expires_at"],
        "issued_at": record["issued_at"],
        "roles": record["roles"],
        "subject": record["subject"],
    }


def create_operator_session_cookie(
    *,
    credential: str,
    roles: list[str],
    subject: str | None,
) -> tuple[str, dict[str, object]]:
    """Create an HMAC-signed session cookie for operator authentication.

    Args:
        credential: The operator credential (token) to embed.
        roles: List of operator roles to include in the session.
        subject: Optional subject identifier for audit logging.

    Returns:
        A tuple of (Set-Cookie header string, session metadata dictionary).
    """
    issued_at: datetime = datetime.now(timezone.utc)
    expires_at: datetime = issued_at + timedelta(seconds=operator_session_ttl_sec())
    payload: str = _to_base64_url(
        json.dumps(
            {
                "credential": credential,
                "expires_at": expires_at.isoformat(),
                "issued_at": issued_at.isoformat(),
                "roles": roles,
                "subject": subject,
            },
            ensure_ascii=True,
        )
    )
    signature: str = _sign_payload(payload)
    parts: list[str] = [
        f"{operator_session_cookie_name()}={payload}.{signature}",
        "Path=/",
        f"Max-Age={operator_session_ttl_sec()}",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if operator_session_secure():
        parts.append("Secure")
    _logger.info(
        "Created operator session for subject=%s, roles=%s",
        subject,
        roles,
    )
    return (
        "; ".join(parts),
        {
            "auth_mode": "token",
            "expires_at": expires_at.isoformat(),
            "issued_at": issued_at.isoformat(),
            "roles": roles,
            "subject": subject,
        },
    )


def clear_operator_session_cookie() -> str:
    """Generate a Set-Cookie header that clears the operator session.

    Returns:
        A Set-Cookie header string with Max-Age=0.
    """
    parts: list[str] = [
        f"{operator_session_cookie_name()}=",
        "Path=/",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
        "Max-Age=0",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if operator_session_secure():
        parts.append("Secure")
    _logger.info("Cleared operator session cookie")
    return "; ".join(parts)


def read_presented_roles(request: Request) -> list[str]:
    """Extract operator roles from request headers.

    Reads from both x-operator-role and x-operator-roles headers.

    Args:
        request: The incoming FastAPI request.

    Returns:
        Lowercase list of presented role strings.
    """
    values: list[str] = []
    for header in ROLE_HEADERS:
        raw: str = str(request.headers.get(header, "")).strip()
        if raw:
            values.extend(raw.split(","))
    return [value.strip().lower() for value in values if value.strip()]


def require_operator_token(request: Request) -> None:
    """Enforce operator token authentication on a request.

    Checks both x-operator-token header and Authorization Bearer token.
    Also enforces role requirements when operator roles are configured.

    Args:
        request: The incoming FastAPI request.

    Raises:
        HTTPException: 403 if the token is missing/invalid or required roles
            are not presented.
    """
    expected: str = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
    if expected:
        header_token: str = str(request.headers.get("x-operator-token", "")).strip()
        authorization: str = str(request.headers.get("authorization", "")).strip()
        bearer_token: str = (
            authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        )
        if header_token != expected and bearer_token != expected:
            _logger.warning("Operator token authentication failed")
            raise HTTPException(status_code=403, detail="missing or invalid operator token")

    allowed_roles: list[str] = operator_allowed_roles()
    if allowed_roles:
        presented_roles: list[str] = read_presented_roles(request)
        if not any(role in allowed_roles for role in presented_roles):
            _logger.warning(
                "Operator role check failed: presented=%s, allowed=%s",
                presented_roles,
                allowed_roles,
            )
            raise HTTPException(status_code=403, detail="missing required operator role")
