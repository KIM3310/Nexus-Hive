"""Memory and Context Manager with short-term and long-term storage.

Provides:
- Short-term memory: per-request context that lives during a single agent run
- Long-term memory: persistent knowledge that survives across runs
- Conversation history tracking
- Semantic retrieval (placeholder for vector DB integration)
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_PATH = Path("data/agent_memory.json")


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    ttl_seconds: float | None = None  # None = never expires

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return (time.time() - self.created_at) > self.ttl_seconds

    def access(self) -> Any:
        self.access_count += 1
        return self.value


class MemoryManager:
    """Dual-layer memory system for agent context management."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self._short_term: dict[str, dict[str, MemoryEntry]] = defaultdict(dict)
        self._long_term: dict[str, MemoryEntry] = {}
        self._conversation_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._persist_path = persist_path

        if persist_path and persist_path.exists():
            self._load()

    # --- Short-term memory (per-request) ---

    def store_short_term(
        self,
        request_id: str,
        key: str,
        value: Any,
        ttl_seconds: float = 3600.0,
    ) -> None:
        """Store a value in short-term memory for a specific request."""
        self._short_term[request_id][key] = MemoryEntry(
            key=key, value=value, ttl_seconds=ttl_seconds,
        )

    def get_short_term(self, request_id: str, key: str) -> Any | None:
        """Retrieve a value from short-term memory."""
        entry = self._short_term.get(request_id, {}).get(key)
        if entry is None or entry.is_expired:
            return None
        return entry.access()

    def get_request_context(self, request_id: str) -> dict[str, Any]:
        """Get all non-expired short-term memory for a request."""
        entries = self._short_term.get(request_id, {})
        return {
            k: e.value for k, e in entries.items() if not e.is_expired
        }

    def clear_request(self, request_id: str) -> None:
        """Clear all short-term memory for a request."""
        self._short_term.pop(request_id, None)
        self._conversation_history.pop(request_id, None)

    # --- Long-term memory (persistent) ---

    def store_long_term(self, key: str, value: Any) -> None:
        """Store a value in long-term memory (persists across runs)."""
        self._long_term[key] = MemoryEntry(key=key, value=value)
        if self._persist_path:
            self._save()

    def get_long_term(self, key: str) -> Any | None:
        """Retrieve a value from long-term memory."""
        entry = self._long_term.get(key)
        if entry is None:
            return None
        return entry.access()

    def search_long_term(self, prefix: str) -> dict[str, Any]:
        """Search long-term memory by key prefix."""
        return {
            k: e.value for k, e in self._long_term.items()
            if k.startswith(prefix)
        }

    # --- Conversation history ---

    def add_message(
        self,
        request_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a message to conversation history."""
        self._conversation_history[request_id].append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
            **(metadata or {}),
        })

    def get_history(self, request_id: str, last_n: int | None = None) -> list[dict[str, Any]]:
        """Get conversation history for a request."""
        history = self._conversation_history.get(request_id, [])
        if last_n is not None:
            return history[-last_n:]
        return history

    # --- Persistence ---

    def _save(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            k: {"key": e.key, "value": e.value, "created_at": e.created_at}
            for k, e in self._long_term.items()
        }
        try:
            self._persist_path.write_text(json.dumps(data, default=str, indent=2))
        except (OSError, TypeError) as e:
            logger.warning(f"Failed to persist memory: {e}")

    def _load(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            for key, entry in data.items():
                self._long_term[key] = MemoryEntry(
                    key=entry["key"],
                    value=entry["value"],
                    created_at=entry.get("created_at", time.time()),
                )
            logger.info(f"Loaded {len(self._long_term)} long-term memories")
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to load memory: {e}")

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        """Get memory usage statistics."""
        return {
            "short_term_requests": len(self._short_term),
            "short_term_entries": sum(len(v) for v in self._short_term.values()),
            "long_term_entries": len(self._long_term),
            "conversation_threads": len(self._conversation_history),
        }
