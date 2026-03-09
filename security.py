from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

ROLE_HEADERS = ("x-operator-role", "x-operator-roles")
DEFAULT_SESSION_COOKIE = "nexus_hive_operator_session"
DEFAULT_SESSION_TTL_SEC = 12 * 60 * 60


def operator_token_enabled() -> bool:
    return bool(str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip())


def operator_allowed_roles() -> list[str]:
    return [
        role.strip().lower()
        for role in str(os.getenv("NEXUS_HIVE_OPERATOR_ALLOWED_ROLES", "")).split(",")
        if role.strip()
    ]


def operator_role_headers() -> list[str]:
    return list(ROLE_HEADERS)


def operator_auth_status() -> dict[str, object]:
    return {
        "enabled": operator_token_enabled(),
        "required_roles": operator_allowed_roles(),
        "accepted_headers": ["authorization: Bearer <token>", "x-operator-token"],
        "role_headers": operator_role_headers(),
        "session_cookie": operator_session_cookie_name(),
    }


def operator_session_cookie_name() -> str:
    return str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_COOKIE", "")).strip() or DEFAULT_SESSION_COOKIE


def operator_session_secret() -> str:
    return (
        str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_SECRET", "")).strip()
        or str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
        or "nexus-hive-local-session-secret"
    )


def operator_session_ttl_sec() -> int:
    raw = str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_TTL_SEC", "")).strip()
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_SESSION_TTL_SEC
    if parsed <= 0:
        return DEFAULT_SESSION_TTL_SEC
    return min(parsed, 7 * 24 * 60 * 60)


def operator_session_secure() -> bool:
    configured = str(os.getenv("NEXUS_HIVE_OPERATOR_SESSION_SECURE", "")).strip().lower()
    if configured in {"1", "true", "yes"}:
        return True
    if configured in {"0", "false", "no"}:
        return False
    return str(os.getenv("NODE_ENV", "")).strip().lower() == "production"


def _to_base64_url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def _from_base64_url(value: str) -> str:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")


def _sign_payload(payload: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(
            operator_session_secret().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8").rstrip("=")


def _parse_cookie_header(value: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for chunk in str(value or "").split(";"):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = raw_value.strip()
    return cookies


def _read_operator_session_record(request: Request) -> dict[str, object] | None:
    encoded = _parse_cookie_header(request.headers.get("cookie")).get(operator_session_cookie_name())
    if not encoded or "." not in encoded:
        return None
    payload, signature = encoded.split(".", 1)
    expected = _sign_payload(payload)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        parsed = json.loads(_from_base64_url(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    expires_at = str(parsed.get("expires_at") or "").strip()
    credential = str(parsed.get("credential") or "").strip()
    if not credential or not expires_at:
        return None
    if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        return None
    return {
        "auth_mode": "token",
        "credential": credential,
        "expires_at": expires_at,
        "issued_at": str(parsed.get("issued_at") or "").strip(),
        "roles": [
            role.strip().lower()
            for role in parsed.get("roles") or []
            if str(role).strip()
        ],
        "subject": str(parsed.get("subject") or "").strip() or None,
    }


def read_operator_session(request: Request) -> dict[str, object] | None:
    record = _read_operator_session_record(request)
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
    record = _read_operator_session_record(request)
    if not record:
        return None

    existing_headers = list(request.scope.get("headers", []))
    header_names = {name.decode("latin-1").lower() for name, _ in existing_headers}
    if "authorization" not in header_names and "x-operator-token" not in header_names:
        existing_headers.append((b"x-operator-token", str(record["credential"]).encode("utf-8")))
    if "x-operator-role" not in header_names and "x-operator-roles" not in header_names and record["roles"]:
        existing_headers.append((b"x-operator-roles", ",".join(record["roles"]).encode("utf-8")))
    request.scope["headers"] = existing_headers
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
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=operator_session_ttl_sec())
    payload = _to_base64_url(
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
    signature = _sign_payload(payload)
    parts = [
        f"{operator_session_cookie_name()}={payload}.{signature}",
        "Path=/",
        f"Max-Age={operator_session_ttl_sec()}",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if operator_session_secure():
        parts.append("Secure")
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
    parts = [
        f"{operator_session_cookie_name()}=",
        "Path=/",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
        "Max-Age=0",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if operator_session_secure():
        parts.append("Secure")
    return "; ".join(parts)


def read_presented_roles(request: Request) -> list[str]:
    values: list[str] = []
    for header in ROLE_HEADERS:
        raw = str(request.headers.get(header, "")).strip()
        if raw:
            values.extend(raw.split(","))
    return [value.strip().lower() for value in values if value.strip()]


def require_operator_token(request: Request) -> None:
    expected = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
    if expected:
        header_token = str(request.headers.get("x-operator-token", "")).strip()
        authorization = str(request.headers.get("authorization", "")).strip()
        bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if header_token != expected and bearer_token != expected:
            raise HTTPException(status_code=403, detail="missing or invalid operator token")

    allowed_roles = operator_allowed_roles()
    if allowed_roles:
        presented_roles = read_presented_roles(request)
        if not any(role in allowed_roles for role in presented_roles):
            raise HTTPException(status_code=403, detail="missing required operator role")
