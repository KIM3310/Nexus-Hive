"""Tool Registry and Execution Engine.

Provides a declarative tool registration system where agents can:
- Register tools with name, description, and schema
- Discover available tools at runtime
- Execute tools with automatic validation and error handling
- Track tool execution metrics
"""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Metadata describing a registered tool."""

    name: str
    description: str
    handler: Callable
    parameters: dict[str, Any] = field(default_factory=dict)
    is_async: bool = False
    call_count: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.call_count if self.call_count > 0 else 0.0

    def to_schema(self) -> dict[str, Any]:
        """Export tool definition as LLM-compatible schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolNotFoundError(Exception):
    """Raised when a requested tool is not in the registry."""


class ToolExecutionError(Exception):
    """Raised when tool execution fails."""


class ToolRegistry:
    """Central registry for agent tools with execution tracking."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> ToolDefinition:
        """Register a tool with the registry."""
        is_async = inspect.iscoroutinefunction(handler)

        tool = ToolDefinition(
            name=name,
            description=description or handler.__doc__ or "",
            handler=handler,
            parameters=parameters or {},
            is_async=is_async,
        )
        self._tools[name] = tool
        logger.debug(f"Registered tool: {name} (async={is_async})")
        return tool

    def tool(
        self,
        name: str | None = None,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> Callable:
        """Decorator to register a function as a tool.

        Usage:
            registry = ToolRegistry()

            @registry.tool(name="search", description="Search the database")
            async def search_db(query: str) -> list:
                ...
        """

        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            self.register(tool_name, fn, description, parameters)
            return fn

        return decorator

    def get(self, name: str) -> ToolDefinition:
        """Get a tool definition by name."""
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' not found. Available: {list(self._tools.keys())}")
        return self._tools[name]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """Execute a registered tool by name with tracking."""
        tool = self.get(name)
        start = time.time()

        try:
            if tool.is_async:
                result = await tool.handler(**kwargs)
            else:
                result = tool.handler(**kwargs)

            duration = (time.time() - start) * 1000
            tool.call_count += 1
            tool.total_duration_ms += duration

            logger.debug(f"Tool '{name}' executed in {duration:.1f}ms")
            return result

        except Exception as e:
            logger.error(f"Tool '{name}' failed: {e}")
            raise ToolExecutionError(f"Tool '{name}' execution failed: {e}") from e

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_schemas(self) -> list[dict[str, Any]]:
        """Export all tool schemas for LLM consumption."""
        return [t.to_schema() for t in self._tools.values()]

    def metrics(self) -> dict[str, dict[str, Any]]:
        """Get execution metrics for all tools."""
        return {
            name: {
                "call_count": t.call_count,
                "total_duration_ms": round(t.total_duration_ms, 1),
                "avg_duration_ms": round(t.avg_duration_ms, 1),
            }
            for name, t in self._tools.items()
        }
