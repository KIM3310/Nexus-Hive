"""
Policy check route handler.
"""

from fastapi import APIRouter, HTTPException, Request

from config import DEFAULT_ROLE, utc_now_iso
from models import PolicyCheckRequest
from policy.engine import (
    build_policy_approval_bundle,
    build_policy_schema,
    build_query_tag,
    evaluate_sql_policy,
)
from runtime_store import append_runtime_event
from security import require_operator_token
from warehouse_adapter import get_active_warehouse_adapter

router = APIRouter()


@router.post("/api/policy/check")
async def policy_check_endpoint(req: PolicyCheckRequest, request: Request):
    require_operator_token(request)
    sql = str(req.sql or "").strip()
    role = str(req.role or DEFAULT_ROLE).strip().lower() or DEFAULT_ROLE
    if not sql:
        raise HTTPException(status_code=400, detail="sql is required")
    verdict = evaluate_sql_policy(sql, role=role)
    approval_bundle = build_policy_approval_bundle(verdict)
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "policy_check",
            "method": "POST",
            "path": "/api/policy/check",
            "status": "ok",
            "role": role,
            "policy_decision": verdict["decision"],
            "at": utc_now_iso(),
        }
    )
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_policy_schema()["schema"],
        "sql": sql,
        "query_tag_preview": build_query_tag(
            request_id=str(getattr(request.state, "request_id", "") or "policy-check"),
            role=role,
            purpose="policy-check",
            adapter_name=get_active_warehouse_adapter().contract.name,
        ),
        "verdict": verdict,
        "approval_required": approval_bundle["approval_required"],
        "approval_actions": approval_bundle["approval_actions"],
        "review_rationale": approval_bundle["review_rationale"],
        "links": {
            "query_approval_board": "/api/query-approval-board",
        },
    }
