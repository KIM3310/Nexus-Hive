"""
Build-time helpers: runtime meta, runtime brief, answer schema.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from config import (
    ALLOW_HEURISTIC_FALLBACK,
    DB_PATH,
    GOVERNANCE_SCORECARD_SCHEMA,
    LAKEHOUSE_READINESS_PACK_SCHEMA,
    MODEL_NAME,
    OLLAMA_URL,
    QUERY_APPROVAL_BOARD_SCHEMA,
    QUERY_SESSION_BOARD_SCHEMA,
    SEMANTIC_GOVERNANCE_PACK_SCHEMA,
    build_openai_runtime_contract,
    get_db_schema,
)
from policy.audit import (
    build_query_audit_schema,
    build_query_review_board,
)
from policy.governance import (
    build_governance_scorecard,
    build_warehouse_brief,
)
from review_resource_pack import build_review_resource_pack
from runtime_store import build_runtime_store_summary
from security import (
    operator_auth_status,
    operator_role_headers,
    operator_session_cookie_name,
    operator_token_enabled,
)
from warehouse_adapter import get_active_warehouse_adapter


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
