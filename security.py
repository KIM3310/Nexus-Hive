from __future__ import annotations

import os

from fastapi import HTTPException, Request

ROLE_HEADERS = ("x-operator-role", "x-operator-roles")


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
    }


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

