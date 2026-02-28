from __future__ import annotations

import warehouse_adapter as wa


def test_get_active_warehouse_adapter_uses_live_databricks_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_HIVE_WAREHOUSE_ADAPTER", "databricks-sql-contract")
    monkeypatch.setenv("DATABRICKS_HOST", "https://dbc-example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_AUTH_TYPE", "databricks-cli")
    monkeypatch.setattr(wa, "DATABRICKS_AVAILABLE", True)
    monkeypatch.setattr(wa, "databricks_configured", lambda: True)

    adapter = wa.get_active_warehouse_adapter()

    assert isinstance(adapter, wa.LiveDatabricksWarehouseAdapter)
    assert adapter.contract.name == "databricks-sql-contract"
    assert adapter.contract.execution_mode == "databricks-live"
