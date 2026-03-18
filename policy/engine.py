"""
Core policy engine: SQL evaluation, query tagging, SQL inference, and chart config inference.
"""

from typing import Any, Dict, List

from config import (
    DB_PATH,
    DEFAULT_ROLE,
    LINEAGE_RELATIONSHIPS,
    METRIC_LAYER_DEFINITIONS,
    QUERY_TAG_SCHEMA,
    READ_ONLY_BLOCKLIST,
    SENSITIVE_COLUMNS_BY_ROLE,
    normalize_question,
)
from warehouse_adapter import get_active_warehouse_adapter


def build_policy_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-policy-v1",
        "default_role": DEFAULT_ROLE,
        "deny_rules": [
            "write_operations_blocked",
            "wildcard_projection_denied",
            "sensitive_columns_require_privileged_role",
        ],
        "review_rules": [
            "non_aggregated_queries_without_limit_require_operator_review",
        ],
        "sensitive_columns_by_role": SENSITIVE_COLUMNS_BY_ROLE,
    }


def build_query_tag_contract() -> Dict[str, Any]:
    return {
        "schema": QUERY_TAG_SCHEMA,
        "default_adapter": "sqlite-demo",
        "required_dimensions": [
            "service",
            "adapter",
            "role",
            "request_id",
            "purpose",
        ],
        "examples": [
            "service=nexus-hive;adapter=sqlite-demo;role=analyst;request_id=req-123;purpose=ask",
            "service=nexus-hive;adapter=snowflake-sql-contract;role=analyst;request_id=req-123;purpose=policy-check",
            "service=nexus-hive;adapter=databricks-sql-contract;role=viewer;request_id=req-123;purpose=gold-eval",
        ],
        "adapter_notes": [
            {
                "adapter": "sqlite-demo",
                "tag_transport": "local audit preview only",
            },
            {
                "adapter": "snowflake-sql-contract",
                "tag_transport": "maps cleanly onto statement params / QUERY_TAG-style governance metadata",
            },
            {
                "adapter": "databricks-sql-contract",
                "tag_transport": "maps onto warehouse tags and medallion/lakehouse governance review",
            },
        ],
    }


def build_query_tag(*, request_id: str, role: str, purpose: str, adapter_name: str = "sqlite-demo") -> str:
    safe_role = str(role or DEFAULT_ROLE).strip().lower() or DEFAULT_ROLE
    safe_purpose = str(purpose or "ask").strip().lower() or "ask"
    safe_request_id = str(request_id or "unknown").strip() or "unknown"
    safe_adapter = str(adapter_name or "sqlite-demo").strip() or "sqlite-demo"
    return (
        f"service=nexus-hive;adapter={safe_adapter};role={safe_role};"
        f"request_id={safe_request_id};purpose={safe_purpose}"
    )


def evaluate_sql_policy(sql: str, role: str = DEFAULT_ROLE) -> Dict[str, Any]:
    normalized_sql = str(sql or "").strip()
    upper_sql = normalized_sql.upper()
    lower_sql = normalized_sql.lower()
    deny_reasons: List[str] = []
    review_reasons: List[str] = []
    sensitive_columns = SENSITIVE_COLUMNS_BY_ROLE.get(role, set())

    if any(keyword in upper_sql for keyword in READ_ONLY_BLOCKLIST):
        deny_reasons.append("write_operations_blocked")
    if "SELECT *" in upper_sql:
        deny_reasons.append("wildcard_projection_denied")
    if any(column in lower_sql for column in sensitive_columns):
        deny_reasons.append("sensitive_columns_require_privileged_role")
    if "GROUP BY" not in upper_sql and "LIMIT" not in upper_sql:
        review_reasons.append("non_aggregated_queries_without_limit_require_operator_review")

    decision = "deny" if deny_reasons else "review" if review_reasons else "allow"
    return {
        "role": role,
        "decision": decision,
        "deny_reasons": deny_reasons,
        "review_reasons": review_reasons,
    }


def build_policy_approval_bundle(verdict: Dict[str, Any]) -> Dict[str, Any]:
    review_reasons = list(verdict.get("review_reasons") or [])
    approval_required = str(verdict.get("decision") or "").strip().lower() == "review"
    return {
        "approval_required": approval_required,
        "approval_actions": [
            "Confirm the SQL scope is intentional before executing a reviewer-sensitive query.",
            "Use /api/query-approval-board to see whether similar review-required queries are already waiting.",
            "Run /api/evals/nl2sql-gold/run if fallback or broad row access makes the request harder to trust.",
        ]
        if approval_required
        else [],
        "review_rationale": review_reasons,
    }


def evaluate_sql_case(sql: str, expected_features: List[str]) -> Dict[str, Any]:
    upper_sql = str(sql or "").upper()
    matched = [feature for feature in expected_features if feature.upper() in upper_sql]
    return {
        "matched_features": matched,
        "missing_features": [feature for feature in expected_features if feature not in matched],
        "score": len(matched),
        "max_score": len(expected_features),
        "status": "pass" if len(matched) == len(expected_features) else "partial",
    }


def normalize_question_text(question: str) -> str:
    return normalize_question(question)


def infer_sql_from_question(question: str) -> str:
    normalized = normalize_question(question)

    if "discount" in normalized and "category" in normalized:
        return (
            "SELECT p.category, ROUND(AVG(s.discount_applied), 4) AS average_discount "
            "FROM sales s "
            "JOIN products p ON s.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY average_discount DESC "
            "LIMIT 10"
        )

    if "profit" in normalized and "region" in normalized:
        limit = 5 if "top 5" in normalized else 10
        return (
            "SELECT r.region_name, ROUND(SUM(s.profit), 2) AS total_profit "
            "FROM sales s "
            "JOIN regions r ON s.region_id = r.region_id "
            "GROUP BY r.region_name "
            "ORDER BY total_profit DESC "
            f"LIMIT {limit}"
        )

    if ("monthly" in normalized or "trend" in normalized or "month" in normalized) and "revenue" in normalized:
        return (
            "SELECT SUBSTR(s.date, 1, 7) AS month, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue "
            "FROM sales s "
            "GROUP BY month "
            "ORDER BY month ASC "
            "LIMIT 12"
        )

    if "quantity" in normalized and "category" in normalized:
        return (
            "SELECT p.category, SUM(s.quantity) AS total_quantity "
            "FROM sales s "
            "JOIN products p ON s.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY total_quantity DESC "
            "LIMIT 10"
        )

    if "category" in normalized and "revenue" in normalized:
        return (
            "SELECT p.category, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue "
            "FROM sales s "
            "JOIN products p ON s.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY total_net_revenue DESC "
            "LIMIT 10"
        )

    return (
        "SELECT r.region_name, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue "
        "FROM sales s "
        "JOIN regions r ON s.region_id = r.region_id "
        "GROUP BY r.region_name "
        "ORDER BY total_net_revenue DESC "
        "LIMIT 10"
    )


def infer_chart_config_from_question(question: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "type": "bar",
            "labels_key": "label",
            "data_key": "value",
            "title": "Data Visualization",
        }

    keys = list(rows[0].keys())
    label_key = keys[0]
    data_key = keys[1] if len(keys) > 1 else keys[0]
    normalized = normalize_question(question)
    chart_type = "bar"

    if "trend" in normalized or "month" in normalized or "date" in normalized:
        chart_type = "line"
    elif len(rows) <= 6 and any(keyword in normalized for keyword in ["share", "mix", "category", "region"]):
        chart_type = "doughnut"

    return {
        "type": chart_type,
        "labels_key": label_key,
        "data_key": data_key,
        "title": "Governed Analytics View",
    }
