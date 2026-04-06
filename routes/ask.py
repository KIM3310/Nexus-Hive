"""
Ask and stream route handlers for the LangGraph agent pipeline.
"""

from typing import Optional
from urllib.parse import quote_plus
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import DEFAULT_ROLE, utc_now_iso
from models import AskRequest
from policy.audit import write_query_audit_snapshot as _write_audit
from policy.engine import build_query_tag
from runtime_store import append_runtime_event
from security import require_operator_token
from warehouse_adapter import get_active_warehouse_adapter

router = APIRouter()

# Graph is injected at registration time by main.py
_graph = None


def configure(graph, write_query_audit_snapshot=None):
    """Inject runtime dependencies from main.py.

    ``write_query_audit_snapshot`` is accepted for backward compatibility
    but the route now calls policy.audit directly (the middleware has already
    synced AUDIT_LOG_PATH before the handler runs).
    """
    global _graph
    _graph = graph


@router.post("/api/ask")
async def ask_endpoint(req: AskRequest, request: Request):
    require_operator_token(request)
    question = str(req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > 1000:
        raise HTTPException(status_code=413, detail="question is too long")
    request_id = uuid4().hex[:12]
    active_adapter = get_active_warehouse_adapter()
    query_tag = build_query_tag(
        request_id=request_id,
        role=DEFAULT_ROLE,
        purpose="ask",
        adapter_name=active_adapter.contract.name,
    )
    _write_audit(
        request_id=request_id,
        question=question,
        status="accepted",
        stage="accepted",
        adapter_name=active_adapter.contract.name,
        query_tag=query_tag,
        policy_decision="pending",
        policy_reasons=[],
        fallback_sql_used=False,
        fallback_chart_used=False,
    )
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "ask_accepted",
            "method": "POST",
            "path": "/api/ask",
            "request_id": request_id,
            "status": "accepted",
            "question": question,
            "at": utc_now_iso(),
        }
    )
    stream_url = str(request.url_for("stream_endpoint"))
    return {
        "status": "accepted",
        "message": "Use the SSE stream endpoint to receive the full agent trace.",
        "request_id": request_id,
        "question": question,
        "query_tag_preview": query_tag,
        "stream_url": f"{stream_url}?q={quote_plus(question)}&rid={request_id}",
        "links": {
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "answer_schema": "/api/schema/answer",
            "query_tag_schema": "/api/schema/query-tag",
            "gold_eval": "/api/evals/nl2sql-gold",
            "query_session_board": "/api/query-session-board",
            "query_approval_board": "/api/query-approval-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": f"/api/query-audit/{request_id}",
        },
    }


@router.get("/api/stream")
async def stream_endpoint(q: str, rid: Optional[str] = None):
    from services.streaming import run_agent_and_stream

    request_id = str(rid or uuid4().hex[:12]).strip()
    return StreamingResponse(
        run_agent_and_stream(q, request_id=request_id, graph=_graph, write_query_audit_snapshot=_write_audit),
        media_type="text/event-stream",
    )
