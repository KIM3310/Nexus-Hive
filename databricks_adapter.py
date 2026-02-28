"""Databricks SQL warehouse adapter for Nexus-Hive.

Provides live SQL execution against a Databricks SQL warehouse using the
Databricks SDK Statement Execution API with unified authentication support.
The adapter activates when a Databricks workspace host is configured and either
an auth profile or token is available.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("nexus_hive.databricks_adapter")

try:
    from databricks.sdk import WorkspaceClient

    DATABRICKS_AVAILABLE = True
except ImportError:
    WorkspaceClient = None  # type: ignore[misc,assignment]
    DATABRICKS_AVAILABLE = False
    _logger.debug("databricks-sdk not installed; Databricks adapter unavailable")


DATABRICKS_QUERY_TIMEOUT_SEC: int = int(os.getenv("DATABRICKS_QUERY_TIMEOUT_SEC", "120"))


def databricks_configured() -> bool:
    settings = _settings()
    return bool(
        settings["host"]
        and (
            settings["token"]
            or settings["profile"]
            or settings["auth_type"]
            or (settings["client_id"] and settings["client_secret"])
        )
    )


def _settings() -> Dict[str, str]:
    return {
        "host": os.getenv("DATABRICKS_HOST", "").strip().rstrip("/"),
        "token": os.getenv("DATABRICKS_TOKEN", "").strip(),
        "client_id": os.getenv("DATABRICKS_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("DATABRICKS_CLIENT_SECRET", "").strip(),
        "auth_type": os.getenv("DATABRICKS_AUTH_TYPE", "").strip(),
        "profile": os.getenv("DATABRICKS_CONFIG_PROFILE", "").strip(),
        "warehouse_id": os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip(),
        "catalog": os.getenv("DATABRICKS_CATALOG", "main").strip(),
        "schema": os.getenv("DATABRICKS_SCHEMA", "default").strip(),
    }


def _quote(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def _table_fqn(table_name: str) -> str:
    settings = _settings()
    return ".".join(_quote(part) for part in (settings["catalog"], settings["schema"], table_name))


def _build_workspace_client() -> Any:
    if not DATABRICKS_AVAILABLE:
        raise RuntimeError(
            "databricks-sdk is not installed. Install it with: pip install databricks-sdk"
        )

    settings = _settings()
    if settings["token"]:
        return WorkspaceClient(host=settings["host"], token=settings["token"])
    if settings["client_id"] and settings["client_secret"]:
        return WorkspaceClient(
            host=settings["host"],
            client_id=settings["client_id"],
            client_secret=settings["client_secret"],
        )
    if settings["profile"]:
        return WorkspaceClient(profile=settings["profile"])
    return WorkspaceClient(host=settings["host"])


def _state_value(response: Any) -> str:
    state = getattr(getattr(response, "status", None), "state", None)
    return getattr(state, "value", str(state or "")).upper()


def _statement_error(response: Any) -> str:
    error = getattr(getattr(response, "status", None), "error", None)
    if not error:
        return "Unknown Databricks statement failure"
    return getattr(error, "message", "") or str(error)


def _resolve_warehouse_id(client: Any) -> str:
    settings = _settings()
    if settings["warehouse_id"]:
        return settings["warehouse_id"]

    warehouses = list(client.warehouses.list())
    if not warehouses:
        raise RuntimeError("No Databricks SQL warehouse available")

    for warehouse in warehouses:
        if getattr(warehouse, "state", "") == "RUNNING" and getattr(warehouse, "id", None):
            return str(warehouse.id)
    warehouse_id = getattr(warehouses[0], "id", None)
    if not warehouse_id:
        raise RuntimeError("Databricks SQL warehouse ID unavailable")
    return str(warehouse_id)


def _execute_statement(sql: str, *, timeout_sec: int = DATABRICKS_QUERY_TIMEOUT_SEC) -> Any:
    client = _build_workspace_client()
    settings = _settings()
    wait_timeout_sec = min(max(5, timeout_sec), 50)
    response = client.statement_execution.execute_statement(
        warehouse_id=_resolve_warehouse_id(client),
        statement=sql,
        catalog=settings["catalog"],
        schema=settings["schema"],
        wait_timeout=f"{wait_timeout_sec}s",
    )
    if _state_value(response) != "SUCCEEDED":
        raise RuntimeError(_statement_error(response))
    return response


def _extract_rows(response: Any) -> Dict[str, Any]:
    schema = getattr(getattr(response, "manifest", None), "schema", None)
    columns = [column.name.lower() for column in getattr(schema, "columns", [])]
    rows = getattr(getattr(response, "result", None), "data_array", None) or []
    row_count = getattr(getattr(response, "result", None), "row_count", None)
    if row_count is None:
        row_count = getattr(getattr(response, "manifest", None), "total_row_count", None)
    if row_count is None:
        row_count = len(rows)
    return {
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in rows],
        "row_count": int(row_count),
        "statement_id": getattr(response, "statement_id", None),
    }


def execute_databricks_rows(
    sql: str,
    *,
    timeout_sec: int = DATABRICKS_QUERY_TIMEOUT_SEC,
    max_rows: int = 1000,
) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    response = _execute_statement(sql, timeout_sec=timeout_sec)
    extracted = _extract_rows(response)
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        **extracted,
        "rows": extracted["rows"][:max_rows],
        "elapsed_ms": elapsed_ms,
    }


def execute_databricks_query(
    sql: str,
    *,
    timeout_sec: int = DATABRICKS_QUERY_TIMEOUT_SEC,
    max_rows: int = 500,
) -> Dict[str, Any]:
    result = execute_databricks_rows(sql, timeout_sec=timeout_sec, max_rows=max_rows)
    preview = result["rows"][:5]
    return {
        "row_count": result["row_count"],
        "preview": preview,
        "elapsed_ms": result["elapsed_ms"],
        "adapter_name": "databricks-live",
        "execution_mode": "databricks-live",
        "statement_id": result.get("statement_id"),
    }


def run_databricks_scalar_query(sql: str) -> int:
    result = execute_databricks_rows(sql, max_rows=1)
    if not result["rows"]:
        return 0
    first_row = result["rows"][0]
    if not first_row:
        return 0
    value = next(iter(first_row.values()))
    if value in (None, ""):
        return 0
    return int(float(value))


def fetch_databricks_date_window() -> Dict[str, Optional[str]]:
    result = execute_databricks_rows(
        f"SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM {_table_fqn('sales')}",
        max_rows=1,
    )
    row = result["rows"][0] if result["rows"] else {}
    return {
        "min_date": row.get("min_date"),
        "max_date": row.get("max_date"),
    }


def _table_names() -> List[str]:
    settings = _settings()
    result = execute_databricks_rows(
        f"SHOW TABLES IN {_quote(settings['catalog'])}.{_quote(settings['schema'])}",
        max_rows=200,
    )
    names: List[str] = []
    for row in result["rows"]:
        table_name = row.get("tablename") or row.get("table_name") or row.get("tablename")
        if table_name:
            names.append(str(table_name))
    return names


def build_databricks_table_profiles() -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for table_name in _table_names():
        count_result = execute_databricks_rows(
            f"SELECT COUNT(*) AS row_count FROM {_table_fqn(table_name)}",
            max_rows=1,
        )
        describe_result = execute_databricks_rows(
            f"DESCRIBE TABLE {_table_fqn(table_name)}",
            max_rows=500,
        )
        columns = [
            str(row.get("col_name"))
            for row in describe_result["rows"]
            if row.get("col_name") and not str(row.get("col_name")).startswith("#")
        ]
        row_count = 0
        if count_result["rows"]:
            row_count = int(float(count_result["rows"][0].get("row_count", 0) or 0))
        profiles.append(
            {
                "table": table_name,
                "row_count": row_count,
                "column_count": len(columns),
                "columns": columns,
            }
        )
    return profiles


def get_databricks_schema() -> str:
    parts: List[str] = []
    for table_name in _table_names():
        describe_result = execute_databricks_rows(
            f"DESCRIBE TABLE {_table_fqn(table_name)}",
            max_rows=500,
        )
        columns = [
            f"{row.get('col_name')} {row.get('data_type')}"
            for row in describe_result["rows"]
            if row.get("col_name") and not str(row.get("col_name")).startswith("#")
        ]
        parts.append(f"Table: {table_name}\nColumns: {', '.join(columns)}\n")
    return "\n".join(parts)


def seed_demo_tables_from_sqlite(
    sqlite_db_path: str | Path, *, batch_size: int = 250
) -> Dict[str, int]:
    db_path = Path(sqlite_db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    settings = _settings()
    catalog_schema = f"{_quote(settings['catalog'])}.{_quote(settings['schema'])}"
    _execute_statement(f"CREATE SCHEMA IF NOT EXISTS {catalog_schema}")
    _execute_statement(
        f"""
        CREATE OR REPLACE TABLE {_table_fqn("products")} (
            product_id INT,
            product_name STRING,
            category STRING,
            unit_price DOUBLE,
            margin_percentage DOUBLE
        ) USING DELTA
        """
    )
    _execute_statement(
        f"""
        CREATE OR REPLACE TABLE {_table_fqn("regions")} (
            region_id INT,
            region_name STRING,
            manager STRING
        ) USING DELTA
        """
    )
    _execute_statement(
        f"""
        CREATE OR REPLACE TABLE {_table_fqn("sales")} (
            transaction_id STRING,
            date DATE,
            product_id INT,
            region_id INT,
            quantity INT,
            discount_applied DOUBLE,
            gross_revenue DOUBLE,
            net_revenue DOUBLE,
            profit DOUBLE
        ) USING DELTA
        """
    )

    counts: Dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for table_name in ("products", "regions", "sales"):
            rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table_name}").fetchall()]
            counts[table_name] = len(rows)
            for index in range(0, len(rows), batch_size):
                chunk = rows[index : index + batch_size]
                values_sql: List[str] = []
                for row in chunk:
                    serialized: List[str] = []
                    for value in row.values():
                        if value is None:
                            serialized.append("NULL")
                        elif isinstance(value, str):
                            serialized.append("'" + value.replace("'", "''") + "'")
                        else:
                            serialized.append(str(value))
                    values_sql.append("(" + ", ".join(serialized) + ")")
                columns_sql = ", ".join(_quote(column) for column in chunk[0].keys())
                _execute_statement(
                    f"INSERT INTO {_table_fqn(table_name)} ({columns_sql}) VALUES {', '.join(values_sql)}",
                    timeout_sec=max(DATABRICKS_QUERY_TIMEOUT_SEC, 180),
                )
    return counts
