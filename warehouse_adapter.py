"""
Warehouse adapter layer for Nexus-Hive.

Provides a pluggable adapter pattern for SQL execution against different
warehouse backends (SQLite local, Snowflake contract preview, Databricks
contract preview). Each adapter implements schema introspection, read-only
SQL execution, and data profiling.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import os
import pandas as pd

from exceptions import SQLValidationError
from snowflake_adapter import (
    SNOWFLAKE_AVAILABLE,
    build_snowflake_table_profiles,
    execute_snowflake_query,
    fetch_snowflake_date_window,
    get_snowflake_schema,
    run_snowflake_scalar_query,
    snowflake_configured,
)
from databricks_adapter import (
    DATABRICKS_AVAILABLE,
    build_databricks_table_profiles,
    databricks_configured,
    execute_databricks_query,
    fetch_databricks_date_window,
    get_databricks_schema,
    run_databricks_scalar_query,
)

_logger = logging.getLogger("nexus_hive.warehouse_adapter")

# ---------------------------------------------------------------------------
# Adapter contract (immutable descriptor)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WarehouseAdapterContract:
    """Immutable descriptor for a warehouse adapter's capabilities and posture.

    Attributes:
        name: Unique adapter identifier (e.g., 'sqlite-demo').
        status: Lifecycle status ('active' or 'planned').
        role: Human-readable description of the adapter's purpose.
        sql_dialect: SQL dialect supported by this adapter.
        execution_mode: How queries are executed ('local-sqlite', 'contract-preview').
        capabilities: List of supported feature strings.
        backing_store: Description of the underlying data store.
        review_note: Note about the adapter's limitations.
    """

    name: str
    status: str
    role: str
    sql_dialect: str
    execution_mode: str
    capabilities: List[str]
    backing_store: str
    review_note: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the contract to a plain dictionary.

        Returns:
            A dictionary representation of all contract fields.
        """
        return {
            "name": self.name,
            "status": self.status,
            "role": self.role,
            "sql_dialect": self.sql_dialect,
            "execution_mode": self.execution_mode,
            "capabilities": self.capabilities,
            "backing_store": self.backing_store,
            "review_note": self.review_note,
        }


# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------


class WarehouseAdapter:
    """Base warehouse adapter defining the interface for SQL execution backends.

    Subclasses must implement schema introspection, query execution, and
    profiling methods. The base class provides contract description and
    prompt-generation helpers.
    """

    contract: WarehouseAdapterContract

    def __init__(self, contract: WarehouseAdapterContract) -> None:
        """Initialize the adapter with a contract descriptor.

        Args:
            contract: Immutable contract describing this adapter's capabilities.
        """
        self.contract = contract

    def describe(self) -> Dict[str, Any]:
        """Return a dictionary description of this adapter's contract.

        Returns:
            The serialized adapter contract.
        """
        return self.contract.to_dict()

    def prompt_sql_target(self) -> str:
        """Return the SQL dialect string for LLM prompt construction.

        Returns:
            The SQL dialect name (e.g., 'SQLite', 'Snowflake SQL').
        """
        return self.contract.sql_dialect

    def prompt_execution_note(self) -> str:
        """Return a reviewer note for LLM prompt construction.

        Returns:
            A human-readable note about execution posture.
        """
        return self.contract.review_note

    def get_schema(self, db_path: Path) -> str:
        """Retrieve the database schema DDL text.

        Args:
            db_path: Path to the database file.

        Returns:
            Schema DDL as a string.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError

    def run_scalar_query(self, sql: str, db_path: Path) -> int:
        """Execute a SQL query that returns a single integer scalar.

        Args:
            sql: The SQL query to execute.
            db_path: Path to the database file.

        Returns:
            The integer result of the scalar query.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError

    def fetch_date_window(self, db_path: Path) -> Dict[str, Optional[str]]:
        """Retrieve the min and max date from the sales table.

        Args:
            db_path: Path to the database file.

        Returns:
            Dictionary with 'min_date' and 'max_date' string values.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError

    def build_table_profiles(self, db_path: Path) -> List[Dict[str, Any]]:
        """Build row-count and column profiles for all tables.

        Args:
            db_path: Path to the database file.

        Returns:
            A list of profile dictionaries, one per table.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError

    def execute_sql_preview(self, sql: str, db_path: Path) -> Dict[str, Any]:
        """Execute a SQL query and return a preview of results.

        Args:
            sql: The SQL query to execute.
            db_path: Path to the database file.

        Returns:
            Dictionary with row_count, preview rows, elapsed_ms, and adapter info.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------

_BLOCKED_SQL_KEYWORDS: Set[str] = {
    "DROP",
    "DELETE",
    "INSERT",
    "UPDATE",
    "ALTER",
    "CREATE",
    "TRUNCATE",
}
_ALLOWED_FIRST_KEYWORDS: Set[str] = {"SELECT", "WITH", "EXPLAIN"}


def _strip_sql_comments_and_strings(sql: str) -> str:
    """Remove SQL comments and string literals so keyword checks cannot be bypassed.

    Strips block comments, single-line comments, single-quoted strings,
    and double-quoted identifiers from the SQL text.

    Args:
        sql: Raw SQL string.

    Returns:
        Cleaned SQL with comments and literals replaced.
    """
    # Remove block comments (/* ... */)
    cleaned: str = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Remove single-line comments (-- ...)
    cleaned = re.sub(r"--[^\n]*", " ", cleaned)
    # Remove single-quoted string literals ('...')
    cleaned = re.sub(r"'(?:[^'\\]|\\.)*'", "''", cleaned)
    # Remove double-quoted identifiers ("...")
    cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cleaned)
    return cleaned


def _validate_sql_readonly(sql: str) -> None:
    """Reject DDL/DML statements to enforce read-only query execution.

    Uses a whitelist approach: only SELECT/WITH/EXPLAIN statements are allowed.
    Comments and string literals are stripped before validation to prevent bypass.

    Args:
        sql: The SQL statement to validate.

    Raises:
        SQLValidationError: If the SQL contains write operations or blocked keywords.
    """
    stripped: str = sql.strip()
    if not stripped:
        raise SQLValidationError(
            "Empty SQL statement is not allowed.",
            sql=sql,
            violation_type="empty_sql",
        )

    cleaned: str = _strip_sql_comments_and_strings(stripped).strip().rstrip(";")

    for statement in cleaned.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        first_word: str = statement.split()[0].upper() if statement.split() else ""

        if first_word not in _ALLOWED_FIRST_KEYWORDS:
            raise SQLValidationError(
                f"Blocked SQL statement: '{first_word}' operations are not allowed. "
                "Only SELECT queries are permitted.",
                sql=sql,
                violation_type="blocked_first_keyword",
            )

        upper_statement: str = statement.upper()
        for keyword in _BLOCKED_SQL_KEYWORDS:
            if re.search(r"\b" + keyword + r"\b", upper_statement):
                raise SQLValidationError(
                    f"Blocked SQL keyword '{keyword}' found in statement. "
                    "Only read-only SELECT queries are permitted.",
                    sql=sql,
                    violation_type="blocked_keyword",
                )


def validate_sql_safety(sql: str) -> None:
    """Public SQL validation entry point for pre-execution safety checks.

    Validates that the SQL is non-empty, read-only, and free of blocked keywords.
    This function is intended to be called before any SQL execution.

    Args:
        sql: The SQL statement to validate.

    Raises:
        SQLValidationError: If the SQL fails any safety check.
    """
    _logger.debug("Validating SQL safety: %s", sql[:100])
    _validate_sql_readonly(sql)
    _logger.debug("SQL validation passed")


# ---------------------------------------------------------------------------
# SQLite adapter
# ---------------------------------------------------------------------------


class SqliteWarehouseAdapter(WarehouseAdapter):
    """Warehouse adapter for local SQLite database execution.

    Provides full read-only SQL execution, schema introspection, and
    data profiling against a local SQLite database file.
    """

    def get_schema(self, db_path: Path) -> str:
        """Retrieve the SQLite database schema DDL.

        Args:
            db_path: Path to the SQLite database file.

        Returns:
            Concatenated DDL for all tables, or empty string if DB does not exist.
        """
        if not db_path.exists():
            return ""
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
        schema: str = ""
        for table, ddl in tables:
            schema += f"Table: {table}\nDDL: {ddl}\n\n"
        return schema

    def run_scalar_query(self, sql: str, db_path: Path) -> int:
        """Execute a SQL query that returns a single integer scalar.

        Args:
            sql: The SQL query (must be read-only).
            db_path: Path to the SQLite database file.

        Returns:
            The integer result, or 0 if the database does not exist.

        Raises:
            SQLValidationError: If the SQL contains write operations.
        """
        _validate_sql_readonly(sql)
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    def fetch_date_window(self, db_path: Path) -> Dict[str, Optional[str]]:
        """Retrieve the date range from the sales table.

        Args:
            db_path: Path to the SQLite database file.

        Returns:
            Dictionary with 'min_date' and 'max_date' strings.
        """
        if not db_path.exists():
            return {"min_date": None, "max_date": None}
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MIN(date), MAX(date) FROM sales")
            min_date, max_date = cursor.fetchone() or (None, None)
        return {"min_date": min_date, "max_date": max_date}

    def build_table_profiles(self, db_path: Path) -> List[Dict[str, Any]]:
        """Build row-count and column profiles for all user tables.

        Args:
            db_path: Path to the SQLite database file.

        Returns:
            A list of profile dictionaries with table, row_count, column_count, columns.
        """
        if not db_path.exists():
            return []

        profiles: List[Dict[str, Any]] = []
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            tables: List[str] = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                row_count: int = int(cursor.fetchone()[0] or 0)
                cursor.execute(f'PRAGMA table_info("{table}")')
                columns = cursor.fetchall()
                profiles.append(
                    {
                        "table": table,
                        "row_count": row_count,
                        "column_count": len(columns),
                        "columns": [column[1] for column in columns],
                    }
                )
        return profiles

    def execute_sql_preview(self, sql: str, db_path: Path) -> Dict[str, Any]:
        """Execute a SQL query and return a preview of the first 5 rows.

        Args:
            sql: The SQL query to execute (must be read-only).
            db_path: Path to the SQLite database file.

        Returns:
            Dictionary with row_count, preview, elapsed_ms, adapter_name,
            and execution_mode.

        Raises:
            SQLValidationError: If the SQL contains write operations.
        """
        _validate_sql_readonly(sql)
        _logger.info(
            "Executing SQL preview via %s",
            self.contract.name,
            extra={"extra_fields": {"sql_preview": sql[:200]}},
        )
        started_at: datetime = datetime.now(timezone.utc)
        with sqlite3.connect(db_path) as conn:
            df: pd.DataFrame = pd.read_sql_query(sql, conn)
        elapsed_ms: int = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        rows: List[Dict[str, Any]] = df.head(5).to_dict(orient="records")
        _logger.info(
            "SQL preview complete: %d rows in %dms",
            len(df.index),
            elapsed_ms,
        )
        return {
            "row_count": int(len(df.index)),
            "preview": rows,
            "elapsed_ms": elapsed_ms,
            "adapter_name": self.contract.name,
            "execution_mode": self.contract.execution_mode,
        }


class ContractPreviewWarehouseAdapter(SqliteWarehouseAdapter):
    """Warehouse adapter for Snowflake/Databricks contract previews.

    Inherits SQLite execution to provide deterministic previews while
    maintaining the contract metadata for the target warehouse platform.
    """

    pass


class LiveSnowflakeWarehouseAdapter(WarehouseAdapter):
    """Warehouse adapter backed by a live Snowflake connection."""

    def get_schema(self, db_path: Path) -> str:
        return get_snowflake_schema()

    def run_scalar_query(self, sql: str, db_path: Path) -> int:
        validate_sql_safety(sql)
        return run_snowflake_scalar_query(sql)

    def fetch_date_window(self, db_path: Path) -> Dict[str, Optional[str]]:
        return fetch_snowflake_date_window()

    def build_table_profiles(self, db_path: Path) -> List[Dict[str, Any]]:
        return build_snowflake_table_profiles()

    def execute_sql_preview(self, sql: str, db_path: Path) -> Dict[str, Any]:
        validate_sql_safety(sql)
        return execute_snowflake_query(sql)


class LiveDatabricksWarehouseAdapter(WarehouseAdapter):
    """Warehouse adapter backed by a live Databricks SQL warehouse."""

    def get_schema(self, db_path: Path) -> str:
        return get_databricks_schema()

    def run_scalar_query(self, sql: str, db_path: Path) -> int:
        validate_sql_safety(sql)
        return run_databricks_scalar_query(sql)

    def fetch_date_window(self, db_path: Path) -> Dict[str, Optional[str]]:
        return fetch_databricks_date_window()

    def build_table_profiles(self, db_path: Path) -> List[Dict[str, Any]]:
        return build_databricks_table_profiles()

    def execute_sql_preview(self, sql: str, db_path: Path) -> Dict[str, Any]:
        validate_sql_safety(sql)
        return execute_databricks_query(sql)


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------


def _build_contracts() -> Dict[str, WarehouseAdapter]:
    """Build and return the warehouse adapter registry.

    Creates adapters for SQLite (active), Snowflake (planned), and
    Databricks (planned) with their respective contract metadata.

    Returns:
        A dictionary mapping adapter names to adapter instances.
    """
    sqlite_adapter = SqliteWarehouseAdapter(
        WarehouseAdapterContract(
            name="sqlite-demo",
            status="active",
            role="Local warehouse stand-in for governed analytics review",
            sql_dialect="SQLite",
            execution_mode="local-sqlite",
            capabilities=[
                "read-only SQL execution",
                "pandas result preview",
                "local schema introspection",
                "query tag preview",
            ],
            backing_store="local sqlite database",
            review_note="All governed execution currently runs against the local SQLite warehouse mirror.",
        )
    )
    snowflake_adapter = ContractPreviewWarehouseAdapter(
        WarehouseAdapterContract(
            name="snowflake-sql-contract",
            status="planned",
            role="Parameterized warehouse adapter contract for Snowflake-style governed SQL warehouses",
            sql_dialect="Snowflake SQL",
            execution_mode="contract-preview",
            capabilities=[
                "query tagging",
                "role simulation",
                "audit sink integration",
                "statement id capture",
            ],
            backing_store="local SQLite mirror for contract previews",
            review_note="Snowflake contract previews use the local SQLite mirror for deterministic review until a live connector is configured.",
        )
    )
    databricks_adapter = ContractPreviewWarehouseAdapter(
        WarehouseAdapterContract(
            name="databricks-sql-contract",
            status="planned",
            role="Lakehouse SQL adapter contract for medallion-style modeled tables",
            sql_dialect="Databricks SQL",
            execution_mode="contract-preview",
            capabilities=[
                "modeled view registration",
                "freshness metadata",
                "quality gate attachment",
                "query tagging",
            ],
            backing_store="local SQLite mirror for contract previews",
            review_note="Databricks contract previews use the local SQLite mirror for deterministic review until a live SQL warehouse is configured.",
        )
    )
    return {
        sqlite_adapter.contract.name: sqlite_adapter,
        snowflake_adapter.contract.name: snowflake_adapter,
        databricks_adapter.contract.name: databricks_adapter,
    }


WAREHOUSE_ADAPTER_REGISTRY: Dict[str, WarehouseAdapter] = _build_contracts()


def get_warehouse_adapter_contracts() -> List[Dict[str, Any]]:
    """Return a list of all registered warehouse adapter contract descriptions.

    Returns:
        List of adapter contract dictionaries.
    """
    return [adapter.describe() for adapter in WAREHOUSE_ADAPTER_REGISTRY.values()]


def get_active_warehouse_adapter() -> WarehouseAdapter:
    """Return the currently active warehouse adapter based on environment configuration.

    Falls back to 'sqlite-demo' if the requested adapter is not registered.

    Returns:
        The active warehouse adapter instance.
    """
    requested: str = (
        str(os.getenv("NEXUS_HIVE_WAREHOUSE_ADAPTER", "sqlite-demo")).strip() or "sqlite-demo"
    )
    if requested == "snowflake-sql-contract" and snowflake_configured() and SNOWFLAKE_AVAILABLE:
        return LiveSnowflakeWarehouseAdapter(
            WarehouseAdapterContract(
                name="snowflake-sql-contract",
                status="active",
                role="Live Snowflake execution path for governed SQL review",
                sql_dialect="Snowflake SQL",
                execution_mode="snowflake-live",
                capabilities=[
                    "query tagging",
                    "role simulation",
                    "audit sink integration",
                    "statement id capture",
                    "live schema introspection",
                    "live preview execution",
                ],
                backing_store="live Snowflake warehouse",
                review_note="Snowflake contract previews are upgraded to live read-only execution when Snowflake credentials are configured.",
            )
        )
    if requested == "databricks-sql-contract" and databricks_configured() and DATABRICKS_AVAILABLE:
        return LiveDatabricksWarehouseAdapter(
            WarehouseAdapterContract(
                name="databricks-sql-contract",
                status="active",
                role="Live Databricks SQL execution path for governed lakehouse review",
                sql_dialect="Databricks SQL",
                execution_mode="databricks-live",
                capabilities=[
                    "modeled view registration",
                    "freshness metadata",
                    "quality gate attachment",
                    "query tagging",
                    "live schema introspection",
                    "live preview execution",
                ],
                backing_store="live Databricks SQL warehouse",
                review_note="Databricks contract previews are upgraded to live read-only execution when Databricks unified auth and a SQL warehouse are configured.",
            )
        )
    adapter = WAREHOUSE_ADAPTER_REGISTRY.get(requested, WAREHOUSE_ADAPTER_REGISTRY["sqlite-demo"])
    _logger.debug("Active warehouse adapter: %s", adapter.contract.name)
    return adapter
