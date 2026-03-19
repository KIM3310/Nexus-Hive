"""
Unit tests for SQL generation logic, policy engine, and heuristic inference.

Covers SQL inference from questions, policy evaluation, query tag building,
chart config inference, SQL validation, circuit breaker, and edge cases.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from policy.engine import (
    build_policy_approval_bundle,
    build_policy_schema,
    build_query_tag,
    build_query_tag_contract,
    evaluate_sql_case,
    evaluate_sql_policy,
    infer_chart_config_from_question,
    infer_sql_from_question,
)
from warehouse_adapter import validate_sql_safety
from exceptions import (
    SQLValidationError,
    PolicyDeniedError,
    OllamaConnectionError,
    CircuitBreakerOpenError,
    AgentOrchestrationError,
    NexusHiveError,
)
from circuit_breaker import CircuitBreaker, CircuitState


# ---------------------------------------------------------------------------
# SQL inference from questions
# ---------------------------------------------------------------------------


class TestSQLInference:
    """Tests for heuristic SQL inference from natural language questions."""

    def test_revenue_by_region_default(self) -> None:
        """Default fallback should produce a revenue-by-region query."""
        sql: str = infer_sql_from_question("Show total net revenue by region")
        assert "SUM" in sql.upper()
        assert "JOIN" in sql.upper()
        assert "region" in sql.lower()
        assert "GROUP BY" in sql.upper()

    def test_profit_by_region_top5(self) -> None:
        """Profit by region with top 5 should include LIMIT 5."""
        sql: str = infer_sql_from_question("Show top 5 regions by total profit")
        assert "profit" in sql.lower()
        assert "LIMIT 5" in sql

    def test_profit_by_region_default_limit(self) -> None:
        """Profit by region without top 5 should use LIMIT 10."""
        sql: str = infer_sql_from_question("Show profit by region")
        assert "LIMIT 10" in sql

    def test_discount_by_category(self) -> None:
        """Discount by category should use AVG and JOIN products."""
        sql: str = infer_sql_from_question("What is the average discount per category?")
        assert "AVG" in sql.upper()
        assert "category" in sql.lower()

    def test_monthly_revenue_trend(self) -> None:
        """Monthly revenue trend should use SUBSTR for month extraction."""
        sql: str = infer_sql_from_question("Show monthly net revenue trend")
        assert "SUBSTR" in sql.upper()
        assert "month" in sql.lower()

    def test_quantity_by_category(self) -> None:
        """Quantity by category should use SUM(quantity)."""
        sql: str = infer_sql_from_question("Show total quantity by category")
        assert "SUM" in sql.upper()
        assert "quantity" in sql.lower()

    def test_category_revenue(self) -> None:
        """Revenue by category should join products."""
        sql: str = infer_sql_from_question("Show revenue by category")
        assert "category" in sql.lower()
        assert "net_revenue" in sql.lower()

    def test_unrecognized_question_returns_default(self) -> None:
        """Unrecognized questions should return the default revenue query."""
        sql: str = infer_sql_from_question("Tell me something random")
        assert "SELECT" in sql.upper()
        assert "net_revenue" in sql.lower()

    def test_empty_question_returns_default(self) -> None:
        """Empty question should return the default query."""
        sql: str = infer_sql_from_question("")
        assert "SELECT" in sql.upper()


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


class TestPolicyEvaluation:
    """Tests for SQL policy enforcement and evaluation."""

    def test_allow_safe_aggregated_query(self) -> None:
        """Safe aggregated queries with LIMIT should be allowed."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name LIMIT 10"
        )
        assert verdict["decision"] == "allow"
        assert verdict["deny_reasons"] == []
        assert verdict["review_reasons"] == []

    def test_deny_wildcard_projection(self) -> None:
        """SELECT * should be denied."""
        verdict: Dict[str, Any] = evaluate_sql_policy("SELECT * FROM sales")
        assert verdict["decision"] == "deny"
        assert "wildcard_projection_denied" in verdict["deny_reasons"]

    def test_deny_write_operations(self) -> None:
        """Write operations (DROP, DELETE, etc.) should be denied."""
        for keyword in ["DROP TABLE sales", "DELETE FROM sales", "INSERT INTO sales VALUES (1)", "UPDATE sales SET x=1"]:
            verdict: Dict[str, Any] = evaluate_sql_policy(keyword)
            assert verdict["decision"] == "deny", f"Expected deny for: {keyword}"
            assert "write_operations_blocked" in verdict["deny_reasons"]

    def test_deny_sensitive_columns_analyst(self) -> None:
        """Analyst role should be denied access to margin_percentage."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT margin_percentage FROM products", role="analyst"
        )
        assert verdict["decision"] == "deny"
        assert "sensitive_columns_require_privileged_role" in verdict["deny_reasons"]

    def test_review_non_aggregated_without_limit(self) -> None:
        """Non-aggregated queries without LIMIT should require review."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT transaction_id FROM sales"
        )
        assert verdict["decision"] == "review"
        assert "non_aggregated_queries_without_limit_require_operator_review" in verdict["review_reasons"]

    def test_allow_query_with_group_by(self) -> None:
        """Queries with GROUP BY should pass the review check."""
        verdict: Dict[str, Any] = evaluate_sql_policy(
            "SELECT region_name, COUNT(*) FROM sales GROUP BY region_name"
        )
        # GROUP BY is present, so no review required (but COUNT(*) won't trigger wildcard)
        # Actually "SELECT region_name, COUNT(*)" does not contain "SELECT *"
        assert verdict["decision"] == "allow"

    def test_policy_schema_structure(self) -> None:
        """Policy schema should have required keys."""
        schema: Dict[str, Any] = build_policy_schema()
        assert schema["schema"] == "nexus-hive-policy-v1"
        assert "deny_rules" in schema
        assert "review_rules" in schema

    def test_approval_bundle_for_review(self) -> None:
        """Approval bundle should flag review-required verdicts."""
        verdict: Dict[str, Any] = {"decision": "review", "review_reasons": ["test_reason"]}
        bundle: Dict[str, Any] = build_policy_approval_bundle(verdict)
        assert bundle["approval_required"] is True
        assert len(bundle["approval_actions"]) >= 1

    def test_approval_bundle_for_allow(self) -> None:
        """Approval bundle should not flag allowed verdicts."""
        verdict: Dict[str, Any] = {"decision": "allow", "review_reasons": []}
        bundle: Dict[str, Any] = build_policy_approval_bundle(verdict)
        assert bundle["approval_required"] is False
        assert bundle["approval_actions"] == []


# ---------------------------------------------------------------------------
# Query tag building
# ---------------------------------------------------------------------------


class TestQueryTag:
    """Tests for governance query tag generation."""

    def test_basic_query_tag(self) -> None:
        """Query tag should include all required dimensions."""
        tag: str = build_query_tag(
            request_id="req-123", role="analyst", purpose="ask"
        )
        assert "service=nexus-hive" in tag
        assert "adapter=sqlite-demo" in tag
        assert "role=analyst" in tag
        assert "request_id=req-123" in tag
        assert "purpose=ask" in tag

    def test_query_tag_with_custom_adapter(self) -> None:
        """Query tag should accept custom adapter names."""
        tag: str = build_query_tag(
            request_id="r1",
            role="viewer",
            purpose="policy-check",
            adapter_name="snowflake-sql-contract",
        )
        assert "adapter=snowflake-sql-contract" in tag

    def test_query_tag_defaults(self) -> None:
        """Query tag should use defaults for empty values."""
        tag: str = build_query_tag(request_id="", role="", purpose="")
        assert "role=analyst" in tag
        assert "purpose=ask" in tag
        assert "request_id=unknown" in tag

    def test_query_tag_contract_structure(self) -> None:
        """Query tag contract should describe required dimensions."""
        contract: Dict[str, Any] = build_query_tag_contract()
        assert contract["schema"] == "nexus-hive-query-tag-v1"
        assert "request_id" in contract["required_dimensions"]


# ---------------------------------------------------------------------------
# SQL case evaluation (gold eval)
# ---------------------------------------------------------------------------


class TestSQLCaseEvaluation:
    """Tests for SQL feature matching used by gold eval."""

    def test_full_match(self) -> None:
        """All features matched should return pass status."""
        result: Dict[str, Any] = evaluate_sql_case(
            "SELECT SUM(net_revenue) FROM sales JOIN regions GROUP BY region_name",
            ["SUM(net_revenue)", "JOIN regions", "GROUP BY region_name"],
        )
        assert result["status"] == "pass"
        assert result["score"] == result["max_score"]

    def test_partial_match(self) -> None:
        """Partial matches should return partial status."""
        result: Dict[str, Any] = evaluate_sql_case(
            "SELECT SUM(net_revenue) FROM sales",
            ["SUM(net_revenue)", "JOIN regions", "GROUP BY region_name"],
        )
        assert result["status"] == "partial"
        assert len(result["missing_features"]) > 0

    def test_no_match(self) -> None:
        """No matches should return partial status with zero score."""
        result: Dict[str, Any] = evaluate_sql_case(
            "SELECT 1",
            ["SUM(net_revenue)", "JOIN regions"],
        )
        assert result["score"] == 0
        assert result["status"] == "partial"


# ---------------------------------------------------------------------------
# Chart config inference
# ---------------------------------------------------------------------------


class TestChartConfigInference:
    """Tests for heuristic Chart.js configuration generation."""

    def test_empty_rows_returns_default(self) -> None:
        """Empty result set should return a default bar chart."""
        config: Dict[str, Any] = infer_chart_config_from_question("Show revenue", [])
        assert config["type"] == "bar"
        assert config["labels_key"] == "label"
        assert config["data_key"] == "value"

    def test_trend_question_returns_line(self) -> None:
        """Trend questions should produce line charts."""
        rows: List[Dict[str, Any]] = [
            {"month": "2024-01", "total": 100},
            {"month": "2024-02", "total": 200},
        ]
        config: Dict[str, Any] = infer_chart_config_from_question(
            "Show monthly revenue trend", rows
        )
        assert config["type"] == "line"

    def test_few_regions_returns_doughnut(self) -> None:
        """Small categorical data with region keyword should produce doughnut."""
        rows: List[Dict[str, Any]] = [
            {"region": "NA", "revenue": 100},
            {"region": "EMEA", "revenue": 200},
        ]
        config: Dict[str, Any] = infer_chart_config_from_question(
            "Show revenue share by region", rows
        )
        assert config["type"] == "doughnut"

    def test_large_dataset_returns_bar(self) -> None:
        """Large datasets should default to bar charts."""
        rows: List[Dict[str, Any]] = [{"x": i, "y": i * 10} for i in range(20)]
        config: Dict[str, Any] = infer_chart_config_from_question(
            "Show all data", rows
        )
        assert config["type"] == "bar"


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------


class TestSQLValidation:
    """Tests for SQL read-only validation and safety checks."""

    def test_valid_select(self) -> None:
        """Valid SELECT should pass validation."""
        validate_sql_safety("SELECT region_name FROM regions LIMIT 10")

    def test_empty_sql_raises(self) -> None:
        """Empty SQL should raise SQLValidationError."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("")

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only SQL should raise SQLValidationError."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("   ")

    def test_drop_table_raises(self) -> None:
        """DROP TABLE should be blocked."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("DROP TABLE sales")

    def test_insert_raises(self) -> None:
        """INSERT should be blocked."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("INSERT INTO sales VALUES (1)")

    def test_update_raises(self) -> None:
        """UPDATE should be blocked."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("UPDATE sales SET x = 1")

    def test_with_cte_allowed(self) -> None:
        """WITH (CTE) statements should be allowed."""
        validate_sql_safety(
            "WITH cte AS (SELECT 1) SELECT * FROM cte"
        )
        # Note: "SELECT *" inside a CTE is technically valid SQL but
        # the policy engine would deny it separately; validation only
        # checks keywords, not policy rules.

    def test_comment_bypass_blocked(self) -> None:
        """SQL injection via comments should be blocked."""
        with pytest.raises(SQLValidationError):
            validate_sql_safety("SELECT 1; -- DROP TABLE sales\nDROP TABLE sales")


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests for the Ollama circuit breaker pattern."""

    def test_starts_closed(self) -> None:
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker(service_name="test", failure_threshold=3, recovery_timeout_sec=1.0)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_opens_after_threshold(self) -> None:
        """Circuit should open after reaching failure threshold."""
        cb = CircuitBreaker(service_name="test", failure_threshold=3, recovery_timeout_sec=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    def test_check_raises_when_open(self) -> None:
        """Check should raise CircuitBreakerOpenError when circuit is open."""
        cb = CircuitBreaker(service_name="test", failure_threshold=2, recovery_timeout_sec=60.0)
        cb.record_failure()
        cb.record_failure()
        with pytest.raises(CircuitBreakerOpenError):
            cb.check()

    def test_success_resets_to_closed(self) -> None:
        """Recording success should reset the circuit to CLOSED."""
        cb = CircuitBreaker(service_name="test", failure_threshold=3, recovery_timeout_sec=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_after_timeout(self) -> None:
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(service_name="test", failure_threshold=2, recovery_timeout_sec=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_manual_reset(self) -> None:
        """Manual reset should return circuit to CLOSED."""
        cb = CircuitBreaker(service_name="test", failure_threshold=2, recovery_timeout_sec=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    """Tests for custom exception types."""

    def test_sql_validation_error_fields(self) -> None:
        """SQLValidationError should carry sql and violation_type."""
        err = SQLValidationError(
            "blocked", sql="DROP TABLE x", violation_type="blocked_keyword"
        )
        assert err.sql == "DROP TABLE x"
        assert err.violation_type == "blocked_keyword"
        assert str(err) == "blocked"

    def test_policy_denied_error_fields(self) -> None:
        """PolicyDeniedError should carry deny_reasons."""
        err = PolicyDeniedError(
            "denied", deny_reasons=["wildcard", "write"]
        )
        assert err.deny_reasons == ["wildcard", "write"]

    def test_ollama_connection_error_fields(self) -> None:
        """OllamaConnectionError should carry url and model."""
        err = OllamaConnectionError(
            "timeout", url="http://localhost:11434", model="phi3"
        )
        assert err.url == "http://localhost:11434"
        assert err.model == "phi3"

    def test_circuit_breaker_open_error_fields(self) -> None:
        """CircuitBreakerOpenError should carry service_name and failure_count."""
        err = CircuitBreakerOpenError(
            "open", service_name="ollama", failure_count=5
        )
        assert err.service_name == "ollama"
        assert err.failure_count == 5

    def test_agent_orchestration_error(self) -> None:
        """AgentOrchestrationError should carry agent_name and retry_count."""
        err = AgentOrchestrationError(
            "failed", agent_name="translator", retry_count=3
        )
        assert err.agent_name == "translator"
        assert err.retry_count == 3

    def test_base_error_details(self) -> None:
        """NexusHiveError should support details dict."""
        err = NexusHiveError("test", details={"key": "value"})
        assert err.details == {"key": "value"}
