"""
LangGraph node implementations: translator, executor, visualizer, and graph builder.

Implements the three-agent pipeline for NL2SQL: translating natural language
to SQL, executing queries safely, and generating Chart.js visualizations.
Includes prompt injection detection, circuit breaker for Ollama, and
heuristic fallback paths.
"""

import json
import logging
import operator
import re
from typing import Annotated, Any, Dict, List, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from circuit_breaker import ollama_circuit_breaker
from config import (
    ALLOW_HEURISTIC_FALLBACK,
    DB_PATH,
    MODEL_NAME,
    OLLAMA_URL,
    get_db_schema,
)
from exceptions import OllamaConnectionError
from logging_config import get_request_id
from policy.engine import (
    evaluate_sql_policy,
    infer_chart_config_from_question,
    infer_sql_from_question,
)
from warehouse_adapter import get_active_warehouse_adapter

_logger = logging.getLogger("nexus_hive.graph")

_MAX_QUESTION_LENGTH: int = 500
_PROMPT_INJECTION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"(system|assistant)\s*:\s*", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|your)\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
]


def _sanitize_user_input(question: str) -> str:
    """Sanitize user question to mitigate prompt injection attacks.

    Performs three safety checks:
      1. Truncates to a maximum length to prevent oversized prompts.
      2. Strips control characters that could manipulate prompt formatting.
      3. Detects common prompt injection patterns and rejects the input.

    Args:
        question: The raw user question string.

    Returns:
        The sanitized question string.

    Raises:
        ValueError: If the question contains prompt injection patterns.
    """
    sanitized: str = str(question or "").strip()
    if len(sanitized) > _MAX_QUESTION_LENGTH:
        sanitized = sanitized[:_MAX_QUESTION_LENGTH]
        _logger.warning("Question truncated to %d chars", _MAX_QUESTION_LENGTH)
    # Remove null bytes and other control characters (keep newlines and tabs)
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', sanitized)
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(sanitized):
            _logger.warning("Prompt injection pattern detected in question")
            raise ValueError(
                "The question contains patterns that resemble prompt injection. "
                "Please rephrase your analytics question."
            )
    return sanitized


class AgentState(TypedDict):
    """Typed state dictionary passed through the LangGraph agent pipeline.

    Attributes:
        user_query: The original user question.
        sql_query: Generated SQL query string.
        db_result: List of result row dictionaries.
        chart_config: Chart.js configuration dictionary.
        error: Error message from the most recent failure, or empty string.
        retry_count: Number of translator-executor retries performed.
        fallback_sql_used: Whether heuristic SQL fallback was engaged.
        fallback_chart_used: Whether heuristic chart config was used.
        policy_verdict: Policy evaluation result dictionary.
        log_stream: Accumulated agent trace log messages.
    """

    user_query: str
    sql_query: str
    db_result: List[Dict[str, Any]]
    chart_config: Dict[str, Any]
    error: str
    retry_count: int
    fallback_sql_used: bool
    fallback_chart_used: bool
    policy_verdict: Dict[str, Any]
    log_stream: Annotated[List[str], operator.add]


async def ask_ollama(prompt: str) -> str:
    """Send a prompt to the Ollama LLM and return the response text.

    Uses the circuit breaker to prevent cascading failures when Ollama
    is unavailable. Records success/failure for circuit state transitions.

    Args:
        prompt: The full prompt string to send to Ollama.

    Returns:
        The LLM response text.

    Raises:
        OllamaConnectionError: If Ollama is unreachable or times out.
        CircuitBreakerOpenError: If the circuit breaker is currently open.
    """
    ollama_circuit_breaker.check()
    _logger.info(
        "Sending prompt to Ollama model=%s, prompt_length=%d",
        MODEL_NAME,
        len(prompt),
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(OLLAMA_URL, json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
            })
            result: str = response.json().get("response", "")
            ollama_circuit_breaker.record_success()
            _logger.info("Ollama response received, length=%d", len(result))
            return result
    except httpx.TimeoutException:
        ollama_circuit_breaker.record_failure()
        raise OllamaConnectionError(
            f"Ollama request timed out after 120s. "
            f"The model '{MODEL_NAME}' at {OLLAMA_URL} may be overloaded or unreachable.",
            url=OLLAMA_URL,
            model=MODEL_NAME,
        )
    except httpx.ConnectError:
        ollama_circuit_breaker.record_failure()
        raise OllamaConnectionError(
            f"Could not connect to Ollama at {OLLAMA_URL}. "
            "Ensure the Ollama service is running.",
            url=OLLAMA_URL,
            model=MODEL_NAME,
        )


async def translator_node(state: AgentState) -> AgentState:
    """Translate a natural language question into SQL using the LLM.

    Sanitizes the user input, constructs a schema-aware prompt, calls Ollama,
    and falls back to heuristic SQL inference if Ollama is unavailable.

    Args:
        state: The current agent pipeline state.

    Returns:
        Updated agent state with sql_query and log_stream populated.
    """
    request_id: str = get_request_id() or "unknown"
    _logger.info(
        "Translator node started for request_id=%s, query='%s'",
        request_id,
        state["user_query"][:100],
    )
    state["log_stream"].append(f"[Agent 1: Translator] Analyzing prompt: '{state['user_query']}'")
    active_adapter = get_active_warehouse_adapter()
    schema_text: str = get_db_schema()

    try:
        sanitized_question: str = _sanitize_user_input(state["user_query"])
    except ValueError as exc:
        state["error"] = str(exc)
        state["sql_query"] = ""
        state["log_stream"].append(f"[Agent 1: Translator] Input rejected: {exc}")
        _logger.warning("Translator input rejected: %s", exc)
        return state

    sanitized_error: str = str(state.get("error", "None"))[:200]

    prompt: str = f"""You are a senior analytics engineer for governed data platforms.
Translate the following executive question into a valid SQL query for {active_adapter.prompt_sql_target()}.
Current execution posture: {active_adapter.prompt_execution_note()}
Use only the tables provided in the schema. Return ONLY the SQL query, nothing else (no markdown blocks, no explanations).
IMPORTANT: Only generate SELECT queries. Never generate DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, or TRUNCATE statements.

Schema:
{schema_text}

Question: {sanitized_question}

If previous error exists, fix this issue: {sanitized_error}
"""
    sql: str = ""
    try:
        sql_response: str = await ask_ollama(prompt)
        sql = sql_response.strip().replace("```sql", "").replace("```", "").strip()
        _logger.info("Translator generated SQL via Ollama, length=%d", len(sql))
    except Exception as exc:
        state["log_stream"].append(f"[Agent 1: Translator] Ollama unavailable: {exc}")
        _logger.warning("Translator Ollama call failed: %s", exc)

    if not sql and ALLOW_HEURISTIC_FALLBACK:
        sql = infer_sql_from_question(state["user_query"])
        state["fallback_sql_used"] = True
        state["log_stream"].append("[Agent 1: Translator] Heuristic SQL fallback engaged.")
        _logger.info("Translator used heuristic SQL fallback")

    state["sql_query"] = sql
    state["log_stream"].append(f"[Agent 1: Translator] Generated SQL:\n{sql}")
    return state


def executor_node(state: AgentState) -> AgentState:
    """Execute SQL safely through the warehouse adapter with policy enforcement.

    Evaluates SQL against the policy engine, rejects denied queries, and
    executes allowed queries through the active warehouse adapter.

    Args:
        state: The current agent pipeline state.

    Returns:
        Updated agent state with db_result, policy_verdict, and error populated.
    """
    sql: str = state["sql_query"]
    active_adapter = get_active_warehouse_adapter()
    request_id: str = get_request_id() or "unknown"

    _logger.info(
        "Executor node started for request_id=%s via %s",
        request_id,
        active_adapter.contract.name,
    )
    state["log_stream"].append(
        f"[Agent 2: Executor] Auditing and executing SQL through {active_adapter.contract.name} ({active_adapter.contract.execution_mode})..."
    )

    if not sql or not sql.strip():
        state["error"] = "Translator produced empty SQL. Cannot execute."
        state["log_stream"].append(f"[Agent 2: Executor] ERROR: {state['error']}")
        state["policy_verdict"] = {
            "role": "analyst",
            "decision": "deny",
            "deny_reasons": ["empty_sql_from_translator"],
            "review_reasons": [],
        }
        _logger.warning("Executor received empty SQL from translator")
        return state

    policy: Dict[str, Any] = evaluate_sql_policy(sql)
    state["policy_verdict"] = policy
    _logger.info(
        "Policy evaluation: decision=%s, deny_reasons=%s",
        policy["decision"],
        policy.get("deny_reasons", []),
    )

    if policy["decision"] == "deny":
        state["error"] = f"Policy denied query: {', '.join(policy['deny_reasons'])}"
        state["log_stream"].append(f"[Agent 2: Executor] ERROR: {state['error']}")
        _logger.warning("Executor policy denied: %s", policy["deny_reasons"])
        return state
    if policy["review_reasons"]:
        state["log_stream"].append(
            f"[Agent 2: Executor] Review required: {', '.join(policy['review_reasons'])}"
        )

    try:
        execution: Dict[str, Any] = active_adapter.execute_sql_preview(sql, DB_PATH)
        result: List[Dict[str, Any]] = list(execution.get("preview") or [])
        state["db_result"] = result
        state["error"] = ""
        state["log_stream"].append(
            f"[Agent 2: Executor] Query successful via {active_adapter.contract.name}. Retrieved {execution.get('row_count', len(result))} rows."
        )
        _logger.info(
            "Executor query successful: %d rows in %dms",
            execution.get("row_count", 0),
            execution.get("elapsed_ms", 0),
        )
    except Exception as e:
        state["error"] = str(e)
        state["log_stream"].append(f"[Agent 2: Executor] SQL Execution Error: {e}")
        _logger.error("Executor SQL execution error: %s", e)

    return state


async def visualizer_node(state: AgentState) -> AgentState:
    """Generate a Chart.js configuration from query results using the LLM.

    Constructs a visualization prompt with sample data, calls Ollama for
    chart configuration, and falls back to heuristic inference if unavailable.

    Args:
        state: The current agent pipeline state.

    Returns:
        Updated agent state with chart_config populated.
    """
    request_id: str = get_request_id() or "unknown"
    _logger.info(
        "Visualizer node started for request_id=%s, data_points=%d",
        request_id,
        len(state["db_result"]),
    )
    state["log_stream"].append(
        f"[Agent 3: Visualizer] Designing Chart.js configuration for {len(state['db_result'])} data points..."
    )

    sample_data: List[Dict[str, Any]] = state["db_result"][:3]

    try:
        sanitized_viz_question: str = _sanitize_user_input(state["user_query"])
    except ValueError:
        sanitized_viz_question = "analytics question"

    prompt: str = f"""You are a Frontend Data Visualization Expert.
Look at the user's original question and the sample data structure extracted from the database.
Determine the best Chart.js configuration string (just a valid JSON object).
Do NOT include any markdown formatting, just the raw JSON text.

User Question: {sanitized_viz_question}
Sample Data: {json.dumps(sample_data)}

Return EXACTLY this JSON format (choose type: 'bar', 'line', 'pie', 'doughnut'):
{{
    "type": "bar",
    "labels_key": "<key_from_data_for_x_axis>",
    "data_key": "<key_from_data_for_y_axis>",
    "title": "<Chart Title>"
}}
"""
    config_response: str = ""
    try:
        config_response = await ask_ollama(prompt)
        clean_json: str = (
            config_response.strip().replace("```json", "").replace("```", "").strip()
        )
        config: Dict[str, Any] = json.loads(clean_json)
        state["chart_config"] = config
        state["log_stream"].append(
            f"[Agent 3: Visualizer] Generated Chart.js config: {config['type'].upper()} Chart."
        )
        _logger.info("Visualizer generated chart config: type=%s", config.get("type"))
    except Exception as exc:
        if exc:
            state["log_stream"].append(
                f"[Agent 3: Visualizer] LLM chart config unavailable: {exc}"
            )
            _logger.warning("Visualizer LLM unavailable: %s", exc)
        state["chart_config"] = infer_chart_config_from_question(
            state["user_query"], state["db_result"]
        )
        state["fallback_chart_used"] = True
        state["log_stream"].append(
            "[Agent 3: Visualizer] Heuristic chart config used."
        )
        _logger.info("Visualizer used heuristic chart fallback")

    return state


def route_after_execution(state: AgentState) -> str:
    """Decide the next node after executor based on error state and retry budget.

    Routes back to translator for retry if an error occurred and retries
    remain, to END if retries are exhausted, or to visualizer on success.

    Args:
        state: The current agent pipeline state.

    Returns:
        The name of the next node: 'translator', 'visualizer', or END.
    """
    if state["error"] and state["retry_count"] < 3:
        state["retry_count"] += 1
        _logger.info(
            "Routing to translator retry %d/3",
            state["retry_count"],
        )
        return "translator"
    elif state["error"]:
        _logger.warning(
            "Agent pipeline exhausted retries after %d attempts",
            state["retry_count"],
        )
        return END
    else:
        return "visualizer"


def build_graph() -> Any:
    """Build and compile the LangGraph agent pipeline.

    Creates a three-node graph: translator -> executor -> visualizer
    with conditional retry routing from executor back to translator.

    Returns:
        A compiled LangGraph workflow ready for streaming execution.
    """
    _logger.info("Building LangGraph agent pipeline")
    workflow: StateGraph = StateGraph(AgentState)

    workflow.add_node("translator", translator_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("visualizer", visualizer_node)

    workflow.set_entry_point("translator")
    workflow.add_edge("translator", "executor")
    workflow.add_conditional_edges("executor", route_after_execution, {
        "translator": "translator",
        "visualizer": "visualizer",
        END: END,
    })
    workflow.add_edge("visualizer", END)

    return workflow.compile()
