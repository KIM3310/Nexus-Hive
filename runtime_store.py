"""
Runtime event persistence for Nexus-Hive.

Provides append-only event storage (JSONL or SQLite backends) for runtime
events such as API requests, agent decisions, and governance actions.
Supports summary aggregation for operational dashboards.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("nexus_hive.runtime_store")


def resolve_runtime_store_path() -> Path:
    """Resolve the file path for the runtime event store.

    Uses the NEXUS_HIVE_RUNTIME_STORE_PATH environment variable if set,
    otherwise defaults to .runtime/nexus-hive-runtime-events.db in the
    current working directory.

    Returns:
        Resolved Path to the runtime store file.
    """
    configured: str = str(os.getenv("NEXUS_HIVE_RUNTIME_STORE_PATH", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".runtime" / "nexus-hive-runtime-events.db"


def resolve_runtime_store_backend(target: Path) -> str:
    """Determine the storage backend (jsonl or sqlite) for the runtime store.

    Uses the NEXUS_HIVE_RUNTIME_STORE_BACKEND environment variable if set,
    otherwise infers from the file extension.

    Args:
        target: Path to the runtime store file.

    Returns:
        Either 'jsonl' or 'sqlite'.
    """
    configured: str = str(
        os.getenv("NEXUS_HIVE_RUNTIME_STORE_BACKEND", "")
    ).strip().lower()
    if configured in {"jsonl", "sqlite"}:
        return configured
    return "jsonl" if target.suffix == ".jsonl" else "sqlite"


def ensure_sqlite_store(target: Path) -> sqlite3.Connection:
    """Create or open the SQLite runtime event store with required schema.

    Creates the parent directory, database file, table, and indexes if
    they do not already exist.

    Args:
        target: Path to the SQLite database file.

    Returns:
        An open sqlite3.Connection.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    connection: sqlite3.Connection = sqlite3.connect(target)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            request_id TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_events_at ON runtime_events(at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_events_event_type ON runtime_events(event_type)"
    )
    connection.commit()
    return connection


def append_runtime_event(event: dict[str, Any]) -> None:
    """Persist a runtime event to the configured backend.

    Supports both JSONL (append to file) and SQLite (insert row) backends.

    Args:
        event: Dictionary containing at minimum 'at', 'event_type', and 'status'.
    """
    target: Path = resolve_runtime_store_path()
    backend: str = resolve_runtime_store_backend(target)

    _logger.debug(
        "Appending runtime event: type=%s, status=%s",
        event.get("event_type", "unknown"),
        event.get("status", "unknown"),
    )

    if backend == "jsonl":
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"{json.dumps(event, ensure_ascii=True)}\n")
        return

    with ensure_sqlite_store(target) as connection:
        connection.execute(
            """
            INSERT INTO runtime_events (
                at,
                event_type,
                status,
                request_id,
                payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(event.get("at", "")),
                str(event.get("event_type", "unknown")),
                str(event.get("status", "unknown")),
                str(event.get("request_id") or ""),
                json.dumps(event, ensure_ascii=True),
            ),
        )
        connection.commit()


def build_runtime_store_summary(limit: int = 25) -> dict[str, Any]:
    """Build a summary of the runtime event store for dashboards.

    Aggregates event type counts, status counts, and returns the most
    recent events up to the specified limit.

    Args:
        limit: Maximum number of recent events to include.

    Returns:
        Dictionary with backend, path, counts, and recent event list.
    """
    target: Path = resolve_runtime_store_path()
    backend: str = resolve_runtime_store_backend(target)

    if backend == "jsonl":
        if not target.exists():
            return {
                "backend": "jsonl",
                "enabled": True,
                "path": str(target),
                "persisted_count": 0,
                "last_event_at": None,
                "event_type_counts": {},
                "status_counts": {},
                "recent_events": [],
            }

        lines: List[str] = [
            line.strip()
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        recent_events: List[Dict[str, Any]] = []
        for line in lines[-max(1, limit):]:
            try:
                recent_events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        event_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        last_event_at: str | None = None
        for event in recent_events:
            event_type: str = (
                str(event.get("event_type", "unknown")).strip() or "unknown"
            )
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
            status: str = str(event.get("status", "unknown")).strip() or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            at = event.get("at")
            if isinstance(at, str) and (last_event_at is None or at > last_event_at):
                last_event_at = at

        return {
            "backend": "jsonl",
            "enabled": True,
            "path": str(target),
            "persisted_count": len(lines),
            "last_event_at": last_event_at,
            "event_type_counts": event_type_counts,
            "status_counts": status_counts,
            "recent_events": recent_events,
        }

    # SQLite backend
    if not target.exists():
        with ensure_sqlite_store(target):
            pass

    with ensure_sqlite_store(target) as connection:
        count, last_event_at_db = connection.execute(
            "SELECT COUNT(*), MAX(at) FROM runtime_events"
        ).fetchone()
        event_type_counts_db: Dict[str, int] = {
            str(row[0]): int(row[1] or 0)
            for row in connection.execute(
                "SELECT event_type, COUNT(*) FROM runtime_events "
                "GROUP BY event_type ORDER BY event_type"
            ).fetchall()
        }
        status_counts_db: Dict[str, int] = {
            str(row[0]): int(row[1] or 0)
            for row in connection.execute(
                "SELECT status, COUNT(*) FROM runtime_events "
                "GROUP BY status ORDER BY status"
            ).fetchall()
        }
        rows = connection.execute(
            """
            SELECT payload_json
            FROM runtime_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        recent_events_db: List[Dict[str, Any]] = []
        for row in reversed(rows):
            try:
                recent_events_db.append(json.loads(str(row[0])))
            except json.JSONDecodeError:
                continue

    return {
        "backend": "sqlite",
        "enabled": True,
        "path": str(target),
        "persisted_count": int(count or 0),
        "last_event_at": last_event_at_db,
        "event_type_counts": event_type_counts_db,
        "status_counts": status_counts_db,
        "recent_events": recent_events_db,
    }
