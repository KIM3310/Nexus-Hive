"""
Mocked unit tests for the Snowflake warehouse adapter.

Tests Snowflake query execution, result formatting, schema retrieval,
connection pooling, and error handling using mocked snowflake-connector-python.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_snowflake_pool():
    """Reset the module-level connection pool before each test."""
    import snowflake_adapter

    snowflake_adapter._pool.close()
    yield
    snowflake_adapter._pool.close()


@pytest.fixture()
def mock_snowflake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set Snowflake environment variables for testing."""
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account.us-east-1")
    monkeypatch.setenv("SNOWFLAKE_USER", "test_user")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "test_pass")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "TEST_DB")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "TEST_WH")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")


def _make_mock_cursor(
    rows: List[Any],
    description: List[tuple] | None = None,
    rowcount: int | None = None,
) -> MagicMock:
    """Create a mock Snowflake cursor with configured return values."""
    cursor = MagicMock()
    cursor.execute = MagicMock()
    cursor.fetchmany = MagicMock(return_value=rows)
    cursor.fetchall = MagicMock(return_value=rows)
    cursor.fetchone = MagicMock(return_value=rows[0] if rows else None)
    cursor.description = description
    cursor.rowcount = rowcount if rowcount is not None else len(rows)
    cursor.sfqid = "mock-query-id-001"
    cursor.close = MagicMock()
    return cursor


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestSnowflakeConfiguration:
    """Tests for Snowflake adapter configuration detection."""

    def test_snowflake_configured_when_account_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """snowflake_configured() returns True when SNOWFLAKE_ACCOUNT is set."""
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
        from snowflake_adapter import snowflake_configured

        assert snowflake_configured() is True

    def test_snowflake_not_configured_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """snowflake_configured() returns False when SNOWFLAKE_ACCOUNT is empty."""
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "")
        from snowflake_adapter import snowflake_configured

        assert snowflake_configured() is False

    def test_snowflake_not_configured_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """snowflake_configured() returns False when SNOWFLAKE_ACCOUNT is unset."""
        monkeypatch.delenv("SNOWFLAKE_ACCOUNT", raising=False)
        from snowflake_adapter import snowflake_configured

        assert snowflake_configured() is False


# ---------------------------------------------------------------------------
# Query execution tests
# ---------------------------------------------------------------------------


class TestSnowflakeQueryExecution:
    """Tests for Snowflake query execution with mocked connections."""

    def test_execute_query_returns_correct_format(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execute_snowflake_query should return a dict with standard adapter fields."""
        mock_rows = [
            {"REGION_NAME": "North America", "TOTAL_REVENUE": 150000.50},
            {"REGION_NAME": "EMEA", "TOTAL_REVENUE": 120000.75},
            {"REGION_NAME": "APAC", "TOTAL_REVENUE": 90000.25},
        ]
        description = [("REGION_NAME",), ("TOTAL_REVENUE",)]
        mock_cursor = _make_mock_cursor(mock_rows, description=description, rowcount=3)

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        result: Dict[str, Any] = snowflake_adapter.execute_snowflake_query(
            "SELECT region_name, SUM(net_revenue) AS total_revenue FROM sales GROUP BY region_name"
        )

        assert "row_count" in result
        assert "preview" in result
        assert "elapsed_ms" in result
        assert result["adapter_name"] == "snowflake-live"
        assert result["execution_mode"] == "snowflake-live"
        assert result["row_count"] == 3
        assert len(result["preview"]) <= 5

    def test_execute_query_normalizes_column_names_to_lowercase(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Result column names should be lowercased from Snowflake's uppercase defaults."""
        mock_rows = [{"REGION_NAME": "NA", "TOTAL": 100}]
        description = [("REGION_NAME",), ("TOTAL",)]
        mock_cursor = _make_mock_cursor(mock_rows, description=description)

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        result = snowflake_adapter.execute_snowflake_query("SELECT region_name, COUNT(*) AS total FROM sales GROUP BY region_name")
        preview = result["preview"]

        assert len(preview) > 0
        for key in preview[0]:
            assert key == key.lower(), f"Column name '{key}' should be lowercase"

    def test_execute_query_includes_query_id(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Result should include the Snowflake query ID for audit trail."""
        mock_cursor = _make_mock_cursor(
            [{"X": 1}], description=[("X",)], rowcount=1
        )
        mock_cursor.sfqid = "sf-query-abc123"

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        result = snowflake_adapter.execute_snowflake_query("SELECT 1 AS x")
        assert result["query_id"] == "sf-query-abc123"

    def test_execute_query_limits_preview_to_5_rows(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preview should contain at most 5 rows even if more are returned."""
        mock_rows = [{"ID": i} for i in range(10)]
        description = [("ID",)]
        mock_cursor = _make_mock_cursor(mock_rows, description=description, rowcount=10)

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        result = snowflake_adapter.execute_snowflake_query("SELECT id FROM big_table")
        assert len(result["preview"]) == 5
        assert result["row_count"] == 10


# ---------------------------------------------------------------------------
# Scalar query tests
# ---------------------------------------------------------------------------


class TestSnowflakeScalarQuery:
    """Tests for scalar query execution."""

    def test_scalar_query_returns_int(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_snowflake_scalar_query should return a single integer."""
        mock_cursor = _make_mock_cursor(
            [{"ROW_COUNT": 42}], description=[("ROW_COUNT",)], rowcount=1
        )
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        result: int = snowflake_adapter.run_snowflake_scalar_query("SELECT COUNT(*) AS row_count FROM sales")
        assert result == 42
        assert isinstance(result, int)

    def test_scalar_query_returns_zero_for_empty_result(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_snowflake_scalar_query should return 0 for empty results."""
        mock_cursor = _make_mock_cursor([], description=[("CNT",)], rowcount=0)
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        result: int = snowflake_adapter.run_snowflake_scalar_query("SELECT COUNT(*) FROM empty_table")
        assert result == 0


# ---------------------------------------------------------------------------
# Schema retrieval tests
# ---------------------------------------------------------------------------


class TestSnowflakeSchema:
    """Tests for Snowflake schema retrieval."""

    def test_get_schema_returns_ddl_text(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_snowflake_schema should return DDL text for all tables."""
        show_tables_cursor = MagicMock()
        show_tables_cursor.fetchall = MagicMock(
            return_value=[
                (None, "SALES", None),
                (None, "REGIONS", None),
            ]
        )
        show_tables_cursor.close = MagicMock()

        ddl_cursor_sales = MagicMock()
        ddl_cursor_sales.fetchone = MagicMock(
            return_value=("CREATE TABLE SALES (transaction_id VARCHAR, date DATE)",)
        )
        ddl_cursor_sales.close = MagicMock()

        ddl_cursor_regions = MagicMock()
        ddl_cursor_regions.fetchone = MagicMock(
            return_value=("CREATE TABLE REGIONS (region_id INT, region_name VARCHAR)",)
        )
        ddl_cursor_regions.close = MagicMock()

        cursors = [show_tables_cursor, ddl_cursor_sales, ddl_cursor_regions]
        cursor_index = {"i": 0}

        def mock_cursor_factory(*args: Any, **kwargs: Any) -> MagicMock:
            idx = cursor_index["i"]
            cursor_index["i"] += 1
            return cursors[idx]

        mock_conn = MagicMock()
        mock_conn.cursor = mock_cursor_factory

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        schema: str = snowflake_adapter.get_snowflake_schema()

        assert "SALES" in schema
        assert "REGIONS" in schema
        assert "CREATE TABLE" in schema


# ---------------------------------------------------------------------------
# Date window tests
# ---------------------------------------------------------------------------


class TestSnowflakeDateWindow:
    """Tests for date window retrieval."""

    def test_fetch_date_window_returns_min_max(
        self, mock_snowflake_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_snowflake_date_window should return min and max dates."""
        mock_cursor = _make_mock_cursor(
            [{"min_date": "2024-01-01", "max_date": "2024-12-31"}],
            description=[("MIN_DATE",), ("MAX_DATE",)],
            rowcount=1,
        )
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter._pool, "get_connection", lambda: mock_conn)

        window = snowflake_adapter.fetch_snowflake_date_window()

        assert window["min_date"] == "2024-01-01"
        assert window["max_date"] == "2024-12-31"


# ---------------------------------------------------------------------------
# Connection pool tests
# ---------------------------------------------------------------------------


class TestSnowflakeConnectionPool:
    """Tests for the connection pool singleton behavior."""

    def test_pool_raises_when_package_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connection pool should raise RuntimeError when snowflake-connector-python is missing."""
        import snowflake_adapter

        monkeypatch.setattr(snowflake_adapter, "SNOWFLAKE_AVAILABLE", False)

        pool = snowflake_adapter.SnowflakeConnectionPool()
        with pytest.raises(RuntimeError, match="snowflake-connector-python"):
            pool.get_connection()
