"""
FastAPI middleware for session management, request logging, and CORS headers.
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import Request

from config import log_runtime_event
from logging_config import set_request_id, clear_request_id
from uuid import uuid4

_logger = logging.getLogger("nexus_hive")

ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "https://nexus-hive.pages.dev",
}
ORIGIN_REGEX = r"^https://([a-z0-9-]+\.)?nexus-hive\.pages\.dev$"


async def session_and_logging_middleware(request: Request, call_next, sync_audit_log_path, apply_operator_session_fn):
    """Middleware that propagates request IDs, applies operator sessions, and logs request lifecycle."""
    sync_audit_log_path()
    request_id: str = str(request.headers.get("x-request-id") or uuid4().hex[:12]).strip()
    request.state.request_id = request_id
    set_request_id(request_id)
    request.state.operator_session = apply_operator_session_fn(request)
    _logger.info(
        "Request started: %s %s",
        request.method,
        request.url.path,
        extra={
            "extra_fields": {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            }
        },
    )
    started: datetime = datetime.now(timezone.utc)
    try:
        response = await call_next(request)
    except Exception as error:
        elapsed_ms: int = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        _logger.error(
            "Request failed: %s %s (%dms) - %s",
            request.method,
            request.url.path,
            elapsed_ms,
            error,
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "elapsed_ms": elapsed_ms,
                    "error": str(error),
                }
            },
        )
        log_runtime_event(
            "error",
            "request-failed",
            elapsed_ms=elapsed_ms,
            error=str(error),
            method=request.method,
            path=request.url.path,
            request_id=request_id,
        )
        clear_request_id()
        raise
    origin = str(request.headers.get("origin") or "").strip()
    if origin and (origin in ALLOWED_ORIGINS or re.match(ORIGIN_REGEX, origin)):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["x-request-id"] = request_id
    response.headers["cache-control"] = "no-store"
    elapsed_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    log_level: str = "warn" if response.status_code >= 400 or elapsed_ms >= 4000 else "info"
    _logger.log(
        logging.WARNING if log_level == "warn" else logging.INFO,
        "Request finished: %s %s -> %d (%dms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        extra={
            "extra_fields": {
                "request_id": request_id,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            }
        },
    )
    log_runtime_event(
        log_level,
        "request-finished",
        elapsed_ms=elapsed_ms,
        method=request.method,
        path=request.url.path,
        request_id=request_id,
        status_code=response.status_code,
    )
    clear_request_id()
    return response
