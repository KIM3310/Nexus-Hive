"""Multi-agent Orchestrator.

Coordinates multiple agents in configurable execution patterns:
- Sequential: agents run one after another, output → input chaining
- Parallel: agents run concurrently with isolated request IDs
- Router: pattern-based routing to select the right agent per request
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.agent import BaseAgent
from framework.memory import MemoryManager

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    ROUTER = "router"


class OrchestrationError(Exception):
    """Raised when orchestration fails."""


@dataclass
class OrchestrationResult:
    """Result of a multi-agent orchestration run."""

    outputs: dict[str, Any]
    execution_order: list[str]
    total_steps: int
    elapsed_ms: float
    agent_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


class Orchestrator:
    """Coordinates multiple agents with shared memory and tool registry."""

    def __init__(self, memory: MemoryManager | None = None) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._routes: dict[str, str] = {}
        self.memory = memory or MemoryManager()

    def register(self, agent: BaseAgent) -> None:
        """Register an agent with the orchestrator."""
        self._agents[agent.name] = agent
        agent.memory = self.memory
        logger.info(f"Registered agent: {agent.name}")

    def add_route(self, pattern: str, agent_name: str) -> None:
        """Add a routing rule: if input matches pattern, route to agent_name."""
        if agent_name not in self._agents:
            raise ValueError(f"Agent '{agent_name}' not registered")
        self._routes[pattern] = agent_name

    async def run_sequential(
        self,
        input_data: Any,
        agent_names: list[str] | None = None,
        request_id: str = "",
    ) -> OrchestrationResult:
        """Run agents sequentially, chaining output → input."""
        agents = self._resolve_agents(agent_names)
        if not agents:
            raise OrchestrationError("No agents to run (empty agent list)")

        start = time.time()
        req_id = request_id or str(uuid.uuid4())[:8]

        outputs: dict[str, Any] = {}
        execution_order: list[str] = []
        total_steps = 0
        current_input = input_data

        for agent in agents:
            output = await agent.run(current_input, request_id=req_id)
            outputs[agent.name] = output
            execution_order.append(agent.name)
            total_steps += agent._context.step if agent._context else 0
            current_input = output

        return OrchestrationResult(
            outputs=outputs,
            execution_order=execution_order,
            total_steps=total_steps,
            elapsed_ms=(time.time() - start) * 1000,
            agent_metrics=self._collect_metrics(agents),
        )

    async def run_parallel(
        self,
        input_data: Any,
        agent_names: list[str] | None = None,
        request_id: str = "",
    ) -> OrchestrationResult:
        """Run agents in parallel with isolated request IDs per agent."""
        agents = self._resolve_agents(agent_names)
        if not agents:
            raise OrchestrationError("No agents to run (empty agent list)")

        start = time.time()
        base_req_id = request_id or str(uuid.uuid4())[:8]

        # Each agent gets a unique request_id to avoid memory conflicts
        tasks = [
            agent.run(input_data, request_id=f"{base_req_id}:{agent.name}") for agent in agents
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs: dict[str, Any] = {}
        execution_order: list[str] = []
        total_steps = 0

        for agent, result in zip(agents, results):
            if isinstance(result, Exception):
                outputs[agent.name] = {"error": str(result)}
                logger.error(f"Agent '{agent.name}' failed: {result}")
            else:
                outputs[agent.name] = result
            execution_order.append(agent.name)
            total_steps += agent._context.step if agent._context else 0

        return OrchestrationResult(
            outputs=outputs,
            execution_order=execution_order,
            total_steps=total_steps,
            elapsed_ms=(time.time() - start) * 1000,
            agent_metrics=self._collect_metrics(agents),
        )

    async def run_routed(
        self,
        input_data: Any,
        request_id: str = "",
    ) -> OrchestrationResult:
        """Route input to the appropriate agent based on registered routes."""
        if not self._agents:
            raise OrchestrationError("No agents registered for routing")

        start = time.time()
        input_str = str(input_data).lower()

        selected_agent: BaseAgent | None = None
        for pattern, agent_name in self._routes.items():
            if pattern.lower() in input_str:
                selected_agent = self._agents[agent_name]
                break

        if selected_agent is None:
            selected_agent = next(iter(self._agents.values()))
            logger.info(f"No route matched, defaulting to '{selected_agent.name}'")

        req_id = request_id or str(uuid.uuid4())[:8]
        output = await selected_agent.run(input_data, request_id=req_id)

        return OrchestrationResult(
            outputs={selected_agent.name: output},
            execution_order=[selected_agent.name],
            total_steps=selected_agent._context.step if selected_agent._context else 0,
            elapsed_ms=(time.time() - start) * 1000,
            agent_metrics=self._collect_metrics([selected_agent]),
        )

    def _resolve_agents(self, names: list[str] | None) -> list[BaseAgent]:
        if names is None:
            return list(self._agents.values())
        missing = [n for n in names if n not in self._agents]
        if missing:
            raise OrchestrationError(f"Agents not found: {missing}")
        return [self._agents[n] for n in names]

    def _collect_metrics(self, agents: list[BaseAgent]) -> dict[str, dict[str, Any]]:
        return {
            agent.name: {
                "status": agent.status.value,
                "steps": agent._context.step if agent._context else 0,
                "elapsed_ms": round(agent._context.elapsed_ms, 1) if agent._context else 0,
                "tool_metrics": agent.tools.metrics(),
            }
            for agent in agents
        }

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())
