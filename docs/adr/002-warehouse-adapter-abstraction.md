# ADR 002: Warehouse Adapter Abstraction

## Status

Accepted

## Date

2026-03-15

## Context

Nexus-Hive executes SQL against a data warehouse to answer business questions. Different deployment environments require different backends:

- **Local development and demos** need a zero-configuration database that ships with the repository.
- **Production deployments** target cloud warehouses like Snowflake or Databricks, each with distinct connection protocols, SQL dialects, and authentication models.

We needed an architecture that supports all three backends without duplicating core logic in the agent pipeline, policy engine, or API layer.

## Decision

We adopted the **Adapter pattern** with a shared `WarehouseAdapter` base class and a runtime registry that selects the active adapter based on environment configuration.

### Architecture

```
WarehouseAdapter (base class)
  - get_schema(db_path) -> str
  - run_scalar_query(sql, db_path) -> int
  - fetch_date_window(db_path) -> dict
  - build_table_profiles(db_path) -> list
  - execute_sql_preview(sql, db_path) -> dict
      |
      ├── SqliteWarehouseAdapter        (local SQLite, active by default)
      ├── LiveSnowflakeWarehouseAdapter  (live Snowflake via snowflake-connector-python)
      └── LiveDatabricksWarehouseAdapter (live Databricks via Statement Execution API)
```

Each adapter implements the same five methods with identical return formats. The `get_active_warehouse_adapter()` function reads `NEXUS_HIVE_WAREHOUSE_ADAPTER` and credential environment variables to select the appropriate adapter at runtime.

### Adapter Selection Logic

1. If `SNOWFLAKE_ACCOUNT` is set and the `snowflake-connector-python` package is installed, the Snowflake live adapter activates.
2. If `DATABRICKS_HOST` is set with valid auth (token, profile, or client credentials) and `databricks-sdk` is installed, the Databricks live adapter activates.
3. Otherwise, the SQLite demo adapter is used.

This means the same codebase and Docker image work for demos (SQLite) and production (Snowflake/Databricks) with no code changes -- only environment variables differ.

## Consequences

### Benefits

- **Demo-to-production continuity.** New users can `git clone`, `seed_db.py`, and interact with the full agent pipeline immediately using SQLite. The same pipeline, policy engine, and audit trail run unchanged when pointed at Snowflake or Databricks.

- **Uniform result format.** All adapters return `{"row_count": int, "preview": list, "elapsed_ms": int, "adapter_name": str, "execution_mode": str}`. The Executor node and Visualizer node never branch on adapter type.

- **Independent adapter testing.** Snowflake and Databricks adapters can be tested with mocked connectors without standing up a live warehouse. The SQLite adapter is tested against a real (but ephemeral) database.

- **Pluggable for future backends.** Adding a new warehouse (e.g., BigQuery, Redshift) requires implementing five methods and registering the adapter. No changes to the agent pipeline, policy engine, or API layer.

- **Contract metadata.** Each adapter carries a `WarehouseAdapterContract` dataclass describing its capabilities, SQL dialect, execution mode, and review notes. This metadata flows into query tags, audit logs, and the `/api/meta` endpoint.

### Tradeoffs

- **SQL dialect differences.** The Translator agent must know the target SQL dialect (SQLite vs. Snowflake SQL vs. Databricks SQL) to generate correct queries. This is handled via `prompt_sql_target()` which injects the dialect into the LLM prompt. Heuristic fallback SQL is SQLite-flavored and may need dialect-specific adjustments for production warehouses.

- **db_path parameter on all methods.** The base interface accepts a `db_path` parameter because SQLite needs it, but cloud adapters ignore it. This is a minor API wart that we accept for interface uniformity.

- **Optional dependency management.** `snowflake-connector-python` and `databricks-sdk` are optional extras (`pip install -e ".[snowflake]"` / `pip install -e ".[databricks]"`). The adapters use guarded imports with `try/except ImportError` to avoid hard failures when these packages are absent.

## References

- `warehouse_adapter.py` -- Base class, SQLite adapter, adapter registry
- `snowflake_adapter.py` -- Snowflake live adapter with connection pooling
- `databricks_adapter.py` -- Databricks live adapter with Statement Execution API
- `config.py` -- Environment variable reading for adapter selection
