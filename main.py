"""
Nexus-Hive Agent API - Thin FastAPI application entrypoint.

Business logic is delegated to:
  - config.py: shared configuration, constants, utility functions
  - policy/: SQL policy engine, audit trail, governance scorecards
  - graph/: LangGraph agent nodes (translator, executor, visualizer)
  - logging_config.py: structured JSON logging with request ID propagation
  - circuit_breaker.py: Ollama circuit breaker for resilient fallback
  - exceptions.py: specific exception types for governed error handling
"""

import json
import logging
import os
import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote_plus
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# -- Ensure project root on sys.path --
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# -- Structured logging --
from logging_config import configure_logging, set_request_id, clear_request_id

_logger: logging.Logger = configure_logging()

# -- Configuration --
from config import (
    ALLOW_HEURISTIC_FALLBACK,
    AUDIT_LOG_PATH,  # noqa: F401 (monkeypatched in tests)
    DB_PATH,
    DEFAULT_ROLE,
    GOVERNANCE_SCORECARD_SCHEMA,
    LAKEHOUSE_READINESS_PACK_SCHEMA,
    MODEL_NAME,
    OLLAMA_URL,
    OPENAI_BASE_URL,
    OPENAI_TIMEOUT_S,
    QUERY_APPROVAL_BOARD_SCHEMA,
    QUERY_SESSION_BOARD_SCHEMA,
    REVIEWER_QUERY_DEMO_SCHEMA,
    REVIEWER_QUERY_SCENARIOS,
    SEMANTIC_GOVERNANCE_PACK_SCHEMA,
    log_runtime_event,
    normalize_operator_roles,
    utc_now_iso,
    build_openai_runtime_contract,
    enforce_openai_public_rate_limit,
    get_db_schema,
)
import config as _config_module  # for mutable global access

# -- Security --
from security import (
    apply_operator_session,
    clear_operator_session_cookie,
    create_operator_session_cookie,
    operator_allowed_roles,
    operator_auth_status,
    operator_role_headers,
    operator_session_cookie_name,
    operator_token_enabled,
    read_operator_session,
    require_operator_token,
)

# -- Runtime store --
from runtime_store import append_runtime_event, build_runtime_store_summary
from review_resource_pack import build_review_resource_pack

# -- Warehouse --
from warehouse_adapter import get_active_warehouse_adapter
from snowflake_adapter import snowflake_configured
from databricks_adapter import databricks_configured

# -- Policy engine --
from policy.engine import (
    build_policy_approval_bundle,
    build_policy_schema,
    build_query_tag,
    build_query_tag_contract,
    evaluate_sql_policy,  # noqa: F401 (used via APP_MODULE in tests)
)
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
    write_query_audit_snapshot as _write_query_audit_snapshot,
)


def _sync_audit_log_path() -> None:
    """Propagate any monkeypatched AUDIT_LOG_PATH back to config so audit I/O sees the override."""
    # Use globals() to read the current module-level AUDIT_LOG_PATH,
    # which may have been overridden by monkeypatch.setattr.
    current = globals().get("AUDIT_LOG_PATH")
    if current is not None and current != _config_module.AUDIT_LOG_PATH:
        _config_module.AUDIT_LOG_PATH = current


def write_query_audit_snapshot(**kwargs):
    _sync_audit_log_path()
    return _write_query_audit_snapshot(**kwargs)


from policy.governance import (
    build_gold_eval_pack,
    build_governance_scorecard,
    build_lineage_schema,
    build_metric_layer_schema,
    build_warehouse_brief,
    build_warehouse_target_scorecard,
    run_gold_eval_suite,
)

# -- LangGraph agent --
from graph import (  # noqa: F401 (re-exported for test monkeypatching)
    ask_ollama,
    build_graph,
    translator_node,
    executor_node,
    visualizer_node,
)

# -- OpenAI helpers (kept inline since they are small and route-specific) --
import httpx


async def call_openai_moderation(api_key: str, payload: str) -> None:
    async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_S) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/moderations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": "omni-moderation-latest", "input": payload},
        )
        response.raise_for_status()
        data = response.json()
    if data.get("results", [{}])[0].get("flagged"):
        raise HTTPException(status_code=400, detail="reviewer scenario blocked by moderation")


async def call_openai_reviewer_demo_summary(
    api_key: str, model: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_S) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a governed analytics reviewer. Return JSON with keys "
                            "reviewerSummary, warehouseFit, approvalReason, metricTrust, nextAction."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=True),
                    },
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
    content = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=502, detail="OpenAI reviewer demo returned empty content")
    try:
        result: Dict[str, Any] = json.loads(content)
        return result
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail="OpenAI reviewer demo returned invalid JSON"
        ) from exc


# ---------------------------------------------------------------------------
# Build-time helpers (runtime brief, review pack, meta, answer schema)
# ---------------------------------------------------------------------------


def build_answer_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-answer-v1",
        "required_sections": [
            "question",
            "sql_query",
            "chart_config",
            "result_preview",
            "agent_trace",
            "runtime_posture",
        ],
        "operator_rules": [
            "Only read-only SQL is allowed through the executor agent.",
            "Chart configuration should be derived from result shape, not hard-coded assumptions.",
            "If SQL fails, the self-correction loop retries up to 3 times before returning a controlled failure.",
        ],
    }


def build_runtime_meta() -> Dict[str, Any]:
    active_adapter = get_active_warehouse_adapter()
    openai_runtime = build_openai_runtime_contract()
    db_exists = DB_PATH.exists()
    db_size_bytes = DB_PATH.stat().st_size if db_exists else 0
    schema_loaded = bool(get_db_schema().strip())
    warehouse_brief = build_warehouse_brief()
    runtime_persistence = build_runtime_store_summary(5)
    diagnostics = {
        "db_ready": db_exists and schema_loaded,
        "db_size_bytes": db_size_bytes,
        "schema_loaded": schema_loaded,
        "adapter_name": active_adapter.contract.name,
        "adapter_execution_mode": active_adapter.contract.execution_mode,
        "ollama_configured": OLLAMA_URL.startswith("http"),
        "warehouse_mode": warehouse_brief["warehouse_mode"],
        "fallback_mode": warehouse_brief["fallback_mode"],
        "quality_gate_status": warehouse_brief["quality_gate"]["status"],
        "recent_audit_count": warehouse_brief["recent_audit_count"],
        "runtime_event_count": runtime_persistence["persisted_count"],
        "next_action": (
            "POST /api/runtime/reviewer-query-demo with a fixed question_id for the bounded public warehouse demo."
            if openai_runtime["publicLiveApi"]
            else "POST /api/ask with an executive question, then follow the returned /api/stream URL."
            if db_exists
            and schema_loaded
            and (OLLAMA_URL.startswith("http") or ALLOW_HEURISTIC_FALLBACK)
            else "Run `python3 seed_db.py` and verify either Ollama or heuristic fallback is enabled before live demos."
        ),
    }
    return {
        "service": "nexus-hive",
        "model": MODEL_NAME,
        "ollama_url": OLLAMA_URL,
        "db_path": str(DB_PATH),
        "warehouse_adapter": active_adapter.describe(),
        "diagnostics": diagnostics,
        "auth": {
            "operator_token_enabled": operator_token_enabled(),
            "operator_required_roles": operator_auth_status()["required_roles"],
            "operator_role_headers": operator_role_headers(),
            "operator_session_cookie": operator_session_cookie_name(),
        },
        "ops_contract": {
            "schema": "ops-envelope-v1",
            "version": 1,
            "required_fields": ["service", "status", "diagnostics.next_action"],
        },
        "openai": openai_runtime,
        "routes": [
            "/health",
            "/api/meta",
            "/api/runtime/brief",
            "/api/runtime/review-resource-pack",
            "/api/runtime/warehouse-mode-switchboard",
            "/api/runtime/warehouse-brief",
            "/api/runtime/warehouse-target-scorecard",
            "/api/runtime/governance-scorecard",
            "/api/runtime/semantic-governance-pack",
            "/api/runtime/lakehouse-readiness-pack",
            "/api/runtime/reviewer-query-demo",
            "/api/auth/session",
            "/api/review-pack",
            "/api/schema/answer",
            "/api/schema/lineage",
            "/api/schema/metrics",
            "/api/schema/policy",
            "/api/schema/query-tag",
            "/api/schema/query-audit",
            "/api/evals/nl2sql-gold",
            "/api/evals/nl2sql-gold/run",
            "/api/policy/check",
            "/api/query-session-board",
            "/api/query-approval-board",
            "/api/query-review-board",
            "/api/query-audit/summary",
            "/api/query-audit/recent",
            "/api/query-audit/{request_id}",
            "/api/ask",
            "/api/stream",
        ],
        "capabilities": [
            "natural-language-to-sql",
            "audit-safe-readonly-execution",
            "chart-config-generation",
            "sse-agent-trace-streaming",
            "runtime-brief-surface",
            "review-resource-pack-surface",
            "warehouse-mode-switchboard-surface",
            "warehouse-brief-surface",
            "warehouse-target-scorecard-surface",
            "semantic-governance-pack-surface",
            "lakehouse-readiness-pack-surface",
            "reviewer-query-demo-surface",
            "lineage-schema-surface",
            "metric-layer-schema-surface",
            "policy-schema-surface",
            "query-tag-schema-surface",
            "query-audit-surface",
            "gold-eval-surface",
            "policy-preview-surface",
            "query-session-board-surface",
            "query-review-board-surface",
            "query-audit-summary-surface",
            "query-audit-detail-surface",
            "governance-scorecard-surface",
            "review-pack-surface",
            "answer-schema-surface",
        ],
    }


def build_runtime_brief() -> Dict[str, Any]:
    runtime_meta = build_runtime_meta()
    warehouse_brief = build_warehouse_brief()
    governance_scorecard = build_governance_scorecard("quality")
    review_resource_pack = build_review_resource_pack()
    diagnostics = runtime_meta["diagnostics"]
    db_ready = diagnostics["db_ready"]

    return {
        "status": "ok" if db_ready else "degraded",
        "service": "nexus-hive",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness_contract": "nexus-hive-runtime-brief-v1",
        "headline": "Federated BI copilot that turns executive questions into audited SQL, executes them safely, and renders chart-ready answers.",
        "diagnostics": diagnostics,
        "deploymentMode": runtime_meta["openai"]["deploymentMode"],
        "publicLiveApi": runtime_meta["openai"]["publicLiveApi"],
        "liveModel": runtime_meta["openai"]["liveModel"],
        "model": MODEL_NAME,
        "report_contract": build_answer_schema(),
        "evidence_counts": {
            "agent_nodes": 3,
            "retry_budget": 3,
            "seeded_rows": 10000,
            "runtime_routes": len(runtime_meta["routes"]),
            "review_pack_scenarios": review_resource_pack["summary"]["scenario_count"],
        },
        "warehouse_contract": {
            "mode": warehouse_brief["warehouse_mode"],
            "fallback_mode": warehouse_brief["fallback_mode"],
            "quality_gate_schema": warehouse_brief["quality_gate"]["schema"],
            "lineage_schema": warehouse_brief["lineage"]["schema"],
            "metric_layer_schema": warehouse_brief["metric_layer"]["schema"],
            "policy_schema": warehouse_brief["policy"]["schema"],
            "semantic_governance_pack_schema": SEMANTIC_GOVERNANCE_PACK_SCHEMA,
            "lakehouse_readiness_pack_schema": LAKEHOUSE_READINESS_PACK_SCHEMA,
            "query_tag_schema": warehouse_brief["query_tag_contract"]["schema"],
            "query_audit_schema": build_query_audit_schema()["schema"],
            "query_session_board_schema": QUERY_SESSION_BOARD_SCHEMA,
            "query_approval_board_schema": QUERY_APPROVAL_BOARD_SCHEMA,
            "query_review_board_schema": build_query_review_board()["schema"],
            "query_audit_summary_schema": warehouse_brief["audit_summary"]["schema"],
            "governance_scorecard_schema": GOVERNANCE_SCORECARD_SCHEMA,
            "gold_eval_schema": warehouse_brief["gold_eval"]["schema"],
            "gold_eval_run_schema": warehouse_brief["gold_eval_run"]["schema"],
            "operator_auth_enabled": operator_token_enabled(),
            "operator_required_roles": operator_auth_status()["required_roles"],
            "runtime_persistence_enabled": governance_scorecard["persistence"]["enabled"],
        },
        "review_flow": [
            "Open /health to confirm database and model posture.",
            "Read /api/runtime/warehouse-brief for adapter mode, lineage, and quality-gate posture.",
            "Read /api/runtime/review-resource-pack for the built-in no-key walkthrough before any live demo claim.",
            "Read /api/schema/metrics to confirm the semantic metric contract before trusting warehouse-target claims.",
            "Read /api/runtime/semantic-governance-pack to see metric certification, approval posture, and warehouse survival in one surface.",
            "Read /api/runtime/lakehouse-readiness-pack to compress Snowflake and Databricks delivery posture into one platform-facing surface.",
            "Use /api/runtime/reviewer-query-demo with a fixed question_id when you need a bounded public live warehouse demo.",
            "Read /api/schema/query-tag to verify warehouse tagging and audit dimensions before a live review.",
            "Read /api/runtime/brief for agent contract, retry policy, and reviewer guidance.",
            "Open /api/query-session-board to revisit saved analyst sessions before re-running a question.",
            "Ask a question through /api/ask or the frontend to validate SQL, execution, and chart generation.",
            "Inspect the streamed agent trace before trusting any rendered answer.",
        ],
        "watchouts": [
            "The visualization agent uses the shape of returned rows; poor SQL still yields poor charts.",
            "Ollama availability affects live demos, but the runtime brief remains available without it.",
            "SQLite is used as a local warehouse stand-in, not a claim of production warehouse scale.",
            "Query tags are governance proof fields and not a substitute for warehouse-native access controls.",
        ],
        "agent_contract": [
            {
                "agent": "translator",
                "responsibility": "Generate SQL from natural language and schema context.",
            },
            {
                "agent": "executor",
                "responsibility": "Block unsafe SQL and execute read-only analytics queries.",
            },
            {
                "agent": "visualizer",
                "responsibility": "Infer a Chart.js payload from the result shape.",
            },
        ],
        "routes": runtime_meta["routes"],
        "links": {"reviewer_query_demo": "/api/runtime/reviewer-query-demo"},
    }


# ---------------------------------------------------------------------------
# SSE streaming helper
# ---------------------------------------------------------------------------


async def run_agent_and_stream(question: str, request_id: str):
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

    async for output in graph.astream(state):
        node_name = list(output.keys())[0]
        node_state = output[node_name]
        for log in node_state["log_stream"]:
            yield f"data: {json.dumps({'type': 'log', 'content': log})}\n\n"
            await asyncio.sleep(0.1)
        node_state["log_stream"] = []
        if node_name == "visualizer":
            yield f"data: {json.dumps({'type': 'chart_data', 'config': node_state['chart_config'], 'data': node_state['db_result']})}\n\n"
        state = node_state

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


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str


class ReviewerQueryDemoRequest(BaseModel):
    question_id: str


class PolicyCheckRequest(BaseModel):
    sql: str
    role: str = DEFAULT_ROLE


# ---------------------------------------------------------------------------
# Build the LangGraph and FastAPI app
# ---------------------------------------------------------------------------

graph = build_graph()

app = FastAPI(
    title="Nexus-Hive Agent API",
    description=(
        "Multi-agent NL-to-SQL BI copilot with governed analytics, "
        "audit trails, and multi-warehouse support (SQLite, Snowflake, Databricks)."
    ),
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "https://nexus-hive.pages.dev",
    ],
    allow_origin_regex=r"^https://([a-z0-9-]+\.)?nexus-hive\.pages\.dev$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def session_and_logging_middleware(request: Request, call_next):
    """Middleware that propagates request IDs, applies operator sessions, and logs request lifecycle."""
    _sync_audit_log_path()
    request_id: str = str(request.headers.get("x-request-id") or uuid4().hex[:12]).strip()
    request.state.request_id = request_id
    set_request_id(request_id)
    request.state.operator_session = apply_operator_session(request)
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
    if origin and (
        origin
        in {
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "https://nexus-hive.pages.dev",
        }
        or re.match(r"^https://([a-z0-9-]+\.)?nexus-hive\.pages\.dev$", origin)
    ):
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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
async def health_endpoint():
    runtime_meta = build_runtime_meta()
    return {
        "status": "ok" if runtime_meta["diagnostics"]["db_ready"] else "degraded",
        **runtime_meta,
        "links": {
            "meta": "/api/meta",
            "runtime_brief": "/api/runtime/brief",
            "review_resource_pack": "/api/runtime/review-resource-pack",
            "warehouse_mode_switchboard": "/api/runtime/warehouse-mode-switchboard",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "semantic_governance_pack": "/api/runtime/semantic-governance-pack",
            "lakehouse_readiness_pack": "/api/runtime/lakehouse-readiness-pack",
            "reviewer_query_demo": "/api/runtime/reviewer-query-demo",
            "auth_session": "/api/auth/session",
            "review_pack": "/api/review-pack",
            "answer_schema": "/api/schema/answer",
            "lineage_schema": "/api/schema/lineage",
            "metric_layer_schema": "/api/schema/metrics",
            "query_audit_schema": "/api/schema/query-audit",
            "query_tag_schema": "/api/schema/query-tag",
            "query_session_board": "/api/query-session-board",
            "query_approval_board": "/api/query-approval-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
        },
    }


@app.get("/api/meta")
async def meta_endpoint():
    runtime_meta = build_runtime_meta()
    return {
        "status": "ok" if runtime_meta["diagnostics"]["db_ready"] else "degraded",
        "generated_at": utc_now_iso(),
        **runtime_meta,
        "readiness_contract": "nexus-hive-runtime-brief-v1",
        "warehouse_brief_contract": "nexus-hive-warehouse-brief-v1",
        "warehouse_mode_switchboard_contract": "nexus-hive-warehouse-mode-switchboard-v1",
        "warehouse_target_scorecard_contract": "nexus-hive-warehouse-target-scorecard-v1",
        "governance_scorecard_contract": "nexus-hive-governance-scorecard-v1",
        "semantic_governance_pack_contract": "nexus-hive-semantic-governance-pack-v1",
        "lakehouse_readiness_pack_contract": "nexus-hive-lakehouse-readiness-pack-v1",
        "review_pack_contract": "nexus-hive-review-pack-v1",
        "report_contract": build_answer_schema(),
        "lineage_contract": "nexus-hive-lineage-v1",
        "metric_layer_contract": "nexus-hive-metric-layer-v1",
        "policy_contract": "nexus-hive-policy-v1",
        "query_tag_contract": "nexus-hive-query-tag-v1",
        "query_audit_contract": "nexus-hive-query-audit-v1",
        "query_session_board_contract": "nexus-hive-query-session-board-v1",
        "query_approval_board_contract": "nexus-hive-query-approval-board-v1",
        "query_review_board_contract": "nexus-hive-query-review-board-v1",
        "query_audit_summary_contract": "nexus-hive-query-audit-summary-v1",
        "gold_eval_contract": "nexus-hive-gold-eval-v1",
    }


@app.get("/api/runtime/brief")
async def runtime_brief_endpoint():
    return build_runtime_brief()


@app.get("/api/runtime/warehouse-brief")
async def warehouse_brief_endpoint():
    return build_warehouse_brief()


@app.get("/api/runtime/warehouse-mode-switchboard")
async def warehouse_mode_switchboard_endpoint():
    active_adapter = get_active_warehouse_adapter()
    return {
        "status": "ok",
        "service": "nexus-hive",
        "schema": "nexus-hive-warehouse-mode-switchboard-v1",
        "headline": "Compact board for comparing SQLite preview, Snowflake live posture, and Databricks live posture before a reviewer switches lanes.",
        "active_target": active_adapter.contract.name,
        "active_execution_mode": active_adapter.contract.execution_mode,
        "targets": [
            {
                "target": "sqlite-demo",
                "configured": True,
                "execution_mode": "local-sqlite",
                "primary_surface": "/api/runtime/brief",
                "why_it_matters": "Fastest no-key review path for governed analytics and audit posture.",
            },
            {
                "target": "snowflake-sql-contract",
                "configured": snowflake_configured(),
                "execution_mode": "snowflake-live"
                if snowflake_configured()
                else "contract-preview",
                "primary_surface": "/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract",
                "why_it_matters": "Best path when reviewer trust depends on live Snowflake execution and metric certification.",
            },
            {
                "target": "databricks-sql-contract",
                "configured": databricks_configured(),
                "execution_mode": "databricks-live"
                if databricks_configured()
                else "contract-preview",
                "primary_surface": "/api/runtime/lakehouse-readiness-pack?target=databricks-sql-contract",
                "why_it_matters": "Best path when reviewer trust depends on live Databricks SQL execution and lakehouse delivery posture.",
            },
        ],
        "review_sequence": [
            "Read /api/runtime/brief for the overall governed runtime posture.",
            "Use /api/runtime/warehouse-mode-switchboard to decide which warehouse lane is the strongest current proof.",
            "Open the target-specific scorecard or readiness pack before making a live warehouse claim.",
        ],
        "links": {
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "lakehouse_readiness_pack": "/api/runtime/lakehouse-readiness-pack",
        },
    }


@app.get("/api/runtime/warehouse-target-scorecard")
async def warehouse_target_scorecard_endpoint(target: Optional[str] = None):
    try:
        return build_warehouse_target_scorecard(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runtime/reviewer-query-demo")
async def reviewer_query_demo_endpoint(req: ReviewerQueryDemoRequest):
    runtime = build_openai_runtime_contract()
    if not runtime["publicLiveApi"]:
        raise HTTPException(
            status_code=503,
            detail="public OpenAI reviewer demo is unavailable; configure OPENAI_API_KEY and keep budgets above zero",
        )
    scenario_id = str(req.question_id or "").strip().lower()
    scenario = REVIEWER_QUERY_SCENARIOS.get(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=400,
            detail="question_id must be one of revenue-by-region or profit-top-regions",
        )
    enforce_openai_public_rate_limit(f"reviewer-demo:{scenario_id}", int(runtime["publicRpm"]))
    payload = {
        "question_id": scenario_id,
        "question": scenario["question"],
        "sql": scenario["sql"],
        "metric_ids": scenario["metric_ids"],
        "warehouse_target": scenario["warehouse_target"],
        "approval_posture": scenario["approval_posture"],
        "lineage_schema": build_lineage_schema()["schema"],
        "metric_layer_schema": build_metric_layer_schema()["schema"],
    }
    api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
    if runtime["moderationEnabled"]:
        await call_openai_moderation(api_key, json.dumps(payload, ensure_ascii=True))
    live_summary = await call_openai_reviewer_demo_summary(
        api_key, str(runtime["liveModel"]), payload
    )
    _config_module.LAST_OPENAI_LIVE_RUN_AT = utc_now_iso()
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "reviewer_query_demo",
            "method": "POST",
            "path": "/api/runtime/reviewer-query-demo",
            "status": "ok",
            "question_id": scenario_id,
            "at": utc_now_iso(),
        }
    )
    return {
        "status": "ok",
        "service": "nexus-hive",
        "schema": REVIEWER_QUERY_DEMO_SCHEMA,
        "mode": runtime["deploymentMode"],
        "model": runtime["liveModel"],
        "scenarioId": scenario_id,
        "moderated": True,
        "capped": True,
        "traceId": uuid4().hex[:12],
        "estimatedCostUsd": scenario["estimated_cost_usd"],
        "nextReviewPath": scenario["next_review_path"],
        "result": {
            "question": scenario["question"],
            "sql": scenario["sql"],
            "metricIds": scenario["metric_ids"],
            "approvalPosture": scenario["approval_posture"],
            "warehouseFit": scenario["warehouse_target"],
            "lineage": build_lineage_schema()["schema"],
            "metricLayer": build_metric_layer_schema()["schema"],
            **live_summary,
        },
    }


@app.get("/api/auth/session")
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


@app.post("/api/auth/session")
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
    expected = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
    if credential != expected:
        raise HTTPException(status_code=403, detail="missing or invalid operator token")
    allowed_roles = operator_allowed_roles()
    if allowed_roles and not any(role in allowed_roles for role in roles):
        raise HTTPException(status_code=403, detail="missing required operator role")
    cookie, session = create_operator_session_cookie(
        credential=credential, roles=roles or allowed_roles, subject="token-operator"
    )
    response.headers["set-cookie"] = cookie
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


@app.delete("/api/auth/session")
async def clear_auth_session(request: Request, response: Response):
    response.headers["set-cookie"] = clear_operator_session_cookie()
    log_runtime_event(
        "info", "operator-session-cleared", request_id=getattr(request.state, "request_id", None)
    )
    return {"ok": True, "active": False, "cookie_name": operator_session_cookie_name()}


@app.get("/api/schema/answer")
async def answer_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_answer_schema(),
    }


@app.get("/api/schema/lineage")
async def lineage_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_lineage_schema(),
    }


@app.get("/api/schema/metrics")
async def metric_layer_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_metric_layer_schema(),
    }


@app.get("/api/schema/policy")
async def policy_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_policy_schema(),
    }


@app.get("/api/schema/query-tag")
async def query_tag_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_tag_contract(),
    }


@app.get("/api/schema/query-audit")
async def query_audit_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_audit_schema(),
    }


@app.get("/api/evals/nl2sql-gold")
async def gold_eval_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_gold_eval_pack(),
    }


@app.get("/api/evals/nl2sql-gold/run")
async def gold_eval_run_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **run_gold_eval_suite(),
    }


@app.post("/api/policy/check")
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


@app.get("/api/query-audit/summary")
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


@app.get("/api/query-review-board")
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


@app.get("/api/query-session-board")
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


@app.get("/api/query-approval-board")
async def query_approval_board_endpoint(limit: int = 5):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_approval_board(limit=limit),
    }


@app.get("/api/query-audit/recent")
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


@app.get("/api/query-audit/{request_id}")
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


@app.post("/api/ask")
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
    write_query_audit_snapshot(
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


@app.get("/api/stream")
async def stream_endpoint(q: str, rid: Optional[str] = None):
    request_id = str(rid or uuid4().hex[:12]).strip()
    return StreamingResponse(
        run_agent_and_stream(q, request_id=request_id), media_type="text/event-stream"
    )


# Mount frontend
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_path, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
