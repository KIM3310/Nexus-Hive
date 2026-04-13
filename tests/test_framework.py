"""Tests for the Agent Framework: agent, tools, memory, orchestrator."""

from __future__ import annotations

import asyncio
import pytest
import time
from pathlib import Path
from typing import Any

from framework.agent import BaseAgent, AgentContext, AgentStatus, StepResult
from framework.tools import ToolRegistry, ToolNotFoundError, ToolExecutionError
from framework.memory import MemoryManager
from framework.orchestrator import Orchestrator, ExecutionMode


# --- Test Agent Implementation ---

class EchoAgent(BaseAgent):
    """Simple agent that echoes input with a prefix."""

    async def step(self, context: AgentContext, input_data: Any) -> StepResult:
        return StepResult(output=f"[{self.name}] {input_data}", should_continue=False)


class CountingAgent(BaseAgent):
    """Agent that counts up to 3 steps."""

    async def step(self, context: AgentContext, input_data: Any) -> StepResult:
        count = (input_data or 0) if isinstance(input_data, int) else 0
        count += 1
        return StepResult(output=count, should_continue=count < 3)


class ToolUsingAgent(BaseAgent):
    """Agent that calls a registered tool."""

    async def step(self, context: AgentContext, input_data: Any) -> StepResult:
        return StepResult(
            output=input_data,
            tool_calls=[{"tool": "uppercase", "args": {"text": str(input_data)}}],
            should_continue=False,
        )


class FailingAgent(BaseAgent):
    """Agent that always fails."""

    async def step(self, context: AgentContext, input_data: Any) -> StepResult:
        raise ValueError("intentional failure")


# === Tool Registry Tests ===

class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        registry.register("greet", lambda name: f"hello {name}", description="Greet someone")
        tool = registry.get("greet")
        assert tool.name == "greet"
        assert tool.description == "Greet someone"

    def test_decorator_registration(self):
        registry = ToolRegistry()

        @registry.tool(name="add", description="Add two numbers")
        def add(a: int, b: int) -> int:
            return a + b

        assert "add" in [t.name for t in registry.list_tools()]
        assert add(1, 2) == 3  # original function still works

    @pytest.mark.asyncio
    async def test_execute_sync_tool(self):
        registry = ToolRegistry()
        registry.register("double", lambda x: x * 2)
        result = await registry.execute("double", x=5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        registry = ToolRegistry()

        async def async_add(a: int, b: int) -> int:
            return a + b

        registry.register("async_add", async_add)
        result = await registry.execute("async_add", a=3, b=4)
        assert result == 7

    def test_tool_not_found(self):
        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            registry.get("nonexistent")

    @pytest.mark.asyncio
    async def test_execution_tracking(self):
        registry = ToolRegistry()
        registry.register("inc", lambda x: x + 1)
        await registry.execute("inc", x=1)
        await registry.execute("inc", x=2)
        metrics = registry.metrics()
        assert metrics["inc"]["call_count"] == 2
        assert metrics["inc"]["total_duration_ms"] >= 0

    def test_list_schemas(self):
        registry = ToolRegistry()
        registry.register("search", lambda q: q, description="Search", parameters={"q": {"type": "string"}})
        schemas = registry.list_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "search"


# === Memory Manager Tests ===

class TestMemoryManager:
    def test_short_term_store_and_get(self):
        mem = MemoryManager()
        mem.store_short_term("req1", "question", "What is revenue?")
        assert mem.get_short_term("req1", "question") == "What is revenue?"

    def test_short_term_missing_key(self):
        mem = MemoryManager()
        assert mem.get_short_term("req1", "missing") is None

    def test_short_term_expiry(self):
        mem = MemoryManager()
        mem.store_short_term("req1", "temp", "data", ttl_seconds=0.01)
        time.sleep(0.02)
        assert mem.get_short_term("req1", "temp") is None

    def test_long_term_store_and_get(self):
        mem = MemoryManager()
        mem.store_long_term("pattern:sql", {"template": "SELECT *"})
        assert mem.get_long_term("pattern:sql")["template"] == "SELECT *"

    def test_long_term_search(self):
        mem = MemoryManager()
        mem.store_long_term("agent:translator:last", {"steps": 3})
        mem.store_long_term("agent:executor:last", {"steps": 1})
        mem.store_long_term("config:model", "gpt-4")
        results = mem.search_long_term("agent:")
        assert len(results) == 2

    def test_conversation_history(self):
        mem = MemoryManager()
        mem.add_message("req1", "user", "Show revenue")
        mem.add_message("req1", "agent", "SELECT SUM(revenue)...")
        history = mem.get_history("req1")
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_conversation_history_last_n(self):
        mem = MemoryManager()
        for i in range(10):
            mem.add_message("req1", "user", f"msg {i}")
        assert len(mem.get_history("req1", last_n=3)) == 3

    def test_clear_request(self):
        mem = MemoryManager()
        mem.store_short_term("req1", "data", "value")
        mem.add_message("req1", "user", "hello")
        mem.clear_request("req1")
        assert mem.get_short_term("req1", "data") is None
        assert mem.get_history("req1") == []

    def test_persistence(self, tmp_path):
        path = tmp_path / "mem.json"
        mem1 = MemoryManager(persist_path=path)
        mem1.store_long_term("key1", "value1")

        mem2 = MemoryManager(persist_path=path)
        assert mem2.get_long_term("key1") == "value1"

    def test_stats(self):
        mem = MemoryManager()
        mem.store_short_term("r1", "a", 1)
        mem.store_short_term("r2", "b", 2)
        mem.store_long_term("x", "y")
        stats = mem.stats()
        assert stats["short_term_requests"] == 2
        assert stats["long_term_entries"] == 1


# === Agent Tests ===

class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_echo_agent(self):
        agent = EchoAgent(name="echo")
        result = await agent.run("hello")
        assert result == "[echo] hello"
        assert agent.status == AgentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_counting_agent_multi_step(self):
        agent = CountingAgent(name="counter")
        result = await agent.run(0)
        assert result == 3
        assert agent._context.step == 3

    @pytest.mark.asyncio
    async def test_tool_using_agent(self):
        registry = ToolRegistry()
        registry.register("uppercase", lambda text: text.upper())
        agent = ToolUsingAgent(name="tool_user", tool_registry=registry)
        result = await agent.run("hello")
        assert result == "hello"  # output is the input, but tool was called
        assert registry.metrics()["uppercase"]["call_count"] == 1

    @pytest.mark.asyncio
    async def test_failing_agent(self):
        agent = FailingAgent(name="failer")
        with pytest.raises(ValueError):
            await agent.run("anything")
        assert agent.status == AgentStatus.FAILED

    @pytest.mark.asyncio
    async def test_max_steps_limit(self):
        agent = CountingAgent(name="limited")
        result = await agent.run(0, max_steps=2)
        assert result == 2  # stopped at step 2, not 3

    @pytest.mark.asyncio
    async def test_memory_integration(self):
        mem = MemoryManager()
        agent = EchoAgent(name="mem_agent", memory=mem)
        await agent.run("test_input", request_id="req123")
        assert mem.get_short_term("req123", "input") == "test_input"
        assert mem.get_short_term("req123", "output") == "[mem_agent] test_input"
        assert mem.get_long_term("mem_agent:last_run") is not None


# === Orchestrator Tests ===

class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        orch = Orchestrator()
        orch.register(EchoAgent(name="agent_a"))
        orch.register(EchoAgent(name="agent_b"))
        result = await orch.run_sequential("hello")
        assert result.execution_order == ["agent_a", "agent_b"]
        assert "[agent_b]" in str(result.outputs["agent_b"])

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        orch = Orchestrator()
        orch.register(EchoAgent(name="p1"))
        orch.register(EchoAgent(name="p2"))
        result = await orch.run_parallel("input")
        assert "p1" in result.outputs
        assert "p2" in result.outputs

    @pytest.mark.asyncio
    async def test_routed_execution(self):
        orch = Orchestrator()
        orch.register(EchoAgent(name="sql_agent"))
        orch.register(EchoAgent(name="chart_agent"))
        orch.add_route("sql", "sql_agent")
        orch.add_route("chart", "chart_agent")
        result = await orch.run_routed("generate a chart")
        assert "chart_agent" in result.outputs

    @pytest.mark.asyncio
    async def test_shared_memory(self):
        orch = Orchestrator()
        orch.register(EchoAgent(name="a1"))
        orch.register(EchoAgent(name="a2"))
        # Both agents should share the orchestrator's memory
        assert orch._agents["a1"].memory is orch._agents["a2"].memory

    @pytest.mark.asyncio
    async def test_parallel_with_failure(self):
        orch = Orchestrator()
        orch.register(EchoAgent(name="good"))
        orch.register(FailingAgent(name="bad"))
        result = await orch.run_parallel("test")
        assert "error" in result.outputs["bad"]
        assert "[good]" in str(result.outputs["good"])

    def test_list_agents(self):
        orch = Orchestrator()
        orch.register(EchoAgent(name="x"))
        orch.register(EchoAgent(name="y"))
        assert orch.list_agents() == ["x", "y"]
