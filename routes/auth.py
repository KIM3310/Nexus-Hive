"""
Auth session route handlers.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response

from config import log_runtime_event, normalize_operator_roles
from security import (
    create_operator_session_cookie,
    operator_allowed_roles,
    operator_session_cookie_name,
    operator_session_secure,
    operator_session_ttl_sec,
    operator_token_enabled,
    operator_token_matches,
    read_operator_session,
    require_operator_token,
)

router = APIRouter()


@router.get("/api/auth/session")
async def auth_session_endpoint(request: Request):
    session = read_operator_session(request)
    validation: Optional[Dict[str, Any]] = None
    if session:
        try:
            require_operator_token(request)
            validation = {"ok": True, "reason": None}
        except HTTPException as error:
            validation = {"ok": False, "reason": error.detail}
    return {
        "ok": True,
        "active": bool(session and validation and validation["ok"]),
        "cookie_name": operator_session_cookie_name(),
        "session": session,
        "validation": validation,
    }


@router.post("/api/auth/session")
async def create_auth_session(request: Request, response: Response):
    if not operator_token_enabled():
        raise HTTPException(
            status_code=409, detail="operator auth is not configured for session login"
        )
    payload = await request.json()
    credential = str(payload.get("credential") or "").strip() if isinstance(payload, dict) else ""
    roles = normalize_operator_roles(payload.get("roles")) if isinstance(payload, dict) else []
    if not credential:
        raise HTTPException(status_code=400, detail="missing credential")
    if not operator_token_matches(credential):
        raise HTTPException(status_code=403, detail="missing or invalid operator token")
    allowed_roles = operator_allowed_roles()
    session_roles = [allowed_role for allowed_role in allowed_roles if allowed_role in roles]
    if allowed_roles and not session_roles:
        raise HTTPException(status_code=403, detail="missing required operator role")
    cookie_value, session = create_operator_session_cookie(
        roles=session_roles, subject="token-operator"
    )
    response.set_cookie(
        key=operator_session_cookie_name(),
        value=cookie_value,
        max_age=operator_session_ttl_sec(),
        path="/",
        secure=operator_session_secure(),
        httponly=True,
        samesite="strict",
    )
    log_runtime_event(
        "info",
        "operator-session-created",
        request_id=getattr(request.state, "request_id", None),
        roles=session["roles"],
        subject=session["subject"],
    )
    return {
        "ok": True,
        "active": True,
        "cookie_name": operator_session_cookie_name(),
        "session": session,
    }


@router.delete("/api/auth/session")
async def clear_auth_session(request: Request, response: Response):
    response.delete_cookie(
        key=operator_session_cookie_name(),
        path="/",
        secure=operator_session_secure(),
        httponly=True,
        samesite="strict",
    )
    log_runtime_event(
        "info", "operator-session-cleared", request_id=getattr(request.state, "request_id", None)
    )
    return {"ok": True, "active": False, "cookie_name": operator_session_cookie_name()}
