# ADR 001: Multi-Agent Pipeline Over Monolithic LLM Call

## Status

Accepted

## Date

2026-03-15

## Context

Nexus-Hive needs to translate natural language business questions into SQL, execute them safely, and produce visualizations. The simplest approach would be a single LLM call that receives the question and returns SQL, execution results, and a chart configuration in one pass. We evaluated this monolithic approach against a multi-agent pipeline with three distinct stages.

### Option A: Single Monolithic LLM Call

One prompt asks the LLM to generate SQL, describe execution intent, and suggest a chart type in a single JSON response. The application parses the response and executes the SQL.

### Option B: Multi-Agent Pipeline (Translator, Executor, Visualizer)

Three separate agents, each with a focused responsibility:

1. **Translator** -- Converts natural language to SQL using schema-aware prompting.
2. **Executor** -- Evaluates the SQL against the policy engine, then executes it through the warehouse adapter.
3. **Visualizer** -- Generates a Chart.js configuration from the query results.

## Decision

We chose **Option B: Multi-Agent Pipeline**, implemented as a LangGraph state graph with conditional edges.

## Consequences

### Benefits

- **Independent testing.** Each agent can be unit-tested in isolation. The Translator can be tested against gold eval cases without a live database. The Executor can be tested with hardcoded SQL. The Visualizer can be tested with synthetic result sets.

- **Retry per stage.** When the Executor rejects SQL (policy denial or execution error), the pipeline routes back to the Translator for correction without re-running the Visualizer. The retry budget (3 attempts) is scoped to the Translator-Executor loop, not the entire pipeline.

- **Policy injection between stages.** The policy engine sits between translation and execution -- a natural enforcement point. In a monolithic call, policy checks would have to be applied post-hoc to an already-generated response, creating a parse-then-reject pattern that wastes LLM tokens.

- **Heuristic fallback isolation.** When the LLM is unavailable (circuit breaker open), only the affected agent falls back to heuristics. The Translator can use keyword-based SQL inference while the Visualizer independently uses chart type heuristics. A monolithic approach would require a single fallback that handles all three concerns.

- **Observability.** Each agent appends to a shared `log_stream`, producing a step-by-step trace that operators can inspect via the SSE `/api/stream` endpoint. This trace is far more useful for debugging than a single opaque LLM response.

- **Adapter independence.** The Executor delegates to the active warehouse adapter (SQLite, Snowflake, Databricks) without the Translator or Visualizer needing awareness of the execution backend.

### Tradeoffs

- **Increased latency.** Three sequential agent invocations (two of which call the LLM) are slower than a single call. We accept this because governed analytics prioritizes correctness and auditability over sub-second response times.

- **State management complexity.** The `AgentState` TypedDict must carry all intermediate results between nodes. LangGraph handles this cleanly, but it introduces a dependency on the LangGraph framework.

- **Multiple prompt engineering surfaces.** Each agent has its own prompt template, which means more prompts to maintain and tune. We mitigate this with the gold eval suite that scores output quality across all stages.

## References

- `graph/nodes.py` -- Agent node implementations and graph builder
- `policy/engine.py` -- Policy evaluation called between Translator and Executor
- `circuit_breaker.py` -- Circuit breaker protecting Ollama calls per-agent
