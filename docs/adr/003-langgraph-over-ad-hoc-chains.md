# ADR 003: LangGraph State Graph Over Ad-Hoc Async Chains

## Status

Accepted

## Date

2026-04-13

## Context

Nexus-Hive's multi-agent pipeline (Translator, Executor, Visualizer) requires orchestration logic that handles sequential execution, conditional retry routing, typed intermediate state, and streaming observability. We evaluated three approaches for implementing this orchestration.

### Option A: Raw Async Chains

Call each agent function sequentially in a single `async def` handler. Use `if/else` branching for retry logic and error routing. Pass state as a plain dictionary between calls.

### Option B: LangChain AgentExecutor

Use LangChain's `AgentExecutor` with tools to manage the pipeline. Each agent stage becomes a tool that the executor selects dynamically.

### Option C: LangGraph State Graph

Define the pipeline as a compiled `StateGraph` with typed state (`AgentState` TypedDict), explicit nodes for each agent, and conditional edges for retry routing.

## Decision

We chose **Option C: LangGraph State Graph**, implementing the pipeline in `graph/nodes.py` with three nodes and one conditional edge.

## Consequences

### Benefits

- **Typed state contract.** `AgentState` is a `TypedDict` with 10 fields (`user_query`, `sql_query`, `db_result`, `chart_config`, `error`, `retry_count`, `fallback_sql_used`, `fallback_chart_used`, `policy_verdict`, `log_stream`). Every node reads and writes the same typed structure, eliminating key-mismatch bugs that plague dictionary-passing patterns.

- **Declarative routing.** The retry loop (`Executor -> Translator` on error) is expressed as a conditional edge via `add_conditional_edges()` with a routing function (`route_after_execution`). This makes the retry logic inspectable and testable without running the full pipeline -- the routing function is a pure function of state.

- **Compiled execution.** `workflow.compile()` produces an optimized execution plan. The compiled graph validates node connectivity at startup, catching wiring errors before the first request.

- **Streaming support.** LangGraph's `astream_events()` emits structured events at each node transition. Nexus-Hive maps these events to SSE messages on the `/api/stream` endpoint, giving operators a real-time agent trace without custom streaming infrastructure.

- **Annotated state fields.** The `log_stream` field uses `Annotated[List[str], operator.add]`, which tells LangGraph to accumulate (not replace) log entries across node invocations. This eliminates the common bug where a downstream node accidentally overwrites logs from upstream nodes.

- **Independent node testing.** Each node function (`translator_node`, `executor_node`, `visualizer_node`) accepts and returns `AgentState`. They can be unit-tested by constructing a state dictionary, calling the function, and asserting the output -- without instantiating the graph or mocking LangGraph internals.

### Tradeoffs

- **Framework dependency.** LangGraph (and its transitive dependency on `langchain-core`) adds to the dependency tree. If LangGraph's API changes, the graph builder and streaming integration must be updated. We accept this because the typed state and declarative routing features significantly reduce orchestration bugs.

- **Overhead for simple pipelines.** A three-node graph does not strictly need a graph framework. However, the retry loop, conditional routing, and streaming support are features we would need to build manually with Option A, and the resulting code would be harder to test and maintain.

- **Not using LangGraph's built-in persistence.** LangGraph supports checkpoint-based persistence for long-running workflows. Nexus-Hive does not use this because each query completes in a single request cycle (including retries). If multi-turn conversations or approval-gated execution are added, persistence would become relevant.

### Why not LangChain AgentExecutor (Option B)

LangChain's AgentExecutor is designed for tool-calling agents where the LLM decides which tool to invoke. Nexus-Hive's pipeline is deterministic: Translator always runs first, then Executor, then Visualizer. The routing decision (retry or proceed) is based on error state, not LLM output. Using AgentExecutor would add unnecessary complexity and make the pipeline harder to reason about.

## References

- `graph/nodes.py` -- Node implementations, `AgentState` TypedDict, `build_graph()`, `route_after_execution()`
- `graph/__init__.py` -- Public API exports
- `routes/ask.py` -- Graph invocation from the `/api/ask` and `/api/stream` endpoints
- `services/streaming.py` -- SSE streaming using LangGraph's event system
