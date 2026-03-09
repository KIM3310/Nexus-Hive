from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def resolve_runtime_store_path() -> Path:
    configured = str(os.getenv("NEXUS_HIVE_RUNTIME_STORE_PATH", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".runtime" / "nexus-hive-runtime-events.jsonl"


def append_runtime_event(event: dict[str, Any]) -> None:
    target = resolve_runtime_store_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"{json.dumps(event, ensure_ascii=True)}\n")


def build_runtime_store_summary(limit: int = 25) -> dict[str, Any]:
    target = resolve_runtime_store_path()
    if not target.exists():
        return {
            "enabled": True,
            "path": str(target),
            "persisted_count": 0,
            "last_event_at": None,
            "event_type_counts": {},
            "status_counts": {},
            "recent_events": [],
        }

    lines = [line.strip() for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    recent_events = []
    for line in lines[-max(1, limit) :]:
        try:
            recent_events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    event_type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    last_event_at: str | None = None
    for event in recent_events:
        event_type = str(event.get("event_type", "unknown")).strip() or "unknown"
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        status = str(event.get("status", "unknown")).strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        at = event.get("at")
        if isinstance(at, str) and (last_event_at is None or at > last_event_at):
            last_event_at = at

    return {
        "enabled": True,
        "path": str(target),
        "persisted_count": len(lines),
        "last_event_at": last_event_at,
        "event_type_counts": event_type_counts,
        "status_counts": status_counts,
        "recent_events": recent_events,
    }
