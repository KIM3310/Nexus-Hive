from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent
EXTERNAL_DIR = ROOT / "data" / "external" / "global_online_orders"


def build_review_resource_pack() -> Dict[str, Any]:
    scenarios = [
        {
            "scenario_id": "revenue-by-region",
            "question": "Show total net revenue by region",
            "goal": "Keep the shortest governed analytics walkthrough tied to a certified metric and review-safe SQL path.",
            "next_surface": "/api/runtime/semantic-governance-pack",
        },
        {
            "scenario_id": "top-profit-regions",
            "question": "Which regions have the highest profit margin?",
            "goal": "Show how warehouse fit and metric certification stay visible before a chart is trusted.",
            "next_surface": "/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract",
        },
        {
            "scenario_id": "review-required-query",
            "question": "List customer-level revenue rows for APAC",
            "goal": "Explain why review-required and denied queries should stay separate from healthy completed traffic.",
            "next_surface": "/api/query-review-board",
        },
        {
            "scenario_id": "lakehouse-warehouse-fit",
            "question": "Can the same governed metric layer survive across Snowflake and Databricks?",
            "goal": "Tie connector posture to query-tagging, quality gates, and approval boundaries.",
            "next_surface": "/api/runtime/lakehouse-readiness-pack?target=databricks-sql-contract",
        },
    ]

    operator_checks = [
        {
            "check_id": "confirm-runtime",
            "surface": "/health",
            "why_it_matters": "Reviewers should confirm database, model, and fallback posture before reading any answer surface.",
        },
        {
            "check_id": "open-resource-pack",
            "surface": "/api/runtime/review-resource-pack",
            "why_it_matters": "Built-in scenarios keep the strongest no-key walkthrough explicit without private warehouse data.",
        },
        {
            "check_id": "metric-certification",
            "surface": "/api/runtime/semantic-governance-pack",
            "why_it_matters": "Certified metrics and approval posture should stay visible before SQL or chart claims are trusted.",
        },
        {
            "check_id": "review-board",
            "surface": "/api/query-review-board",
            "why_it_matters": "Denied and review-required traffic should remain inspectable instead of blending into healthy queries.",
        },
    ]

    validation_cases = [
        {
            "case_id": "runtime-brief-contract",
            "goal": "Runtime brief should keep warehouse, audit, and retry posture aligned before live review.",
            "proof_surface": "/api/runtime/brief",
        },
        {
            "case_id": "semantic-pack-boundary",
            "goal": "Certified metrics and target posture should remain visible in one review surface.",
            "proof_surface": "/api/runtime/semantic-governance-pack",
        },
        {
            "case_id": "warehouse-fit-preview",
            "goal": "Warehouse-target claims should stay explicit contract previews until live connectors are configured.",
            "proof_surface": "/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract",
        },
        {
            "case_id": "review-board-governance",
            "goal": "Review-required traffic should stay visible through the governed query board and audit summary.",
            "proof_surface": "/api/query-review-board",
        },
    ]

    playbooks = [
        {
            "playbook_id": "runtime-first",
            "entry_surface": "/health",
            "handoff_surface": "/api/runtime/brief",
            "focus": "Use when the reviewer needs the shortest path from service posture to governed analytics proof.",
        },
        {
            "playbook_id": "semantic-metrics-first",
            "entry_surface": "/api/runtime/semantic-governance-pack",
            "handoff_surface": "/api/runtime/warehouse-target-scorecard",
            "focus": "Use when metric trust matters more than raw SQL generation.",
        },
        {
            "playbook_id": "review-board-first",
            "entry_surface": "/api/query-review-board",
            "handoff_surface": "/api/query-audit/summary",
            "focus": "Use when the conversation is about governance failures, denials, and safe escalation.",
        },
    ]

    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": None,
        "schema": "nexus-hive-review-resource-pack-v1",
        "headline": "Built-in governed analytics review pack for a no-key walkthrough.",
        "summary": {
            "scenario_count": len(scenarios),
            "operator_check_count": len(operator_checks),
            "validation_case_count": len(validation_cases),
            "playbook_count": len(playbooks),
        },
        "external_data": {
            "orders_workbook": {
                "present": (EXTERNAL_DIR / "orders_frostonline.xlsx").exists(),
                "path": "data/external/global_online_orders/orders_frostonline.xlsx",
            },
            "schema_sql": {
                "present": (EXTERNAL_DIR / "Amazon.sql").exists(),
                "path": "data/external/global_online_orders/Amazon.sql",
                "statement_count": _count_sql_statements(EXTERNAL_DIR / "Amazon.sql"),
            },
        },
        "scenarios": scenarios,
        "operator_checks": operator_checks,
        "validation_cases": validation_cases,
        "playbooks": playbooks,
        "reviewer_fast_path": [
            "/health",
            "/api/runtime/brief",
            "/api/runtime/review-resource-pack",
            "/api/runtime/semantic-governance-pack",
            "/api/runtime/warehouse-target-scorecard",
            "/api/query-review-board",
            "/api/review-pack",
        ],
        "links": {
            "health": "/health",
            "runtime_brief": "/api/runtime/brief",
            "review_resource_pack": "/api/runtime/review-resource-pack",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "semantic_governance_pack": "/api/runtime/semantic-governance-pack",
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "query_review_board": "/api/query-review-board",
            "review_pack": "/api/review-pack",
        },
    }


def _count_sql_statements(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    return sum(1 for item in text.split(";") if item.strip())
