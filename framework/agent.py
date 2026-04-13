"""Agent base class with lifecycle management and state machine.

Provides the core abstraction for building agents with:
- Lifecycle hooks (on_start, on_step, on_complete, on_error)
- State machine (IDLE → RUNNING → WAITING → COMPLETED/FAILED)
- Automatic retry with configurable backoff
- Tool execution error isolation
- Integration with ToolRegistry and MemoryManager
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.tools import ToolRegistry, ToolExecutionError
from framework.memory import MemoryManager

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting_for_tool"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentContext:
    """Runtime context passed through the agent lifecycle."""

    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    request_id: str = ""
    step: int = 0
    max_steps: int = 10
    max_retries: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)
    _start_time: float = 0.0

    @property
    def elapsed_ms(self) -> float:
        return (time.time() - self._start_time) * 1000 if self._start_time else 0.0


@dataclass
class StepResult:
    """Result of a single agent step."""

    output: Any = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    should_continue: bool = True
    reasoning: str = ""


class BaseAgent(ABC):
    """Abstract base agent with lifecycle hooks and tool/memory integration."""

    def __init__(
        self,
        name: str,
        tool_registry: ToolRegistry | None = None,
        memory: MemoryManager | None = None,
    ):
        self.name = name
        self.tools = tool_registry or ToolRegistry()
        self.memory = memory or MemoryManager()
        self.status = AgentStatus.IDLE
        self._context: AgentContext | None = None

    # --- Lifecycle hooks (override in subclass) ---

    def on_start(self, context: AgentContext, input_data: Any) -> None:
        """Called before the first step."""

    def on_step(self, context: AgentContext, step_result: StepResult) -> None:
        """Called after each step."""

    def on_complete(self, context: AgentContext, final_output: Any) -> None:
        """Called on successful completion."""

    def on_error(self, context: AgentContext, error: Exception) -> None:
        """Called when the agent fails after all retries."""

    # --- Core method to implement ---

    @abstractmethod
    async def step(self, context: AgentContext, input_data: Any) -> StepResult:
        """Execute one step of the agent. Must be implemented by subclass."""
        ...

    def _reset(self) -> None:
        """Reset agent state for a fresh run."""
        self.status = AgentStatus.IDLE
        self._context = None

    # --- Tool execution with error isolation ---

    async def _execute_tools(self, tool_calls: list[dict[str, Any]]) -> None:
        """Execute tool calls with individual error isolation."""
        self.status = AgentStatus.WAITING
        for call in tool_calls:
            tool_name = call.get("tool")
            if not tool_name:
                call["result"] = None
                call["error"] = "Missing tool name"
                logger.warning("Tool call missing 'tool' key, skipping")
                continue

            tool_args = call.get("args", {})
            try:
                call["result"] = await self.tools.execute(tool_name, **tool_args)
                call["error"] = None
            except (ToolExecutionError, Exception) as e:
                call["result"] = None
                call["error"] = str(e)
                logger.warning(f"Tool '{tool_name}' failed: {e}")
        self.status = AgentStatus.RUNNING

    # --- Runner ---

    async def run(
        self,
        input_data: Any,
        request_id: str = "",
        max_steps: int = 10,
    ) -> Any:
        """Run the agent through its full lifecycle."""
        self._reset()

        context = AgentContext(
            request_id=request_id or str(uuid.uuid4())[:8],
            max_steps=max_steps,
            _start_time=time.time(),
        )
        self._context = context
        self.status = AgentStatus.RUNNING

        logger.info(f"[{self.name}] Starting (request={context.request_id})")
        self.on_start(context, input_data)

        self.memory.store_short_term(context.request_id, f"{self.name}:input", input_data)

        current_input = input_data
        last_output: Any = None
        retries = 0

        try:
            while context.step < context.max_steps:
                context.step += 1

                try:
                    result = await self.step(context, current_input)
                    retries = 0

                    if result.tool_calls:
                        await self._execute_tools(result.tool_calls)

                    self.on_step(context, result)
                    last_output = result.output
                    current_input = result.output

                    if not result.should_continue:
                        break

                except Exception as step_error:
                    retries += 1
                    logger.warning(
                        f"[{self.name}] Step {context.step} failed "
                        f"(retry {retries}/{context.max_retries}): {step_error}"
                    )
                    if retries >= context.max_retries:
                        raise

            self.status = AgentStatus.COMPLETED
            self.on_complete(context, last_output)

            self.memory.store_short_term(context.request_id, f"{self.name}:output", last_output)
            self.memory.store_long_term(
                f"{self.name}:last_run",
                {
                    "request_id": context.request_id,
                    "steps": context.step,
                    "elapsed_ms": context.elapsed_ms,
                    "status": self.status.value,
                },
            )

            logger.info(
                f"[{self.name}] Completed in {context.step} steps ({context.elapsed_ms:.0f}ms)"
            )
            return last_output

        except Exception as e:
            self.status = AgentStatus.FAILED
            self.on_error(context, e)
            logger.error(f"[{self.name}] Failed: {e}")
            raise
