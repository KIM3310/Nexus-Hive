from __future__ import annotations

from warehouse_adapter import get_active_warehouse_adapter


def test_get_active_warehouse_adapter_returns_live_snowflake_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_HIVE_WAREHOUSE_ADAPTER", "snowflake-sql-contract")
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "demo-account")
    monkeypatch.setattr("warehouse_adapter.SNOWFLAKE_AVAILABLE", True)

    adapter = get_active_warehouse_adapter()

    assert adapter.contract.name == "snowflake-sql-contract"
    assert adapter.contract.execution_mode == "snowflake-live"
    assert adapter.contract.status == "active"
