from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import sqlite3
import os


@dataclass(frozen=True)
class WarehouseAdapterContract:
    name: str
    status: str
    role: str
    sql_dialect: str
    execution_mode: str
    capabilities: List[str]
    backing_store: str
    review_note: str

    def to_dict(self) -> Dict[str, Any]:
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


class WarehouseAdapter:
    contract: WarehouseAdapterContract

    def __init__(self, contract: WarehouseAdapterContract):
        self.contract = contract

    def describe(self) -> Dict[str, Any]:
        return self.contract.to_dict()

    def prompt_sql_target(self) -> str:
        return self.contract.sql_dialect

    def prompt_execution_note(self) -> str:
        return self.contract.review_note

    def get_schema(self, db_path: Path) -> str:
        raise NotImplementedError

    def run_scalar_query(self, sql: str, db_path: Path) -> int:
        raise NotImplementedError

    def fetch_date_window(self, db_path: Path) -> Dict[str, Optional[str]]:
        raise NotImplementedError

    def build_table_profiles(self, db_path: Path) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def execute_sql_preview(self, sql: str, db_path: Path) -> Dict[str, Any]:
        raise NotImplementedError


_BLOCKED_SQL_KEYWORDS = {"DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE"}


def _validate_sql_readonly(sql: str) -> None:
    """Reject DDL/DML statements to enforce read-only query execution."""
    normalized = sql.strip().rstrip(";").upper()
    # Check the leading keyword of each statement (handles multi-statement strings)
    for statement in normalized.split(";"):
        first_word = statement.strip().split()[0] if statement.strip() else ""
        if first_word in _BLOCKED_SQL_KEYWORDS:
            raise ValueError(
                f"Blocked SQL statement: '{first_word}' operations are not allowed. "
                "Only SELECT queries are permitted."
            )


class SqliteWarehouseAdapter(WarehouseAdapter):
    def get_schema(self, db_path: Path) -> str:
        if not db_path.exists():
            return ""
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
        schema = ""
        for table, ddl in tables:
            schema += f"Table: {table}\nDDL: {ddl}\n\n"
        return schema

    def run_scalar_query(self, sql: str, db_path: Path) -> int:
        _validate_sql_readonly(sql)
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    def fetch_date_window(self, db_path: Path) -> Dict[str, Optional[str]]:
        if not db_path.exists():
            return {"min_date": None, "max_date": None}
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MIN(date), MAX(date) FROM sales")
            min_date, max_date = cursor.fetchone() or (None, None)
        return {"min_date": min_date, "max_date": max_date}

    def build_table_profiles(self, db_path: Path) -> List[Dict[str, Any]]:
        if not db_path.exists():
            return []

        profiles: List[Dict[str, Any]] = []
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                row_count = int(cursor.fetchone()[0] or 0)
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
        _validate_sql_readonly(sql)
        started_at = datetime.now(timezone.utc)
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(sql, conn)
        elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        rows = df.head(5).to_dict(orient="records")
        return {
            "row_count": int(len(df.index)),
            "preview": rows,
            "elapsed_ms": elapsed_ms,
            "adapter_name": self.contract.name,
            "execution_mode": self.contract.execution_mode,
        }


class ContractPreviewWarehouseAdapter(SqliteWarehouseAdapter):
    pass


def _build_contracts() -> Dict[str, WarehouseAdapter]:
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


WAREHOUSE_ADAPTER_REGISTRY = _build_contracts()


def get_warehouse_adapter_contracts() -> List[Dict[str, Any]]:
    return [adapter.describe() for adapter in WAREHOUSE_ADAPTER_REGISTRY.values()]


def get_active_warehouse_adapter() -> WarehouseAdapter:
    requested = str(os.getenv("NEXUS_HIVE_WAREHOUSE_ADAPTER", "sqlite-demo")).strip() or "sqlite-demo"
    return WAREHOUSE_ADAPTER_REGISTRY.get(requested, WAREHOUSE_ADAPTER_REGISTRY["sqlite-demo"])
