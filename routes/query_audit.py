"""
Query audit, session board, approval board, and review board route handlers.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from config import utc_now_iso
from policy.audit import (
    build_query_approval_board,
    build_query_audit_schema,
    build_query_audit_summary,
    build_query_review_board,
    build_query_session_board,
    clamp_audit_limit,
    get_query_audit_history,
    list_recent_query_audits,
    normalize_audit_status_filter,
    normalize_fallback_mode_filter,
    normalize_policy_decision_filter,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory archive set for soft-deleted audit entries
# ---------------------------------------------------------------------------
_archived_request_ids: set[str] = set()


@router.get("/api/query-audit/summary")
async def query_audit_summary_endpoint(
    limit: int = 5,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_audit_summary(
            fallback_mode=fallback_mode, limit=limit, status=status, policy_decision=policy_decision
        ),
    }


@router.get("/api/query-review-board")
async def query_review_board_endpoint(
    limit: int = 5,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_review_board(
            fallback_mode=fallback_mode, limit=limit, status=status, policy_decision=policy_decision
        ),
    }


@router.get("/api/query-session-board")
async def query_session_board_endpoint(
    limit: int = 6,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_session_board(
            fallback_mode=fallback_mode, limit=limit, status=status, policy_decision=policy_decision
        ),
    }


@router.get("/api/query-approval-board")
async def query_approval_board_endpoint(limit: int = 5):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_approval_board(limit=limit),
    }


@router.get("/api/query-audit/recent")
async def query_audit_recent_endpoint(
    limit: int = 5,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    items = list_recent_query_audits(
        limit=limit,
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )
    # Filter out soft-deleted (archived) entries
    items = [i for i in items if i.get("request_id") not in _archived_request_ids]
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_query_audit_schema()["schema"],
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": clamp_audit_limit(limit),
        },
        "items": items,
    }


@router.get("/api/query-audit/{request_id}")
async def query_audit_detail_endpoint(request_id: str):
    history = get_query_audit_history(request_id)
    if not history:
        raise HTTPException(status_code=404, detail="request_id not found")
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_query_audit_schema()["schema"],
        "request_id": request_id,
        "latest": history[-1],
        "history": history,
    }


@router.patch("/api/query-audit/{request_id}/archive")
async def query_audit_archive_endpoint(request_id: str):
    """Soft-delete an audit entry by marking it as archived."""
    history = get_query_audit_history(request_id)
    if not history:
        raise HTTPException(status_code=404, detail="request_id not found")
    _archived_request_ids.add(request_id)
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "request_id": request_id,
        "archived": True,
        "message": f"Audit entry {request_id} has been archived.",
    }
