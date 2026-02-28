"""
Mocked unit tests for the Databricks warehouse adapter.

Tests Databricks query execution, result extraction, schema retrieval,
configuration detection, and error handling using mocked databricks-sdk.
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


@pytest.fixture()
def mock_databricks_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set Databricks environment variables for testing."""
    monkeypatch.setenv("DATABRICKS_HOST", "https://dbc-test.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test-token-123")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-abc-123")
    monkeypatch.setenv("DATABRICKS_CATALOG", "main")
    monkeypatch.setenv("DATABRICKS_SCHEMA", "default")


def _make_mock_response(
    columns: List[str],
    rows: List[List[Any]],
    state: str = "SUCCEEDED",
    statement_id: str = "stmt-mock-001",
    row_count: int | None = None,
) -> MagicMock:
    """Create a mock Databricks statement execution response."""
    # Build column schema
    mock_columns = []
    for col_name in columns:
        col = MagicMock()
        col.name = col_name
        mock_columns.append(col)

    mock_schema = MagicMock()
    mock_schema.columns = mock_columns

    mock_manifest = MagicMock()
    mock_manifest.schema = mock_schema
    mock_manifest.total_row_count = row_count if row_count is not None else len(rows)

    mock_result = MagicMock()
    mock_result.data_array = rows
    mock_result.row_count = row_count if row_count is not None else len(rows)

    mock_state = MagicMock()
    mock_state.value = state

    mock_status = MagicMock()
    mock_status.state = mock_state
    mock_status.error = None

    response = MagicMock()
    response.manifest = mock_manifest
    response.result = mock_result
    response.status = mock_status
    response.statement_id = statement_id

    return response


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestDatabricksConfiguration:
    """Tests for Databricks adapter configuration detection."""

    def test_configured_with_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """databricks_configured() returns True with host and token."""
        monkeypatch.setenv("DATABRICKS_HOST", "https://dbc.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-token")
        monkeypatch.delenv("DATABRICKS_AUTH_TYPE", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CLIENT_SECRET", raising=False)

        from databricks_adapter import databricks_configured

        assert databricks_configured() is True

    def test_configured_with_auth_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """databricks_configured() returns True with host and auth_type."""
        monkeypatch.setenv("DATABRICKS_HOST", "https://dbc.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_AUTH_TYPE", "databricks-cli")
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CLIENT_SECRET", raising=False)

        from databricks_adapter import databricks_configured

        assert databricks_configured() is True

    def test_configured_with_client_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """databricks_configured() returns True with host and client credentials."""
        monkeypatch.setenv("DATABRICKS_HOST", "https://dbc.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_CLIENT_ID", "client-id-123")
        monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "client-secret-456")
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        monkeypatch.delenv("DATABRICKS_AUTH_TYPE", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        from databricks_adapter import databricks_configured

        assert databricks_configured() is True

    def test_not_configured_without_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """databricks_configured() returns False without DATABRICKS_HOST."""
        monkeypatch.setenv("DATABRICKS_HOST", "")
        monkeypatch.setenv("DATABRICKS_TOKEN", "some-token")

        from databricks_adapter import databricks_configured

        assert databricks_configured() is False

    def test_not_configured_without_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """databricks_configured() returns False with host but no auth method."""
        monkeypatch.setenv("DATABRICKS_HOST", "https://dbc.cloud.databricks.com")
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        monkeypatch.delenv("DATABRICKS_AUTH_TYPE", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CLIENT_SECRET", raising=False)

        from databricks_adapter import databricks_configured

        assert databricks_configured() is False


# ---------------------------------------------------------------------------
# Result extraction tests
# ---------------------------------------------------------------------------


class TestDatabricksResultExtraction:
    """Tests for extracting and formatting Databricks query results."""

    def test_extract_rows_from_response(self) -> None:
        """_extract_rows should parse columns and rows from a mock response."""
        from databricks_adapter import _extract_rows

        response = _make_mock_response(
            columns=["region_name", "total_revenue"],
            rows=[
                ["North America", "150000.50"],
                ["EMEA", "120000.75"],
            ],
        )

        result = _extract_rows(response)

        assert result["columns"] == ["region_name", "total_revenue"]
        assert len(result["rows"]) == 2
        assert result["rows"][0]["region_name"] == "North America"
        assert result["rows"][0]["total_revenue"] == "150000.50"
        assert result["row_count"] == 2
        assert result["statement_id"] == "stmt-mock-001"

    def test_extract_rows_empty_result(self) -> None:
        """_extract_rows should handle empty result sets."""
        from databricks_adapter import _extract_rows

        response = _make_mock_response(
            columns=["col_a"],
            rows=[],
            row_count=0,
        )

        result = _extract_rows(response)

        assert result["rows"] == []
        assert result["row_count"] == 0
        assert result["columns"] == ["col_a"]

    def test_extract_rows_lowercases_column_names(self) -> None:
        """_extract_rows should lowercase column names."""
        from databricks_adapter import _extract_rows

        response = _make_mock_response(
            columns=["Region_Name", "TOTAL"],
            rows=[["NA", "100"]],
        )

        result = _extract_rows(response)

        assert "region_name" in result["columns"]
        assert "total" in result["columns"]
        assert "region_name" in result["rows"][0]


# ---------------------------------------------------------------------------
# Statement execution tests
# ---------------------------------------------------------------------------


class TestDatabricksStatementExecution:
    """Tests for statement execution with mocked WorkspaceClient."""

    def test_execute_query_returns_standard_format(
        self, mock_databricks_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execute_databricks_query should return the standard adapter result format."""
        mock_response = _make_mock_response(
            columns=["category", "total_quantity"],
            rows=[
                ["Electronics", "500"],
                ["Apparel", "300"],
                ["Food", "200"],
            ],
        )

        import databricks_adapter

        monkeypatch.setattr(
            databricks_adapter,
            "_execute_statement",
            lambda sql, **kwargs: mock_response,
        )

        result: Dict[str, Any] = databricks_adapter.execute_databricks_query(
            "SELECT category, SUM(quantity) AS total_quantity FROM sales GROUP BY category"
        )

        assert result["row_count"] == 3
        assert len(result["preview"]) == 3
        assert result["adapter_name"] == "databricks-live"
        assert result["execution_mode"] == "databricks-live"
        assert "elapsed_ms" in result
        assert "statement_id" in result

    def test_execute_query_limits_preview_to_5(
        self, mock_databricks_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execute_databricks_query preview should contain at most 5 rows."""
        mock_response = _make_mock_response(
            columns=["id"],
            rows=[[str(i)] for i in range(20)],
            row_count=20,
        )

        import databricks_adapter

        monkeypatch.setattr(
            databricks_adapter,
            "_execute_statement",
            lambda sql, **kwargs: mock_response,
        )

        result = databricks_adapter.execute_databricks_query("SELECT id FROM big_table")
        assert len(result["preview"]) == 5
        assert result["row_count"] == 20

    def test_scalar_query_returns_int(
        self, mock_databricks_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_databricks_scalar_query should return a single integer value."""
        mock_response = _make_mock_response(
            columns=["row_count"],
            rows=[["42"]],
            row_count=1,
        )

        import databricks_adapter

        monkeypatch.setattr(
            databricks_adapter,
            "_execute_statement",
            lambda sql, **kwargs: mock_response,
        )

        result: int = databricks_adapter.run_databricks_scalar_query(
            "SELECT COUNT(*) AS row_count FROM sales"
        )
        assert result == 42
        assert isinstance(result, int)

    def test_scalar_query_returns_zero_for_empty(
        self, mock_databricks_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_databricks_scalar_query should return 0 for empty results."""
        mock_response = _make_mock_response(
            columns=["cnt"],
            rows=[],
            row_count=0,
        )

        import databricks_adapter

        monkeypatch.setattr(
            databricks_adapter,
            "_execute_statement",
            lambda sql, **kwargs: mock_response,
        )

        result: int = databricks_adapter.run_databricks_scalar_query(
            "SELECT COUNT(*) FROM empty_table"
        )
        assert result == 0


# ---------------------------------------------------------------------------
# Statement failure tests
# ---------------------------------------------------------------------------


class TestDatabricksStatementFailure:
    """Tests for handling Databricks statement execution failures."""

    def test_failed_statement_raises_runtime_error(
        self, mock_databricks_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_execute_statement should raise RuntimeError when statement fails."""
        mock_state = MagicMock()
        mock_state.value = "FAILED"

        mock_error = MagicMock()
        mock_error.message = "SYNTAX_ERROR: unexpected token"

        mock_status = MagicMock()
        mock_status.state = mock_state
        mock_status.error = mock_error

        mock_response = MagicMock()
        mock_response.status = mock_status

        mock_client = MagicMock()
        mock_client.statement_execution.execute_statement = MagicMock(return_value=mock_response)

        import databricks_adapter

        monkeypatch.setattr(databricks_adapter, "_build_workspace_client", lambda: mock_client)
        monkeypatch.setattr(databricks_adapter, "_resolve_warehouse_id", lambda c: "wh-123")

        with pytest.raises(RuntimeError, match="SYNTAX_ERROR"):
            databricks_adapter._execute_statement("INVALID SQL HERE")


# ---------------------------------------------------------------------------
# Date window tests
# ---------------------------------------------------------------------------


class TestDatabricksDateWindow:
    """Tests for date window retrieval."""

    def test_fetch_date_window(
        self, mock_databricks_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_databricks_date_window should return min and max dates."""
        mock_response = _make_mock_response(
            columns=["min_date", "max_date"],
            rows=[["2024-01-15", "2024-12-28"]],
            row_count=1,
        )

        import databricks_adapter

        monkeypatch.setattr(
            databricks_adapter,
            "_execute_statement",
            lambda sql, **kwargs: mock_response,
        )

        window = databricks_adapter.fetch_databricks_date_window()
        assert window["min_date"] == "2024-01-15"
        assert window["max_date"] == "2024-12-28"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestDatabricksHelpers:
    """Tests for Databricks adapter helper functions."""

    def test_quote_escapes_backticks(self) -> None:
        """_quote should escape backticks in identifiers."""
        from databricks_adapter import _quote

        assert _quote("my_table") == "`my_table`"
        assert _quote("has`tick") == "`has``tick`"

    def test_table_fqn_uses_catalog_schema(
        self, mock_databricks_env: None
    ) -> None:
        """_table_fqn should produce catalog.schema.table format."""
        from databricks_adapter import _table_fqn

        fqn = _table_fqn("sales")
        assert "`main`" in fqn
        assert "`default`" in fqn
        assert "`sales`" in fqn

    def test_build_workspace_client_raises_when_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_workspace_client should raise RuntimeError when SDK is missing."""
        import databricks_adapter

        monkeypatch.setattr(databricks_adapter, "DATABRICKS_AVAILABLE", False)

        with pytest.raises(RuntimeError, match="databricks-sdk"):
            databricks_adapter._build_workspace_client()
