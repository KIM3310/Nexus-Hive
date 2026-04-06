"""
Health, meta, and runtime brief route handlers.
"""

from fastapi import APIRouter, Response

from config import utc_now_iso
from policy.governance import build_warehouse_brief
from services.build_helpers import build_answer_schema, build_runtime_brief, build_runtime_meta

router = APIRouter()


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/health")
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


@router.get("/api/meta")
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


@router.get("/api/runtime/brief")
async def runtime_brief_endpoint():
    return build_runtime_brief()


@router.get("/api/runtime/warehouse-brief")
async def warehouse_brief_endpoint():
    return build_warehouse_brief()
