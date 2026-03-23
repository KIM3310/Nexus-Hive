"""
Governance scorecards, warehouse briefs, semantic governance pack, lakehouse readiness,
gold eval suite, quality gates, lineage, and metric layer schemas.
"""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from config import (
    ALLOW_HEURISTIC_FALLBACK,
    DB_PATH,
    GOLD_EVAL_CASES,
    GOVERNANCE_SCORECARD_FOCUS_VALUES,
    GOVERNANCE_SCORECARD_SCHEMA,
    LAKEHOUSE_READINESS_PACK_SCHEMA,
    LINEAGE_RELATIONSHIPS,
    METRIC_LAYER_DEFINITIONS,
    SEMANTIC_GOVERNANCE_PACK_SCHEMA,
    WAREHOUSE_TARGET_SCORECARD_SCHEMA,
    utc_now_iso,
)
from warehouse_adapter import get_active_warehouse_adapter, get_warehouse_adapter_contracts
from runtime_store import build_runtime_store_summary

from policy.engine import (
    build_policy_schema,
    build_query_tag_contract,
    evaluate_sql_case,
    evaluate_sql_policy,
    infer_sql_from_question,
)
from policy.audit import (
    build_query_audit_summary,
    build_query_approval_board,
    list_latest_query_audits,
    list_recent_query_audits,
)
from security import operator_auth_status


def run_scalar_query(sql: str) -> int:
    return get_active_warehouse_adapter().run_scalar_query(sql, DB_PATH)


def fetch_date_window() -> Dict[str, Optional[str]]:
    return get_active_warehouse_adapter().fetch_date_window(DB_PATH)


def build_table_profiles() -> List[Dict[str, Any]]:
    return get_active_warehouse_adapter().build_table_profiles(DB_PATH)


def execute_sql_preview(sql: str) -> Dict[str, Any]:
    return get_active_warehouse_adapter().execute_sql_preview(sql, DB_PATH)


def build_quality_gate() -> Dict[str, Any]:
    table_profiles = build_table_profiles()
    required_tables = {"sales", "products", "regions"}
    present_tables = {profile["table"] for profile in table_profiles}
    missing_tables = sorted(required_tables - present_tables)

    checks = [
        {
            "name": "required_tables_present",
            "description": "sales, products, and regions tables must all be loaded before governed querying.",
            "violations": len(missing_tables),
            "status": "pass" if not missing_tables else "fail",
            "details": {"missing_tables": missing_tables},
        },
        {
            "name": "sales_primary_fields_not_null",
            "description": "sales rows should keep transaction, date, product, region, and net revenue populated.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM sales
                WHERE transaction_id IS NULL
                    OR date IS NULL
                    OR product_id IS NULL
                    OR region_id IS NULL
                    OR net_revenue IS NULL
                """
            ),
        },
        {
            "name": "sales_product_fk_integrity",
            "description": "Every sales.product_id should resolve to a products dimension row.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.product_id
                WHERE p.product_id IS NULL
                """
            ),
        },
        {
            "name": "sales_region_fk_integrity",
            "description": "Every sales.region_id should resolve to a regions dimension row.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM sales s
                LEFT JOIN regions r ON s.region_id = r.region_id
                WHERE r.region_id IS NULL
                """
            ),
        },
        {
            "name": "transaction_id_uniqueness",
            "description": "Each sales transaction_id should stay unique for auditable grain.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT transaction_id
                    FROM sales
                    GROUP BY transaction_id
                    HAVING COUNT(*) > 1
                ) dupes
                """
            ),
        },
    ]

    for check in checks[1:]:
        check["status"] = "pass" if check["violations"] == 0 else "fail"

    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "schema": "nexus-hive-quality-gate-v1",
        "status": "ok" if not failed else "degraded",
        "headline": "Quality gate validates modeled tables before governed querying is trusted.",
        "checks": checks,
        "failed_checks": [check["name"] for check in failed],
    }


def build_lineage_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-lineage-v1",
        "semantic_model": [
            {
                "name": "fact_sales",
                "source_table": "sales",
                "grain": "transaction_id",
                "measures": ["gross_revenue", "net_revenue", "profit", "quantity"],
            },
            {
                "name": "dim_products",
                "source_table": "products",
                "grain": "product_id",
                "attributes": ["product_name", "category", "unit_price", "margin_percentage"],
            },
            {
                "name": "dim_regions",
                "source_table": "regions",
                "grain": "region_id",
                "attributes": ["region_name", "manager"],
            },
        ],
        "relationships": LINEAGE_RELATIONSHIPS,
        "operator_rules": [
            "Aggregate metrics should be traced back to fact_sales grain before approval.",
            "Dimension joins must stay auditable and consistent with the modeled foreign-key relationships.",
            "Reviewers should inspect lineage and quality gates before trusting NL2SQL output.",
        ],
    }


def build_metric_layer_schema() -> Dict[str, Any]:
    certified_metrics = [
        metric["metric_id"] for metric in METRIC_LAYER_DEFINITIONS if metric["certified"]
    ]
    return {
        "schema": "nexus-hive-metric-layer-v1",
        "headline": "Semantic metric contract for governed warehouse questions before SQL or dashboards are trusted.",
        "metrics": METRIC_LAYER_DEFINITIONS,
        "dimensions": [
            {
                "dimension_id": "region_name",
                "source": "regions.region_name",
                "join_path": "sales.region_id -> regions.region_id",
            },
            {
                "dimension_id": "category",
                "source": "products.category",
                "join_path": "sales.product_id -> products.product_id",
            },
            {
                "dimension_id": "month",
                "source": "SUBSTR(sales.date, 1, 7)",
                "join_path": "derived from sales.date",
            },
            {
                "dimension_id": "product_name",
                "source": "products.product_name",
                "join_path": "sales.product_id -> products.product_id",
            },
        ],
        "approval_policy": {
            "certified_metrics": certified_metrics,
            "review_required_when": [
                "request references a non-certified metric",
                "query mixes certified and non-certified metrics without an explicit purpose",
                "dimension grain is ambiguous relative to transaction_id",
            ],
            "warehouse_targets": [
                "sqlite-demo",
                "snowflake-sql-contract",
                "databricks-sql-contract",
            ],
        },
        "operator_rules": [
            "Certified metrics are the front door for executive analytics claims.",
            "Non-certified metrics stay visible but require explicit reviewer approval before external sharing.",
            "Metric definitions must map back to fact_sales grain and known lineage edges.",
        ],
    }


def build_gold_eval_pack() -> Dict[str, Any]:
    cases = []
    for case in GOLD_EVAL_CASES:
        fallback_sql = infer_sql_from_question(case["question"])
        verdict = evaluate_sql_case(fallback_sql, case["expected_features"])
        cases.append(
            {
                **case,
                "fallback_sql_preview": fallback_sql,
                "fallback_verdict": verdict,
            }
        )

    passing_cases = sum(1 for case in cases if case["fallback_verdict"]["status"] == "pass")
    return {
        "schema": "nexus-hive-gold-eval-v1",
        "headline": "Canonical NL2SQL review set used to judge governed analytics behavior before demo claims.",
        "summary": {
            "case_count": len(cases),
            "fallback_pass_count": passing_cases,
        },
        "cases": cases,
    }


def run_gold_eval_suite(strategy: str = "heuristic") -> Dict[str, Any]:
    items = []
    passed = 0

    for case in GOLD_EVAL_CASES:
        sql = infer_sql_from_question(case["question"])
        feature_verdict = evaluate_sql_case(sql, case["expected_features"])
        policy_verdict = evaluate_sql_policy(sql)
        execution = None
        execution_error = ""

        if policy_verdict["decision"] != "deny":
            try:
                execution = execute_sql_preview(sql)
            except Exception as exc:
                execution_error = str(exc)
        else:
            execution_error = "policy denied"

        status = "pass"
        if feature_verdict["status"] != "pass":
            status = "partial"
        if policy_verdict["decision"] == "deny" or execution_error:
            status = "fail"

        if status == "pass":
            passed += 1

        items.append(
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "strategy": strategy,
                "sql": sql,
                "feature_verdict": feature_verdict,
                "policy_verdict": policy_verdict,
                "execution": execution
                or {
                    "row_count": 0,
                    "preview": [],
                    "elapsed_ms": 0,
                },
                "error": execution_error,
                "status": status,
            }
        )

    return {
        "schema": "nexus-hive-gold-eval-run-v1",
        "headline": "Runnable gold eval suite that checks SQL features, policy verdicts, and executable previews.",
        "strategy": strategy,
        "summary": {
            "case_count": len(items),
            "pass_count": passed,
            "fail_count": len([item for item in items if item["status"] == "fail"]),
        },
        "items": items,
    }


def normalize_governance_focus(focus: Optional[str]) -> str:
    normalized = str(focus or "").strip().lower()
    if not normalized:
        return "quality"
    if normalized not in GOVERNANCE_SCORECARD_FOCUS_VALUES:
        raise HTTPException(status_code=400, detail="invalid governance focus")
    return normalized


def build_governance_scorecard(focus: str = "quality") -> Dict[str, Any]:
    normalized_focus = normalize_governance_focus(focus)
    active_adapter = get_active_warehouse_adapter()
    db_ready = DB_PATH.exists() and bool(get_active_warehouse_adapter().get_schema(DB_PATH).strip())
    quality_gate = build_quality_gate()
    gold_eval_run = run_gold_eval_suite()
    audit_summary = build_query_audit_summary(limit=10)
    persisted = build_runtime_store_summary(10)
    latest_items = list_latest_query_audits()
    fallback_any_count = len(list_latest_query_audits(fallback_mode="any"))
    denied_items = list_recent_query_audits(limit=3, policy_decision="deny")
    review_items = list_recent_query_audits(limit=3, policy_decision="review")
    failed_items = list_recent_query_audits(limit=3, status="failed")
    total_requests = int(audit_summary["summary"]["total_requests"])
    gold_case_count = int(gold_eval_run["summary"]["case_count"])
    gold_pass_count = int(gold_eval_run["summary"]["pass_count"])
    quality_failures = len(quality_gate["failed_checks"])
    review_required_count = int(audit_summary["summary"]["review_required_count"])
    denied_count = int(audit_summary["summary"]["denied_count"])
    error_count = int(audit_summary["summary"]["error_count"])
    fallback_rate_pct = (
        round((fallback_any_count / total_requests) * 100, 1) if total_requests else 0.0
    )
    guarded_rate_pct = (
        round(((review_required_count + denied_count) / total_requests) * 100, 1)
        if total_requests
        else 0.0
    )
    gold_eval_pass_rate_pct = (
        round((gold_pass_count / gold_case_count) * 100, 1) if gold_case_count else 0.0
    )
    error_rate_pct = round((error_count / total_requests) * 100, 1) if total_requests else 0.0

    score_bands = [
        {
            "id": "query-safety",
            "label": "Query safety",
            "score_pct": max(0.0, round(100.0 - error_rate_pct - quality_failures * 5, 1)),
            "signal": "strong" if denied_count + review_required_count > 0 else "watch",
            "evidence": "policy previews, deny rules, review-required counts",
        },
        {
            "id": "resilience",
            "label": "Resilience",
            "score_pct": max(0.0, round(100.0 - error_rate_pct, 1)),
            "signal": "strong" if error_count == 0 else "watch",
            "evidence": "fallback ratio and runtime error rate",
        },
        {
            "id": "quality",
            "label": "Quality",
            "score_pct": gold_eval_pass_rate_pct,
            "signal": "strong"
            if quality_gate["status"] == "ok" and gold_eval_pass_rate_pct >= 75
            else "watch",
            "evidence": "gold eval run + modeled table quality gate",
        },
        {
            "id": "throughput",
            "label": "Throughput",
            "score_pct": min(100.0, float(total_requests) * 10.0),
            "signal": "strong" if total_requests >= 3 else "watch",
            "evidence": "query audit volume and latest request activity",
        },
    ]

    if normalized_focus == "policy":
        spotlight = {
            "headline": "Policy posture surfaces the main approval reasons before governed analytics claims are made.",
            "top_policy_reasons": audit_summary["top_policy_reasons"],
            "recent_denied": denied_items,
            "recent_review_required": review_items,
        }
    elif normalized_focus == "resilience":
        spotlight = {
            "headline": "Resilience posture keeps fallback and runtime error pressure visible before demos.",
            "fallback_any_count": fallback_any_count,
            "error_rate_pct": error_rate_pct,
            "recent_failed": failed_items,
        }
    elif normalized_focus == "throughput":
        spotlight = {
            "headline": "Throughput posture shows current audit volume and the latest governed questions.",
            "total_requests": total_requests,
            "latest_requests": latest_items[:5],
        }
    else:
        spotlight = {
            "headline": "Quality posture ties gold eval readiness, modeled-table integrity, and audit hygiene together.",
            "gold_eval_failures": gold_case_count - gold_pass_count,
            "quality_gate_failures": quality_gate["failed_checks"],
            "recent_quality_reviews": review_items,
        }

    recommendations = [
        None
        if db_ready
        else "Seed the warehouse and verify schema load before judging governed analytics quality.",
        None
        if quality_gate["status"] == "ok"
        else "Resolve modeled-table quality gate failures before claiming governed SQL readiness.",
        None
        if gold_eval_pass_rate_pct >= 75
        else "Improve NL2SQL heuristics or prompt quality until the gold eval pass rate clears 75%.",
        None
        if denied_count + review_required_count > 0
        else "Exercise /api/policy/check with risky SQL so the policy boundary remains visible.",
        None
        if error_count == 0
        else "Inspect failed audit items before relying on live SSE walkthroughs during demos.",
    ]

    return {
        "status": "ok" if db_ready else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": GOVERNANCE_SCORECARD_SCHEMA,
        "focus": normalized_focus,
        "summary": {
            "db_ready": db_ready,
            "warehouse_mode": active_adapter.contract.name,
            "fallback_mode": "heuristic" if ALLOW_HEURISTIC_FALLBACK else "disabled",
            "quality_gate_status": quality_gate["status"],
            "quality_gate_failures": quality_failures,
            "total_requests": total_requests,
            "guarded_rate_pct": guarded_rate_pct,
            "fallback_rate_pct": fallback_rate_pct,
            "error_rate_pct": error_rate_pct,
            "gold_eval_pass_rate_pct": gold_eval_pass_rate_pct,
            "latest_updated_at": audit_summary["summary"]["latest_updated_at"],
            "persisted_event_count": persisted["persisted_count"],
        },
        "persistence": persisted,
        "operator_auth": {
            **operator_auth_status(),
            "protected_routes": ["/api/ask", "/api/policy/check"],
        },
        "score_bands": score_bands,
        "spotlight": spotlight,
        "recommendations": [item for item in recommendations if item],
        "links": {
            "health": "/health",
            "meta": "/api/meta",
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "auth_session": "/api/auth/session",
            "review_pack": "/api/review-pack",
            "policy_check": "/api/policy/check",
            "query_session_board": "/api/query-session-board",
            "query_approval_board": "/api/query-approval-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
            "governance_scorecard": "/api/runtime/governance-scorecard",
        },
    }


def build_warehouse_brief() -> Dict[str, Any]:
    active_adapter = get_active_warehouse_adapter()
    table_profiles = build_table_profiles()
    quality_gate = build_quality_gate()
    date_window = fetch_date_window()
    recent_audits = list_recent_query_audits(limit=5)
    gold_eval = build_gold_eval_pack()
    gold_eval_run = run_gold_eval_suite()
    policy_schema = build_policy_schema()
    query_tag_contract = build_query_tag_contract()

    return {
        "status": "ok" if quality_gate["status"] == "ok" else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "readiness_contract": "nexus-hive-warehouse-brief-v1",
        "headline": "Governed analytics brief tying warehouse mode, lineage, quality gate, and audit trail into one reviewable surface.",
        "warehouse_mode": active_adapter.contract.name,
        "selected_adapter": active_adapter.describe(),
        "fallback_mode": "heuristic" if ALLOW_HEURISTIC_FALLBACK else "disabled",
        "adapter_contracts": get_warehouse_adapter_contracts(),
        "table_profiles": table_profiles,
        "date_window": date_window,
        "quality_gate": quality_gate,
        "lineage": build_lineage_schema(),
        "metric_layer": build_metric_layer_schema(),
        "policy": policy_schema,
        "query_tag_contract": query_tag_contract,
        "gold_eval": gold_eval,
        "gold_eval_run": gold_eval_run,
        "recent_audit_count": len(recent_audits),
        "audit_summary": build_query_audit_summary(limit=5),
        "policy_examples": [
            "read_only_sql_only",
            "aggregates_before_operator_approval",
            "trace_sql_before_chart_trust",
            "sensitive_columns_require_role_escalation",
        ],
        "query_tag_examples": query_tag_contract["examples"],
        "routes": [
            "/api/runtime/warehouse-brief",
            "/api/runtime/warehouse-target-scorecard",
            "/api/schema/lineage",
            "/api/schema/metrics",
            "/api/schema/policy",
            "/api/schema/query-tag",
            "/api/schema/query-audit",
            "/api/evals/nl2sql-gold",
            "/api/query-session-board",
            "/api/query-approval-board",
            "/api/query-review-board",
            "/api/query-audit/summary",
            "/api/query-audit/recent",
        ],
    }


def build_warehouse_target_scorecard(target: Optional[str] = None) -> Dict[str, Any]:
    contracts = get_warehouse_adapter_contracts()
    allowed_targets = [
        str(item.get("name", "")).strip().lower()
        for item in contracts
        if str(item.get("name", "")).strip()
    ]
    normalized_target = str(target or "").strip().lower()
    if normalized_target and normalized_target not in allowed_targets:
        raise ValueError(f"invalid warehouse target: {target}")

    metric_layer = build_metric_layer_schema()
    quality_gate = build_quality_gate()
    governance_scorecard = build_governance_scorecard("policy")
    gold_eval_run = run_gold_eval_suite()
    certified_metrics = [
        str(item) for item in metric_layer.get("approval_policy", {}).get("certified_metrics", [])
    ]
    review_required_when = [
        str(item)
        for item in metric_layer.get("approval_policy", {}).get("review_required_when", [])
    ]

    visible_contracts = [
        item
        for item in contracts
        if not normalized_target or str(item.get("name", "")).strip().lower() == normalized_target
    ]
    target_notes = {
        "sqlite-demo": {
            "fit": "Deterministic governed BI review path with live local execution.",
            "primary_surface": "/api/ask",
        },
        "snowflake-sql-contract": {
            "fit": "Snowflake-style governed warehouse contract with query tagging and audit posture kept explicit.",
            "primary_surface": "/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract",
        },
        "databricks-sql-contract": {
            "fit": "Databricks-style lakehouse contract with freshness and quality-gate semantics visible up front.",
            "primary_surface": "/api/runtime/warehouse-target-scorecard?target=databricks-sql-contract",
        },
    }

    cards = []
    for item in visible_contracts:
        target_name = str(item.get("name", ""))
        note = target_notes.get(target_name, {})
        execution_mode = str(item.get("execution_mode", ""))
        blockers: List[str] = []
        if execution_mode == "contract-preview":
            blockers.append("live_connector_not_configured")
        if quality_gate.get("status") != "ok":
            blockers.append("quality_gate_degraded")
        cards.append(
            {
                "target": target_name,
                "status": (
                    "ready"
                    if execution_mode == "local-sqlite" and quality_gate.get("status") == "ok"
                    else "review-ready"
                    if quality_gate.get("status") == "ok"
                    else "attention"
                ),
                "sql_dialect": str(item.get("sql_dialect", "")),
                "execution_mode": execution_mode,
                "fit": note.get("fit", str(item.get("role", ""))),
                "primary_surface": note.get("primary_surface", "/api/runtime/warehouse-brief"),
                "capabilities": [str(capability) for capability in item.get("capabilities", [])],
                "blockers": blockers,
                "review_note": str(item.get("review_note", "")),
            }
        )

    return {
        "status": "ok" if quality_gate["status"] == "ok" else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": WAREHOUSE_TARGET_SCORECARD_SCHEMA,
        "headline": "Warehouse target scorecard that makes SQLite, Snowflake, and Databricks fit explicit before platform-native claims are made.",
        "filters": {
            "target": normalized_target or None,
        },
        "summary": {
            "visible_targets": len(cards),
            "certified_metric_count": len(certified_metrics),
            "review_required_rule_count": len(review_required_when),
            "quality_gate_status": quality_gate["status"],
            "gold_eval_pass_count": gold_eval_run["summary"]["pass_count"],
            "runtime_event_count": governance_scorecard["persistence"]["persisted_count"],
        },
        "targets": cards,
        "review_actions": [
            "Read this scorecard before claiming Snowflake or Databricks fit from the generic warehouse brief alone.",
            "Use /api/schema/metrics to verify which certified metrics survive across warehouse targets.",
            "Pair this view with query approval and policy surfaces before promising platform-native governance behavior.",
        ],
        "links": {
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "semantic_governance_pack": "/api/runtime/semantic-governance-pack",
            "metric_layer_schema": "/api/schema/metrics",
            "policy_schema": "/api/schema/policy",
            "query_approval_board": "/api/query-approval-board",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
        },
    }


def build_semantic_governance_pack() -> Dict[str, Any]:
    metric_layer = build_metric_layer_schema()
    policy_schema = build_policy_schema()
    governance_scorecard = build_governance_scorecard("policy")
    warehouse_target_scorecard = build_warehouse_target_scorecard()
    query_approval_board = build_query_approval_board(limit=5)

    certified_metrics = [
        metric for metric in metric_layer["metrics"] if bool(metric.get("certified"))
    ]
    attention_metrics = [
        metric for metric in metric_layer["metrics"] if not bool(metric.get("certified"))
    ]

    return {
        "status": "ok" if governance_scorecard["status"] == "ok" else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": SEMANTIC_GOVERNANCE_PACK_SCHEMA,
        "headline": "Semantic governance pack covering metric certification, approval posture, and warehouse-target status.",
        "summary": {
            "certified_metric_count": len(certified_metrics),
            "review_required_metric_count": len(attention_metrics),
            "approval_queue_count": query_approval_board["summary"]["pending_count"],
            "review_required_rule_count": len(
                metric_layer["approval_policy"]["review_required_when"]
            ),
            "target_count": warehouse_target_scorecard["summary"]["visible_targets"],
            "guarded_rate_pct": governance_scorecard["summary"]["guarded_rate_pct"],
        },
        "certification_board": [
            {
                "metric_id": str(metric.get("metric_id", "")),
                "label": str(metric.get("label", "")),
                "owner": str(metric.get("owner", "")),
                "grain": str(metric.get("grain", "")),
                "status": "certified" if bool(metric.get("certified")) else "review-required",
                "default_dimensions": [str(item) for item in metric.get("default_dimensions", [])],
                "warehouse_targets": metric_layer["approval_policy"]["warehouse_targets"],
            }
            for metric in metric_layer["metrics"]
        ],
        "target_posture": [
            {
                "target": str(item.get("target", "")),
                "status": str(item.get("status", "")),
                "execution_mode": str(item.get("execution_mode", "")),
                "fit": str(item.get("fit", "")),
                "blockers": [str(blocker) for blocker in item.get("blockers", [])],
            }
            for item in warehouse_target_scorecard["targets"]
        ],
        "approval_boundary": {
            "review_required_when": metric_layer["approval_policy"]["review_required_when"],
            "deny_rules": policy_schema["deny_rules"],
            "query_approval_pending_count": query_approval_board["summary"]["pending_count"],
            "latest_pending_updated_at": query_approval_board["summary"]["latest_updated_at"],
        },
        "review_path": [
            "Open /api/runtime/semantic-governance-pack first when the question is metric trust, not just SQL generation.",
            "Use /api/schema/metrics to inspect the exact certification boundary behind each measure.",
            "Pair this pack with /api/runtime/warehouse-target-scorecard and /api/query-approval-board before claiming Snowflake or Databricks fit.",
        ],
        "reviewer_notes": [
            "Certified metrics are the front door for external analytics claims.",
            "Warehouse target fit stays a contract preview unless the live connector posture changes.",
            "Review-required metrics remain visible so governance is explicit instead of silently hidden.",
        ],
        "links": {
            "semantic_governance_pack": "/api/runtime/semantic-governance-pack",
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "metric_layer_schema": "/api/schema/metrics",
            "policy_schema": "/api/schema/policy",
            "query_approval_board": "/api/query-approval-board",
            "query_review_board": "/api/query-review-board",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
            "review_pack": "/api/review-pack",
        },
    }


def build_lakehouse_readiness_pack(target: Optional[str] = None) -> Dict[str, Any]:
    normalized_target = (target or "").strip().lower()
    query_tag_contract = build_query_tag_contract()
    governance_scorecard = build_governance_scorecard("policy")
    build_semantic_governance_pack()
    warehouse_target_scorecard = build_warehouse_target_scorecard()
    query_approval_board = build_query_approval_board(limit=5)

    allowed_targets = {
        "snowflake-sql-contract",
        "databricks-sql-contract",
    }
    if normalized_target and normalized_target not in allowed_targets:
        raise ValueError("target must be snowflake-sql-contract or databricks-sql-contract")

    target_rows = [
        item
        for item in warehouse_target_scorecard["targets"]
        if str(item.get("target", "")) in allowed_targets
        and (
            not normalized_target
            or str(item.get("target", "")).strip().lower() == normalized_target
        )
    ]
    adapter_notes = {
        str(item.get("adapter", "")): str(item.get("tag_transport", ""))
        for item in query_tag_contract["adapter_notes"]
    }

    return {
        "status": "ok" if governance_scorecard["status"] == "ok" else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": LAKEHOUSE_READINESS_PACK_SCHEMA,
        "headline": "Lakehouse readiness pack that turns Snowflake and Databricks fit into explicit connector, governance, and delivery proof.",
        "filters": {
            "target": normalized_target or None,
        },
        "summary": {
            "visible_targets": len(target_rows),
            "contract_preview_count": sum(
                1
                for item in target_rows
                if str(item.get("execution_mode", "")) == "contract-preview"
            ),
            "approval_queue_count": query_approval_board["summary"]["pending_count"],
            "guarded_rate_pct": governance_scorecard["summary"]["guarded_rate_pct"],
            "query_tag_example_count": len(query_tag_contract["examples"]),
        },
        "platform_cards": [
            {
                "target": str(item.get("target", "")),
                "status": str(item.get("status", "")),
                "execution_mode": str(item.get("execution_mode", "")),
                "sql_dialect": str(item.get("sql_dialect", "")),
                "fit": str(item.get("fit", "")),
                "tag_transport": adapter_notes.get(str(item.get("target", "")), ""),
                "blockers": [str(blocker) for blocker in item.get("blockers", [])],
                "review_surfaces": [
                    "/api/runtime/lakehouse-readiness-pack",
                    "/api/runtime/warehouse-target-scorecard",
                    "/api/runtime/semantic-governance-pack",
                    "/api/schema/query-tag",
                    "/api/query-approval-board",
                ],
            }
            for item in target_rows
        ],
        "delivery_path": [
            "Start with certified metrics and approval rules so adapter claims stay governed before connector work begins.",
            "Preview warehouse tagging and request metadata through /api/schema/query-tag before any platform-native story is repeated.",
            "Treat Snowflake and Databricks as explicit contract-preview targets until live connector posture changes.",
            "Keep the approval board in the loop so warehouse-native demos still show human review boundaries.",
        ],
        "reviewer_notes": [
            "Snowflake and Databricks fit is expressed as an explicit contract preview with governance artifacts, not as fake live connectivity.",
            "The strongest public claim is governed warehouse-readiness, not production connector throughput.",
            "Lakehouse posture stays credible only when target scorecard, semantic pack, and query-tag contract all agree.",
        ],
        "links": {
            "lakehouse_readiness_pack": "/api/runtime/lakehouse-readiness-pack",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "semantic_governance_pack": "/api/runtime/semantic-governance-pack",
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "query_tag_schema": "/api/schema/query-tag",
            "query_approval_board": "/api/query-approval-board",
            "query_review_board": "/api/query-review-board",
            "review_pack": "/api/review-pack",
        },
    }
