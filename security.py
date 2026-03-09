from __future__ import annotations

import os

from fastapi import HTTPException, Request


def operator_token_enabled() -> bool:
    return bool(str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip())


def require_operator_token(request: Request) -> None:
    expected = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
    if not expected:
        return

    header_token = str(request.headers.get("x-operator-token", "")).strip()
    authorization = str(request.headers.get("authorization", "")).strip()
    bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if header_token == expected or bearer_token == expected:
        return

    raise HTTPException(status_code=403, detail="missing or invalid operator token")
