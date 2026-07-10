"""
Dedicated tests for the policy engine: deny, review, and allow decision paths.

Covers dangerous SQL denial (DROP, DELETE, INSERT, UPDATE, ALTER, TRUNCATE),
safe SELECT allowance, borderline review cases, sensitive column gating,
query tag generation, and approval bundle construction.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from policy.engine import (
    build_policy_approval_bundle,
    build_policy_schema,
    build_query_tag,
    evaluate_sql_policy,
)
from warehouse_adapter import validate_sql_safety
from exceptions import SQLValidationError


# ---------------------------------------------------------------------------
# Deny path: dangerous SQL
# ---------------------------------------------------------------------------


class TestPolicyDenyDangerousSQL:
    """Policy engine should deny all write and DDL operations."""

    def test_deny_drop_table(self) -> None:
        """DROP TABLE must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("DROP TABLE sales")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_drop_database(self) -> None:
        """DROP DATABASE must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("DROP DATABASE analytics")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_delete_from(self) -> None:
        """DELETE FROM must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("DELETE FROM sales WHERE region_id = 1")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_insert_into(self) -> None:
        """INSERT INTO must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "INSERT INTO sales (transaction_id) VALUES ('tx-evil')"
        )
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_update(self) -> None:
        """UPDATE must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("UPDATE sales SET net_revenue = 0 WHERE 1=1")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_alter_table(self) -> None:
        """ALTER TABLE must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("ALTER TABLE sales ADD COLUMN hack TEXT")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_truncate(self) -> None:
        """TRUNCATE must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("TRUNCATE TABLE sales")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_create_table(self) -> None:
        """CREATE TABLE must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("CREATE TABLE evil (id INT)")
        assert verdict["decision"] == "deny"
        assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_select_star(self) -> None:
        """SELECT * (wildcard projection) must be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("SELECT * FROM sales")
        assert verdict["decision"] == "deny"
        assert "wildcard_projection_denied" in verdict["deny_reasons"]

    def test_deny_select_star_with_where(self) -> None:
        """SELECT * with WHERE clause should still be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("SELECT * FROM sales WHERE region_id = 1")
        assert verdict["decision"] == "deny"
        assert "wildcard_projection_denied" in verdict["deny_reasons"]


# ---------------------------------------------------------------------------
# Allow path: safe SELECT queries
# ---------------------------------------------------------------------------


class TestPolicyAllowSafeQueries:
    """Policy engine should allow safe, aggregated SELECT queries."""

    def test_allow_aggregated_with_group_by(self) -> None:
        """Aggregated query with GROUP BY should be allowed."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name, SUM(net_revenue) FROM sales "
            "JOIN regions ON sales.region_id = regions.region_id "
            "GROUP BY region_name"
        )
        assert verdict["decision"] == "allow"
        assert verdict["deny_reasons"] == []
        assert verdict["review_reasons"] == []

    def test_allow_aggregated_with_limit(self) -> None:
        """Aggregated query with LIMIT should be allowed."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name, SUM(net_revenue) AS total FROM sales GROUP BY region_name LIMIT 10"
        )
        assert verdict["decision"] == "allow"

    def test_allow_count_query(self) -> None:
        """Simple COUNT query with GROUP BY should be allowed."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT category, COUNT(transaction_id) AS cnt "
            "FROM sales JOIN products ON sales.product_id = products.product_id "
            "GROUP BY category"
        )
        assert verdict["decision"] == "allow"

    def test_allow_query_with_limit_no_group_by(self) -> None:
        """Non-aggregated query with LIMIT should be allowed (LIMIT satisfies review check)."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT transaction_id, date FROM sales LIMIT 10"
        )
        assert verdict["decision"] == "allow"
        assert verdict["review_reasons"] == []

    def test_allow_query_with_order_by_and_limit(self) -> None:
        """Query with ORDER BY and LIMIT should be allowed."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name, SUM(profit) AS total_profit "
            "FROM sales JOIN regions ON sales.region_id = regions.region_id "
            "GROUP BY region_name ORDER BY total_profit DESC LIMIT 5"
        )
        assert verdict["decision"] == "allow"

    def test_default_role_is_analyst(self) -> None:
        """Default role in verdict should be analyst."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name FROM regions GROUP BY region_name"
        )
        assert verdict["role"] == "analyst"


# ---------------------------------------------------------------------------
# Review path: borderline cases
# ---------------------------------------------------------------------------


class TestPolicyReviewBorderline:
    """Policy engine should flag borderline queries for operator review."""

    def test_review_non_aggregated_without_limit(self) -> None:
        """Non-aggregated query without LIMIT or GROUP BY should require review."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT transaction_id, date, net_revenue FROM sales"
        )
        assert verdict["decision"] == "review"
        assert (
            "non_aggregated_queries_without_limit_require_operator_review"
            in verdict["review_reasons"]
        )

    def test_review_simple_column_select(self) -> None:
        """Simple column SELECT without constraints should require review."""
        verdict: Dict[str, Any] = evaluate_sql_policy("SELECT region_name FROM regions")
        assert verdict["decision"] == "review"
        assert len(verdict["review_reasons"]) > 0


# ---------------------------------------------------------------------------
# Sensitive column gating
# ---------------------------------------------------------------------------


class TestPolicySensitiveColumns:
    """Policy engine should deny access to sensitive columns based on role."""

    def test_deny_margin_percentage_for_analyst(self) -> None:
        """Analyst should be denied access to margin_percentage."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT product_name, margin_percentage FROM products GROUP BY product_name, margin_percentage",
            role="analyst",
        )
        assert verdict["decision"] == "deny"
        assert "sensitive_columns_require_privileged_role" in verdict["deny_reasons"]

    def test_deny_manager_column_for_viewer(self) -> None:
        """Viewer should be denied access to manager column."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name, manager FROM regions GROUP BY region_name, manager",
            role="viewer",
        )
        assert verdict["decision"] == "deny"
        assert "sensitive_columns_require_privileged_role" in verdict["deny_reasons"]

    def test_allow_margin_percentage_for_admin(self) -> None:
        """Admin role (not in sensitive_columns_by_role) should access margin_percentage."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT product_name, margin_percentage FROM products GROUP BY product_name, margin_percentage",
            role="admin",
        )
        # admin has no sensitive column restrictions
        assert "sensitive_columns_require_privileged_role" not in verdict["deny_reasons"]


# ---------------------------------------------------------------------------
# SQL validation (warehouse_adapter level)
# ---------------------------------------------------------------------------


class TestSQLValidationDangerous:
    """SQL validation should block dangerous statements at the adapter level."""

    def test_validate_blocks_drop(self) -> None:
        """DROP should be blocked by validate_sql_safety."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("DROP TABLE sales")

    def test_validate_blocks_delete(self) -> None:
        """DELETE should be blocked by validate_sql_safety."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("DELETE FROM sales")

    def test_validate_blocks_insert(self) -> None:
        """INSERT should be blocked by validate_sql_safety."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("INSERT INTO sales VALUES (1, 2, 3)")

    def test_validate_blocks_update(self) -> None:
        """UPDATE should be blocked by validate_sql_safety."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("UPDATE sales SET net_revenue = 0")

    def test_validate_blocks_alter(self) -> None:
        """ALTER should be blocked by validate_sql_safety."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("ALTER TABLE sales DROP COLUMN net_revenue")

    def test_validate_blocks_truncate(self) -> None:
        """TRUNCATE should be blocked by validate_sql_safety."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("TRUNCATE TABLE sales")

    def test_validate_allows_select(self) -> None:
        """Valid SELECT should pass validation."""
        validate_sql_safety(
            "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name LIMIT 10"
        )

    def test_validate_allows_with_cte(self) -> None:
        """WITH (CTE) should pass validation."""
        validate_sql_safety("WITH cte AS (SELECT 1 AS x) SELECT x FROM cte")

    def test_validate_blocks_multi_statement_injection(self) -> None:
        """Multi-statement injection (SELECT; DROP) should be blocked."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("SELECT 1; DROP TABLE sales")


# ---------------------------------------------------------------------------
# Approval bundle construction
# ---------------------------------------------------------------------------


class TestPolicyApprovalBundle:
    """Tests for approval bundle generation from policy verdicts."""

    def test_review_verdict_requires_approval(self) -> None:
        """Review verdict should produce an approval bundle with actions."""
        verdict: Dict[str, Any] = {
            "decision": "review",
            "review_reasons": ["non_aggregated_queries_without_limit_require_operator_review"],
        }
        bundle: Dict[str, Any] = build_policy_approval_bundle(verdict)

        assert bundle["approval_required"] is True
        assert len(bundle["approval_actions"]) >= 1
        assert len(bundle["review_rationale"]) == 1

    def test_allow_verdict_no_approval_needed(self) -> None:
        """Allow verdict should not require approval."""
        verdict: Dict[str, Any] = {"decision": "allow", "review_reasons": []}
        bundle: Dict[str, Any] = build_policy_approval_bundle(verdict)

        assert bundle["approval_required"] is False
        assert bundle["approval_actions"] == []

    def test_deny_verdict_no_approval_needed(self) -> None:
        """Deny verdict should not require approval (it is outright rejected)."""
        verdict: Dict[str, Any] = {"decision": "deny", "review_reasons": []}
        bundle: Dict[str, Any] = build_policy_approval_bundle(verdict)

        assert bundle["approval_required"] is False


# ---------------------------------------------------------------------------
# Policy schema
# ---------------------------------------------------------------------------


class TestPolicySchema:
    """Tests for the policy schema descriptor."""

    def test_schema_has_required_keys(self) -> None:
        """Policy schema should include deny_rules, review_rules, and sensitive_columns."""
        schema: Dict[str, Any] = build_policy_schema()

        assert schema["schema"] == "nexus-hive-policy-v1"
        assert "deny_rules" in schema
        assert "review_rules" in schema
        assert "sensitive_columns_by_role" in schema
        assert "write_operations_blocked" in schema["deny_rules"]
        assert "wildcard_projection_denied" in schema["deny_rules"]


# ---------------------------------------------------------------------------
# Query tag governance metadata
# ---------------------------------------------------------------------------


class TestPolicyQueryTags:
    """Tests for query tag generation used in governance audit trails."""

    def test_tag_includes_all_dimensions(self) -> None:
        """Query tag should include service, adapter, role, request_id, purpose."""
        tag: str = build_query_tag(
            request_id="req-abc-123",
            role="analyst",
            purpose="ask",
            adapter_name="snowflake-sql-contract",
        )

        assert "service=nexus-hive" in tag
        assert "adapter=snowflake-sql-contract" in tag
        assert "role=analyst" in tag
        assert "request_id=req-abc-123" in tag
        assert "purpose=ask" in tag

    def test_tag_defaults_for_empty_values(self) -> None:
        """Query tag should fall back to defaults for empty inputs."""
        tag: str = build_query_tag(request_id="", role="", purpose="")

        assert "role=analyst" in tag
        assert "purpose=ask" in tag
        assert "request_id=unknown" in tag

    def test_tag_with_databricks_adapter(self) -> None:
        """Query tag should accept Databricks adapter name."""
        tag: str = build_query_tag(
            request_id="r1",
            role="viewer",
            purpose="policy-check",
            adapter_name="databricks-sql-contract",
        )
        assert "adapter=databricks-sql-contract" in tag
        assert "role=viewer" in tag
        assert "purpose=policy-check" in tag
