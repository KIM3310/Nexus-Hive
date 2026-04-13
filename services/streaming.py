"""
SSE streaming helper for the LangGraph agent pipeline.
"""

import asyncio
import json
import logging
from typing import Any

from config import DEFAULT_ROLE, utc_now_iso
from policy.engine import build_query_tag
from runtime_store import append_runtime_event
from warehouse_adapter import get_active_warehouse_adapter

_logger = logging.getLogger("nexus_hive")


async def run_agent_and_stream(question: str, request_id: str, graph, write_query_audit_snapshot):
    """Run the LangGraph agent and yield SSE events.

    Parameters
    ----------
    question : str
        The natural-language question to process.
    request_id : str
        Unique identifier for this request.
    graph : CompiledGraph
        The compiled LangGraph agent graph.
    write_query_audit_snapshot : callable
        Audit snapshot writer (passed in so monkeypatching in tests works).
    """
    active_adapter = get_active_warehouse_adapter()
    query_tag = build_query_tag(
        request_id=request_id,
        role=DEFAULT_ROLE,
        purpose="ask",
        adapter_name=active_adapter.contract.name,
    )
    state = {
        "user_query": question,
        "sql_query": "",
        "db_result": [],
        "chart_config": {},
        "error": "",
        "retry_count": 0,
        "fallback_sql_used": False,
        "fallback_chart_used": False,
        "policy_verdict": {},
        "log_stream": [],
    }

    _AGENT_TIMEOUT_SECONDS = 30

    async def _consume_graph():
        """Run the LangGraph agent and collect streamed outputs."""
        nonlocal state
        async for output in graph.astream(state):
            node_name = list(output.keys())[0]
            node_state = output[node_name]
            for log in node_state["log_stream"]:
                yield log
            node_state["log_stream"] = []
            if node_name == "visualizer":
                yield ("__chart__", node_state["chart_config"], node_state["db_result"])
            state = node_state

    try:
        timed_stream = _consume_graph()
        deadline = asyncio.get_event_loop().time() + _AGENT_TIMEOUT_SECONDS
        async for item in timed_stream:
            if asyncio.get_event_loop().time() > deadline:
                raise asyncio.TimeoutError()
            if isinstance(item, tuple) and len(item) == 3 and item[0] == "__chart__":
                yield f"data: {json.dumps({'type': 'chart_data', 'config': item[1], 'data': item[2]})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'log', 'content': item})}\n\n"
                await asyncio.sleep(0.1)
    except asyncio.TimeoutError:
        _logger.warning(
            "Agent stream timed out after %ds for request_id=%s", _AGENT_TIMEOUT_SECONDS, request_id
        )
        yield f"data: {json.dumps({'type': 'error', 'content': f'[System] Agent timed out after {_AGENT_TIMEOUT_SECONDS}s.'})}\n\n"
        yield 'data: {"type": "done"}\n\n'
        return

    # Extract typed fields from the final agent state for audit logging.
    _db_result: Any = state.get("db_result") or []
    _chart_cfg: Any = state.get("chart_config") or {}
    _policy_v: Any = state.get("policy_verdict") or {}
    _retry_raw: Any = state.get("retry_count") or 0
    _retry: int = int(_retry_raw)
    audit_kwargs = dict(
        request_id=request_id,
        question=question,
        adapter_name=active_adapter.contract.name,
        query_tag=query_tag,
        sql_query=str(state.get("sql_query", "")),
        row_count=len(_db_result),
        retry_count=_retry,
        chart_type=str(_chart_cfg.get("type", "")),
        error=str(state.get("error", "")),
        policy_decision=str(_policy_v.get("decision", "")),
        policy_reasons=list(_policy_v.get("deny_reasons") or [])
        + list(_policy_v.get("review_reasons") or []),
        fallback_sql_used=bool(state.get("fallback_sql_used", False)),
        fallback_chart_used=bool(state.get("fallback_chart_used", False)),
    )

    if state["error"] and _retry >= 3:
        error_msg = state.get("error", "unknown")
        yield f"data: {json.dumps({'type': 'log', 'content': '[System] Agent failed after 3 retries. Error: ' + str(error_msg)})}\n\n"
        write_query_audit_snapshot(status="failed", stage="failed", **audit_kwargs)
        append_runtime_event(
            {
                "service": "nexus-hive",
                "event_type": "stream_failed",
                "method": "GET",
                "path": "/api/stream",
                "request_id": request_id,
                "status": "failed",
                "at": utc_now_iso(),
            }
        )
    else:
        write_query_audit_snapshot(status="completed", stage="completed", **audit_kwargs)
        append_runtime_event(
            {
                "service": "nexus-hive",
                "event_type": "stream_completed",
                "method": "GET",
                "path": "/api/stream",
                "request_id": request_id,
                "status": "completed",
                "at": utc_now_iso(),
            }
        )

    yield 'data: {"type": "done"}\n\n'
