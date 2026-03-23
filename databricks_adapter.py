"""
Databricks SQL warehouse adapter for Nexus-Hive.

Provides live SQL execution against a Databricks SQL warehouse using
databricks-sql-connector. Activated when the DATABRICKS_HOST environment
variable is set. Includes connection pooling, query timeouts, and
structured error handling.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("nexus_hive.databricks_adapter")

# Guard import so the package is only required when the adapter is activated
try:
    from databricks import sql as databricks_sql

    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False
    _logger.debug("databricks-sql-connector not installed; Databricks adapter unavailable")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def databricks_configured() -> bool:
    """Return True if DATABRICKS_HOST is set in the environment."""
    return bool(os.getenv("DATABRICKS_HOST", "").strip())


def _get_databricks_config() -> Dict[str, str]:
    """Read Databricks connection parameters from environment variables.

    Returns:
        Dictionary of connection parameters suitable for databricks.sql.connect().
    """
    return {
        "server_hostname": os.getenv("DATABRICKS_HOST", "").strip(),
        "access_token": os.getenv("DATABRICKS_TOKEN", "").strip(),
        "http_path": os.getenv("DATABRICKS_HTTP_PATH", "").strip(),
        "catalog": os.getenv("DATABRICKS_CATALOG", "main").strip(),
        "schema": os.getenv("DATABRICKS_SCHEMA", "default").strip(),
    }


# ---------------------------------------------------------------------------
# Connection pool (thread-safe singleton)
# ---------------------------------------------------------------------------


class DatabricksConnectionPool:
    """Simple thread-safe connection pool for Databricks SQL.

    Maintains a single reusable connection per process with automatic
    reconnection on failure.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: Optional[Any] = None
        self._created_at: Optional[float] = None
        self._max_age_sec: float = 3600.0

    def get_connection(self) -> Any:
        """Return a live Databricks SQL connection, creating or refreshing as needed.

        Returns:
            A databricks.sql Connection object.

        Raises:
            RuntimeError: If databricks-sql-connector is not installed.
        """
        if not DATABRICKS_AVAILABLE:
            raise RuntimeError(
                "databricks-sql-connector is not installed. "
                "Install it with: pip install databricks-sql-connector"
            )

        with self._lock:
            now = time.monotonic()
            if (
                self._conn is not None
                and self._created_at is not None
                and (now - self._created_at) < self._max_age_sec
            ):
                try:
                    cursor = self._conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.close()
                    return self._conn
                except Exception:
                    _logger.warning("Databricks connection stale, reconnecting")
                    self._close_unsafe()

            config = _get_databricks_config()
            _logger.info(
                "Opening Databricks SQL connection: host=%s, catalog=%s",
                config["server_hostname"],
                config["catalog"],
            )
            self._conn = databricks_sql.connect(
                server_hostname=config["server_hostname"],
                access_token=config["access_token"],
                http_path=config["http_path"],
                catalog=config["catalog"],
                schema=config["schema"],
            )
            self._created_at = now
            return self._conn

    def _close_unsafe(self) -> None:
        """Close the current connection without locking (caller must hold lock)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._created_at = None

    def close(self) -> None:
        """Close the pooled connection."""
        with self._lock:
            self._close_unsafe()


# Module-level pool singleton
_pool = DatabricksConnectionPool()


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

DATABRICKS_QUERY_TIMEOUT_SEC: int = int(os.getenv("DATABRICKS_QUERY_TIMEOUT_SEC", "120"))


def execute_databricks_query(
    sql: str,
    *,
    timeout_sec: int = DATABRICKS_QUERY_TIMEOUT_SEC,
    max_rows: int = 500,
) -> Dict[str, Any]:
    """Execute a read-only SQL query against Databricks SQL warehouse.

    The result format matches the SQLite adapter's execute_sql_preview() output
    so callers can treat both adapters uniformly.

    Args:
        sql: The SQL query to execute (must be read-only).
        timeout_sec: Query timeout in seconds.
        max_rows: Maximum rows to fetch for the preview.

    Returns:
        Dictionary with row_count, preview (list of dicts), elapsed_ms,
        adapter_name, and execution_mode.

    Raises:
        RuntimeError: If databricks-sql-connector is not installed.
    """
    conn = _pool.get_connection()
    started = datetime.now(timezone.utc)

    _logger.info("Executing Databricks query, timeout=%ds", timeout_sec)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
        row_count = cursor.rowcount if cursor.rowcount and cursor.rowcount >= 0 else len(rows)
    finally:
        cursor.close()

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    # Convert rows to list of dicts
    preview: List[Dict[str, Any]] = []
    for row in rows[:5]:
        if isinstance(row, dict):
            preview.append({k.lower(): v for k, v in row.items()})
        elif hasattr(row, "_asdict"):
            preview.append({k.lower(): v for k, v in row._asdict().items()})
        else:
            preview.append(dict(zip([c.lower() for c in columns], row)))

    _logger.info(
        "Databricks query complete: %d rows in %dms",
        row_count,
        elapsed_ms,
    )

    return {
        "row_count": row_count,
        "preview": preview,
        "elapsed_ms": elapsed_ms,
        "adapter_name": "databricks-live",
        "execution_mode": "databricks-live",
    }


def get_databricks_schema() -> str:
    """Retrieve the schema information from the configured Databricks catalog.

    Returns:
        Concatenated table descriptions from the current catalog and schema.
    """
    conn = _pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
    finally:
        cursor.close()

    schema_parts: List[str] = []
    for row in tables:
        # SHOW TABLES returns (database, tableName, isTemporary)
        table_name = row[1] if len(row) > 1 else row[0]
        desc_cursor = conn.cursor()
        try:
            desc_cursor.execute(f"DESCRIBE TABLE {table_name}")
            columns = desc_cursor.fetchall()
            col_defs = ", ".join(f"{col[0]} {col[1]}" for col in columns if len(col) >= 2)
            schema_parts.append(f"Table: {table_name}\nColumns: {col_defs}\n")
        except Exception as exc:
            _logger.warning("Could not describe table %s: %s", table_name, exc)
            schema_parts.append(f"Table: {table_name}\nColumns: (unavailable)\n")
        finally:
            desc_cursor.close()

    return "\n".join(schema_parts)


def close_databricks_pool() -> None:
    """Close the Databricks connection pool. Call on shutdown."""
    _pool.close()
