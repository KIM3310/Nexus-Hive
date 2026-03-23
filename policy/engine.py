"""
Core policy engine: SQL evaluation, query tagging, SQL inference, and chart config inference.

Provides the governance layer that evaluates SQL queries against security
policies, builds query tags for audit trails, and offers heuristic fallback
paths for SQL generation and chart configuration.
"""

import logging
from typing import Any, Dict, List, Set

from config import (
    DEFAULT_ROLE,
    QUERY_TAG_SCHEMA,
    READ_ONLY_BLOCKLIST,
    SENSITIVE_COLUMNS_BY_ROLE,
    normalize_question,
)

_logger = logging.getLogger("nexus_hive.policy.engine")


def build_policy_schema() -> Dict[str, Any]:
    """Build the policy schema descriptor for API responses.

    Returns:
        Dictionary describing policy rules, deny rules, review rules,
        and sensitive column mappings.
    """
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
    """Build the query tag contract describing governance metadata dimensions.

    Returns:
        Dictionary with schema, required dimensions, examples, and adapter notes.
    """
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


def build_query_tag(
    *,
    request_id: str,
    role: str,
    purpose: str,
    adapter_name: str = "sqlite-demo",
) -> str:
    """Build a governance query tag string for audit trail attachment.

    Args:
        request_id: Unique request identifier.
        role: Operator role (e.g., 'analyst', 'viewer').
        purpose: Query purpose (e.g., 'ask', 'policy-check').
        adapter_name: Warehouse adapter name.

    Returns:
        A semicolon-delimited query tag string.
    """
    safe_role: str = str(role or DEFAULT_ROLE).strip().lower() or DEFAULT_ROLE
    safe_purpose: str = str(purpose or "ask").strip().lower() or "ask"
    safe_request_id: str = str(request_id or "unknown").strip() or "unknown"
    safe_adapter: str = str(adapter_name or "sqlite-demo").strip() or "sqlite-demo"
    return (
        f"service=nexus-hive;adapter={safe_adapter};role={safe_role};"
        f"request_id={safe_request_id};purpose={safe_purpose}"
    )


def evaluate_sql_policy(
    sql: str,
    role: str = DEFAULT_ROLE,
) -> Dict[str, Any]:
    """Evaluate a SQL query against the governance policy rules.

    Checks for write operations, wildcard projections, sensitive column access,
    and non-aggregated queries without LIMIT clauses.

    Args:
        sql: The SQL query to evaluate.
        role: The operator role for sensitive column checks.

    Returns:
        Dictionary with role, decision ('allow', 'review', or 'deny'),
        deny_reasons, and review_reasons lists.
    """
    normalized_sql: str = str(sql or "").strip()
    upper_sql: str = normalized_sql.upper()
    lower_sql: str = normalized_sql.lower()
    deny_reasons: List[str] = []
    review_reasons: List[str] = []
    sensitive_columns: Set[str] = SENSITIVE_COLUMNS_BY_ROLE.get(role, set())

    if any(keyword in upper_sql for keyword in READ_ONLY_BLOCKLIST):
        deny_reasons.append("write_operations_blocked")
    if "SELECT *" in upper_sql:
        deny_reasons.append("wildcard_projection_denied")
    if any(column in lower_sql for column in sensitive_columns):
        deny_reasons.append("sensitive_columns_require_privileged_role")
    if "GROUP BY" not in upper_sql and "LIMIT" not in upper_sql:
        review_reasons.append("non_aggregated_queries_without_limit_require_operator_review")

    decision: str = "deny" if deny_reasons else "review" if review_reasons else "allow"

    _logger.info(
        "Policy evaluation: decision=%s, sql_preview=%s",
        decision,
        normalized_sql[:80],
    )

    return {
        "role": role,
        "decision": decision,
        "deny_reasons": deny_reasons,
        "review_reasons": review_reasons,
    }


def build_policy_approval_bundle(verdict: Dict[str, Any]) -> Dict[str, Any]:
    """Build an approval action bundle from a policy verdict.

    Args:
        verdict: The policy verdict dictionary from evaluate_sql_policy.

    Returns:
        Dictionary with approval_required flag, approval_actions list,
        and review_rationale.
    """
    review_reasons: List[str] = list(verdict.get("review_reasons") or [])
    approval_required: bool = str(verdict.get("decision") or "").strip().lower() == "review"
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


def evaluate_sql_case(
    sql: str,
    expected_features: List[str],
) -> Dict[str, Any]:
    """Evaluate a generated SQL query against expected feature patterns.

    Used by the gold eval suite to score heuristic SQL quality.

    Args:
        sql: The generated SQL query.
        expected_features: List of SQL feature strings to match against.

    Returns:
        Dictionary with matched_features, missing_features, score, max_score,
        and status ('pass' or 'partial').
    """
    upper_sql: str = str(sql or "").upper()
    matched: List[str] = [feature for feature in expected_features if feature.upper() in upper_sql]
    return {
        "matched_features": matched,
        "missing_features": [feature for feature in expected_features if feature not in matched],
        "score": len(matched),
        "max_score": len(expected_features),
        "status": "pass" if len(matched) == len(expected_features) else "partial",
    }


def normalize_question_text(question: str) -> str:
    """Normalize question text for comparison using the shared normalizer.

    Args:
        question: Raw question string.

    Returns:
        Normalized, lowercase, single-spaced string.
    """
    return normalize_question(question)


def infer_sql_from_question(question: str) -> str:
    """Infer a SQL query from a natural language question using heuristic rules.

    Matches question patterns against known analytics scenarios and returns
    pre-built SQL. Falls back to a default revenue-by-region query.

    Args:
        question: The natural language question.

    Returns:
        A SQL query string.
    """
    normalized: str = normalize_question(question)
    _logger.debug("Heuristic SQL inference for: %s", normalized[:80])

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
        limit: int = 5 if "top 5" in normalized else 10
        return (
            "SELECT r.region_name, ROUND(SUM(s.profit), 2) AS total_profit "
            "FROM sales s "
            "JOIN regions r ON s.region_id = r.region_id "
            "GROUP BY r.region_name "
            "ORDER BY total_profit DESC "
            f"LIMIT {limit}"
        )

    if (
        "monthly" in normalized or "trend" in normalized or "month" in normalized
    ) and "revenue" in normalized:
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


def infer_chart_config_from_question(
    question: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Infer a Chart.js configuration from the question and result rows.

    Uses keyword matching to select chart type (bar, line, doughnut)
    and picks label/data keys from the first row's column names.

    Args:
        question: The original user question.
        rows: List of result row dictionaries.

    Returns:
        Chart.js configuration dictionary with type, labels_key, data_key, title.
    """
    if not rows:
        return {
            "type": "bar",
            "labels_key": "label",
            "data_key": "value",
            "title": "Data Visualization",
        }

    keys: List[str] = list(rows[0].keys())
    label_key: str = keys[0]
    data_key: str = keys[1] if len(keys) > 1 else keys[0]
    normalized: str = normalize_question(question)
    chart_type: str = "bar"

    if "trend" in normalized or "month" in normalized or "date" in normalized:
        chart_type = "line"
    elif len(rows) <= 6 and any(
        keyword in normalized for keyword in ["share", "mix", "category", "region"]
    ):
        chart_type = "doughnut"

    return {
        "type": chart_type,
        "labels_key": label_key,
        "data_key": data_key,
        "title": "Governed Analytics View",
    }
