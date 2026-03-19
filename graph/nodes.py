"""
LangGraph node implementations: translator, executor, visualizer, and graph builder.
"""

import json
import operator
import re
from typing import Annotated, Any, Dict, List, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from config import (
    ALLOW_HEURISTIC_FALLBACK,
    DB_PATH,
    MODEL_NAME,
    OLLAMA_URL,
    get_db_schema,
)
from policy.engine import (
    evaluate_sql_policy,
    infer_chart_config_from_question,
    infer_sql_from_question,
)
from warehouse_adapter import get_active_warehouse_adapter


_MAX_QUESTION_LENGTH = 500
_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"(system|assistant)\s*:\s*", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|your)\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
]


def _sanitize_user_input(question: str) -> str:
    """Sanitize user question to mitigate prompt injection attacks.

    - Truncates to a maximum length
    - Strips characters that could be used for prompt manipulation
    - Detects common injection patterns
    """
    sanitized = str(question or "").strip()
    if len(sanitized) > _MAX_QUESTION_LENGTH:
        sanitized = sanitized[:_MAX_QUESTION_LENGTH]
    # Remove null bytes and other control characters (keep newlines and tabs for readability)
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', sanitized)
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(sanitized):
            raise ValueError(
                "The question contains patterns that resemble prompt injection. "
                "Please rephrase your analytics question."
            )
    return sanitized


class AgentState(TypedDict):
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
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(OLLAMA_URL, json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False
            })
            return response.json().get("response", "")
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama request timed out after 120s. "
            f"The model '{MODEL_NAME}' at {OLLAMA_URL} may be overloaded or unreachable."
        )
    except httpx.ConnectError:
        raise RuntimeError(
            f"Could not connect to Ollama at {OLLAMA_URL}. "
            "Ensure the Ollama service is running."
        )


async def translator_node(state: AgentState) -> AgentState:
    state["log_stream"].append(f"[Agent 1: Translator] Analyzing prompt: '{state['user_query']}'")
    active_adapter = get_active_warehouse_adapter()
    schema_text = get_db_schema()

    try:
        sanitized_question = _sanitize_user_input(state["user_query"])
    except ValueError as exc:
        state["error"] = str(exc)
        state["sql_query"] = ""
        state["log_stream"].append(f"[Agent 1: Translator] Input rejected: {exc}")
        return state

    sanitized_error = str(state.get("error", "None"))[:200]

    prompt = f"""You are a senior analytics engineer for governed data platforms.
Translate the following executive question into a valid SQL query for {active_adapter.prompt_sql_target()}.
Current execution posture: {active_adapter.prompt_execution_note()}
Use only the tables provided in the schema. Return ONLY the SQL query, nothing else (no markdown blocks, no explanations).
IMPORTANT: Only generate SELECT queries. Never generate DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, or TRUNCATE statements.

Schema:
{schema_text}

Question: {sanitized_question}

If previous error exists, fix this issue: {sanitized_error}
"""
    sql = ""
    try:
        sql_response = await ask_ollama(prompt)
        sql = sql_response.strip().replace("```sql", "").replace("```", "").strip()
    except Exception as exc:
        state["log_stream"].append(f"[Agent 1: Translator] Ollama unavailable: {exc}")

    if not sql and ALLOW_HEURISTIC_FALLBACK:
        sql = infer_sql_from_question(state["user_query"])
        state["fallback_sql_used"] = True
        state["log_stream"].append("[Agent 1: Translator] Heuristic SQL fallback engaged.")

    state["sql_query"] = sql
    state["log_stream"].append(f"[Agent 1: Translator] Generated SQL:\n{sql}")
    return state


def executor_node(state: AgentState) -> AgentState:
    sql = state["sql_query"]
    active_adapter = get_active_warehouse_adapter()
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
        return state

    policy = evaluate_sql_policy(sql)
    state["policy_verdict"] = policy
    if policy["decision"] == "deny":
        state["error"] = f"Policy denied query: {', '.join(policy['deny_reasons'])}"
        state["log_stream"].append(f"[Agent 2: Executor] ERROR: {state['error']}")
        return state
    if policy["review_reasons"]:
        state["log_stream"].append(
            f"[Agent 2: Executor] Review required: {', '.join(policy['review_reasons'])}"
        )

    try:
        execution = active_adapter.execute_sql_preview(sql, DB_PATH)
        result = list(execution.get("preview") or [])
        state["db_result"] = result
        state["error"] = ""
        state["log_stream"].append(
            f"[Agent 2: Executor] Query successful via {active_adapter.contract.name}. Retrieved {execution.get('row_count', len(result))} rows."
        )
    except Exception as e:
        state["error"] = str(e)
        state["log_stream"].append(f"[Agent 2: Executor] SQL Execution Error: {e}")

    return state


async def visualizer_node(state: AgentState) -> AgentState:
    state["log_stream"].append(f"[Agent 3: Visualizer] Designing Chart.js configuration for {len(state['db_result'])} data points...")

    sample_data = state["db_result"][:3]

    try:
        sanitized_viz_question = _sanitize_user_input(state["user_query"])
    except ValueError:
        sanitized_viz_question = "analytics question"

    prompt = f"""You are a Frontend Data Visualization Expert.
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
    config_response = ""
    try:
        config_response = await ask_ollama(prompt)
        clean_json = config_response.strip().replace("```json", "").replace("```", "").strip()
        config = json.loads(clean_json)
        state["chart_config"] = config
        state["log_stream"].append(f"[Agent 3: Visualizer] Generated Chart.js config: {config['type'].upper()} Chart.")
    except Exception as exc:
        if exc:
            state["log_stream"].append(f"[Agent 3: Visualizer] LLM chart config unavailable: {exc}")
        state["chart_config"] = infer_chart_config_from_question(state["user_query"], state["db_result"])
        state["fallback_chart_used"] = True
        state["log_stream"].append("[Agent 3: Visualizer] Heuristic chart config used.")

    return state


def route_after_execution(state: AgentState) -> str:
    if state["error"] and state["retry_count"] < 3:
        state["retry_count"] += 1
        return "translator"
    elif state["error"]:
        return END
    else:
        return "visualizer"


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("translator", translator_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("visualizer", visualizer_node)

    workflow.set_entry_point("translator")
    workflow.add_edge("translator", "executor")
    workflow.add_conditional_edges("executor", route_after_execution, {
        "translator": "translator",
        "visualizer": "visualizer",
        END: END
    })
    workflow.add_edge("visualizer", END)

    return workflow.compile()
