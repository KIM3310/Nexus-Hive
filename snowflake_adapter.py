"""
Snowflake warehouse adapter for Nexus-Hive.

Provides live SQL execution against Snowflake using snowflake-connector-python.
Activated when the SNOWFLAKE_ACCOUNT environment variable is set. Includes
connection pooling, query timeouts, and structured error handling.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("nexus_hive.snowflake_adapter")

# Guard import so the package is only required when the adapter is activated
try:
    import snowflake.connector
    from snowflake.connector import DictCursor

    SNOWFLAKE_AVAILABLE = True
except ImportError:
    DictCursor = None
    SNOWFLAKE_AVAILABLE = False
    DictCursor = None  # type: ignore[assignment,misc]
    _logger.debug("snowflake-connector-python not installed; Snowflake adapter unavailable")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def snowflake_configured() -> bool:
    """Return True if SNOWFLAKE_ACCOUNT is set in the environment."""
    return bool(os.getenv("SNOWFLAKE_ACCOUNT", "").strip())


def _get_snowflake_config() -> Dict[str, Any]:
    """Read Snowflake connection parameters from environment variables.

    Returns:
        Dictionary of connection parameters suitable for snowflake.connector.connect().
    """
    config: Dict[str, Any] = {
        "account": os.getenv("SNOWFLAKE_ACCOUNT", "").strip(),
        "user": os.getenv("SNOWFLAKE_USER", "").strip(),
        "password": os.getenv("SNOWFLAKE_PASSWORD", "").strip(),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH").strip(),
        "database": os.getenv("SNOWFLAKE_DATABASE", "ANALYTICS").strip(),
        "schema": os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC").strip(),
        "login_timeout": 30,
        "network_timeout": 30,
        "client_session_keep_alive": True,
    }
    role = os.getenv("SNOWFLAKE_ROLE", "").strip()
    if role:
        config["role"] = role
    return config


# ---------------------------------------------------------------------------
# Connection pool (thread-safe singleton)
# ---------------------------------------------------------------------------


class SnowflakeConnectionPool:
    """Simple thread-safe connection pool for Snowflake.

    Maintains a single reusable connection per process with automatic
    reconnection on failure. Not intended for high-concurrency production
    use; a proper pool (e.g., via SQLAlchemy) should be used at scale.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: Optional[Any] = None
        self._created_at: Optional[float] = None
        self._max_age_sec: float = 3600.0  # Refresh connection every hour

    def get_connection(self) -> Any:
        """Return a live Snowflake connection, creating or refreshing as needed.

        Returns:
            A snowflake.connector connection object.

        Raises:
            RuntimeError: If snowflake-connector-python is not installed.
            snowflake.connector.Error: If connection fails.
        """
        if not SNOWFLAKE_AVAILABLE:
            raise RuntimeError(
                "snowflake-connector-python is not installed. "
                "Install it with: pip install snowflake-connector-python"
            )

        with self._lock:
            now = time.monotonic()
            if (
                self._conn is not None
                and self._created_at is not None
                and (now - self._created_at) < self._max_age_sec
            ):
                try:
                    # Verify the connection is still alive
                    self._conn.cursor().execute("SELECT 1")
                    return self._conn
                except Exception:
                    _logger.warning("Snowflake connection stale, reconnecting")
                    self._close_unsafe()

            config = _get_snowflake_config()
            _logger.info(
                "Opening Snowflake connection: account=%s, warehouse=%s, database=%s",
                config["account"],
                config["warehouse"],
                config["database"],
            )
            self._conn = snowflake.connector.connect(**config)
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
_pool = SnowflakeConnectionPool()


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

# Default query timeout in seconds
SNOWFLAKE_QUERY_TIMEOUT_SEC: int = int(os.getenv("SNOWFLAKE_QUERY_TIMEOUT_SEC", "120"))


def _open_cursor(conn: Any) -> Any:
    """Return a dict-style cursor when available, otherwise a plain cursor for mocked callers."""
    if DictCursor is None:
        return conn.cursor()
    return conn.cursor(DictCursor)


def execute_snowflake_query(
    sql: str,
    *,
    timeout_sec: int = SNOWFLAKE_QUERY_TIMEOUT_SEC,
    max_rows: int = 500,
) -> Dict[str, Any]:
    """Execute a read-only SQL query against Snowflake and return results.

    The result format matches the SQLite adapter's execute_sql_preview() output
    so callers can treat both adapters uniformly.

    Args:
        sql: The SQL query to execute (must be read-only).
        timeout_sec: Statement-level timeout in seconds.
        max_rows: Maximum rows to fetch for the preview.

    Returns:
        Dictionary with row_count, preview (list of dicts), elapsed_ms,
        adapter_name, and execution_mode.

    Raises:
        RuntimeError: If snowflake-connector-python is not installed.
        snowflake.connector.ProgrammingError: On SQL errors.
        snowflake.connector.DatabaseError: On connection errors.
    """
    conn = _pool.get_connection()
    started = datetime.now(timezone.utc)

    _logger.info("Executing Snowflake query, timeout=%ds", timeout_sec)
    cursor = _open_cursor(conn)
    try:
        # Set statement-level timeout
        cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {timeout_sec}")
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
        # Get total row count if available
        row_count = cursor.rowcount if cursor.rowcount is not None else len(rows)
        query_id = getattr(cursor, "sfqid", None)
    finally:
        cursor.close()

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    # Normalize row dicts (Snowflake returns uppercase column names by default)
    preview: List[Dict[str, Any]] = []
    for row in rows[:5]:
        if isinstance(row, dict):
            preview.append({k.lower(): v for k, v in row.items()})
        else:
            preview.append(dict(zip([c.lower() for c in columns], row)))

    _logger.info(
        "Snowflake query complete: %d rows in %dms",
        row_count,
        elapsed_ms,
    )

    return {
        "row_count": row_count,
        "preview": preview,
        "elapsed_ms": elapsed_ms,
        "adapter_name": "snowflake-live",
        "execution_mode": "snowflake-live",
        "query_id": query_id,
    }


def execute_snowflake_rows(
    sql: str,
    *,
    timeout_sec: int = SNOWFLAKE_QUERY_TIMEOUT_SEC,
    max_rows: int = 1000,
) -> Dict[str, Any]:
    """Execute SQL and return normalized rows and metadata."""
    conn = _pool.get_connection()
    started = datetime.now(timezone.utc)
    cursor = _open_cursor(conn)
    try:
        cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {timeout_sec}")
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
        row_count = cursor.rowcount if cursor.rowcount is not None else len(rows)
        query_id = getattr(cursor, "sfqid", None)
    finally:
        cursor.close()

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized_rows.append({k.lower(): v for k, v in row.items()})
        else:
            normalized_rows.append(dict(zip([c.lower() for c in columns], row)))

    return {
        "columns": [col.lower() for col in columns],
        "elapsed_ms": elapsed_ms,
        "query_id": query_id,
        "row_count": row_count,
        "rows": normalized_rows,
    }


def run_snowflake_scalar_query(sql: str) -> int:
    """Execute a scalar Snowflake query and return the first value as int."""
    result = execute_snowflake_rows(sql, max_rows=1)
    if not result["rows"]:
        return 0
    first_row = result["rows"][0]
    if not first_row:
        return 0
    value = next(iter(first_row.values()))
    return int(value or 0)


def fetch_snowflake_date_window() -> Dict[str, Optional[str]]:
    """Retrieve min and max sales date from the live Snowflake SALES table."""
    result = execute_snowflake_rows(
        "SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM sales",
        max_rows=1,
    )
    row = result["rows"][0] if result["rows"] else {}
    return {
        "min_date": str(row.get("min_date")) if row.get("min_date") is not None else None,
        "max_date": str(row.get("max_date")) if row.get("max_date") is not None else None,
    }


def build_snowflake_table_profiles() -> List[Dict[str, Any]]:
    """Build lightweight profiles for all base tables in the current Snowflake schema."""
    tables = execute_snowflake_rows(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = CURRENT_SCHEMA()
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        max_rows=100,
    )
    profiles: List[Dict[str, Any]] = []
    for item in tables["rows"]:
        table_name = str(item.get("table_name") or "").strip()
        if not table_name:
            continue
        row_count = run_snowflake_scalar_query(f"SELECT COUNT(*) AS row_count FROM {table_name}")
        columns = execute_snowflake_rows(
            f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = CURRENT_SCHEMA()
              AND table_name = '{table_name.upper()}'
            ORDER BY ordinal_position
            """,
            max_rows=200,
        )
        profiles.append(
            {
                "column_count": len(columns["rows"]),
                "columns": [str(col.get("column_name", "")).lower() for col in columns["rows"]],
                "row_count": row_count,
                "table": table_name.lower(),
            }
        )
    return profiles


def get_snowflake_schema() -> str:
    """Retrieve the schema DDL from the configured Snowflake database.

    Returns:
        Concatenated DDL for all tables in the current schema.
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
        table_name = row[1]  # name is the second column in SHOW TABLES
        ddl_cursor = conn.cursor()
        try:
            ddl_cursor.execute(f"SELECT GET_DDL('TABLE', '{table_name}')")
            ddl_row = ddl_cursor.fetchone()
            if ddl_row:
                schema_parts.append(f"Table: {table_name}\nDDL: {ddl_row[0]}\n")
        except Exception as exc:
            _logger.warning("Could not get DDL for table %s: %s", table_name, exc)
            schema_parts.append(f"Table: {table_name}\nDDL: (unavailable)\n")
        finally:
            ddl_cursor.close()

    return "\n".join(schema_parts)


def close_snowflake_pool() -> None:
    """Close the Snowflake connection pool. Call on shutdown."""
    _pool.close()
