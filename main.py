import json
import sqlite3
import pandas as pd
from datetime import datetime, timezone
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from urllib.parse import quote_plus
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import asyncio
import httpx
import tempfile

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("NEXUS_HIVE_DB_PATH", str(BASE_DIR / "nexus_enterprise.db"))).expanduser()
OLLAMA_URL = str(os.getenv("NEXUS_HIVE_OLLAMA_URL", "http://localhost:11434/api/generate")).strip()
MODEL_NAME = str(os.getenv("NEXUS_HIVE_MODEL", "phi3")).strip() or "phi3"
AUDIT_LOG_PATH = Path(
    os.getenv(
        "NEXUS_HIVE_AUDIT_PATH",
        str(Path(tempfile.gettempdir()) / "nexus_hive_query_audit.jsonl"),
    )
).expanduser()

READ_ONLY_BLOCKLIST = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE", "CREATE"}
WAREHOUSE_ADAPTERS = [
    {
        "name": "sqlite-demo",
        "status": "active",
        "role": "Local warehouse stand-in for governed analytics review",
        "capabilities": ["read-only SQL execution", "pandas result preview", "local schema introspection"],
    },
    {
        "name": "cloud-warehouse-contract",
        "status": "planned",
        "role": "Parameterized warehouse adapter contract for future deployment",
        "capabilities": ["query tagging", "role simulation", "audit sink integration"],
    },
    {
        "name": "lakehouse-sql-contract",
        "status": "planned",
        "role": "Lakehouse SQL adapter contract for medallion-style modeled tables",
        "capabilities": ["modeled view registration", "freshness metadata", "quality gate attachment"],
    },
]
LINEAGE_RELATIONSHIPS = [
    {
        "from_table": "sales",
        "from_column": "product_id",
        "to_table": "products",
        "to_column": "product_id",
        "kind": "dimension-join",
        "semantic_role": "product context",
    },
    {
        "from_table": "sales",
        "from_column": "region_id",
        "to_table": "regions",
        "to_column": "region_id",
        "kind": "dimension-join",
        "semantic_role": "regional ownership",
    },
]

import operator

# Read DB Schema for the LLM
def get_db_schema():
    if not DB_PATH.exists():
        return ""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        schema = ""
        for table, ddl in tables:
            schema += f"Table: {table}\nDDL: {ddl}\n\n"
        return schema

DB_SCHEMA = get_db_schema()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_scalar_query(sql: str) -> int:
    if not DB_PATH.exists():
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()
        return int(row[0] or 0) if row else 0


def fetch_date_window() -> Dict[str, Optional[str]]:
    if not DB_PATH.exists():
        return {"min_date": None, "max_date": None}
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(date), MAX(date) FROM sales")
        min_date, max_date = cursor.fetchone() or (None, None)
        return {"min_date": min_date, "max_date": max_date}


def build_table_profiles() -> List[Dict[str, Any]]:
    if not DB_PATH.exists():
        return []

    profiles: List[Dict[str, Any]] = []
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            row_count = int(cursor.fetchone()[0] or 0)
            cursor.execute(f'PRAGMA table_info("{table}")')
            columns = cursor.fetchall()
            profiles.append(
                {
                    "table": table,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "columns": [column[1] for column in columns],
                }
            )
    return profiles


def build_quality_gate() -> Dict[str, Any]:
    table_profiles = build_table_profiles()
    required_tables = {"sales", "products", "regions"}
    present_tables = {profile["table"] for profile in table_profiles}
    missing_tables = sorted(required_tables - present_tables)

    checks = [
        {
            "name": "required_tables_present",
            "description": "sales, products, and regions tables must all be loaded before governed querying.",
            "violations": len(missing_tables),
            "status": "pass" if not missing_tables else "fail",
            "details": {"missing_tables": missing_tables},
        },
        {
            "name": "sales_primary_fields_not_null",
            "description": "sales rows should keep transaction, date, product, region, and net revenue populated.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM sales
                WHERE transaction_id IS NULL
                    OR date IS NULL
                    OR product_id IS NULL
                    OR region_id IS NULL
                    OR net_revenue IS NULL
                """
            ),
        },
        {
            "name": "sales_product_fk_integrity",
            "description": "Every sales.product_id should resolve to a products dimension row.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.product_id
                WHERE p.product_id IS NULL
                """
            ),
        },
        {
            "name": "sales_region_fk_integrity",
            "description": "Every sales.region_id should resolve to a regions dimension row.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM sales s
                LEFT JOIN regions r ON s.region_id = r.region_id
                WHERE r.region_id IS NULL
                """
            ),
        },
        {
            "name": "transaction_id_uniqueness",
            "description": "Each sales transaction_id should stay unique for auditable grain.",
            "violations": run_scalar_query(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT transaction_id
                    FROM sales
                    GROUP BY transaction_id
                    HAVING COUNT(*) > 1
                ) dupes
                """
            ),
        },
    ]

    for check in checks[1:]:
        check["status"] = "pass" if check["violations"] == 0 else "fail"

    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "schema": "nexus-hive-quality-gate-v1",
        "status": "ok" if not failed else "degraded",
        "headline": "Quality gate validates modeled tables before governed querying is trusted.",
        "checks": checks,
        "failed_checks": [check["name"] for check in failed],
    }


def build_lineage_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-lineage-v1",
        "semantic_model": [
            {
                "name": "fact_sales",
                "source_table": "sales",
                "grain": "transaction_id",
                "measures": ["gross_revenue", "net_revenue", "profit", "quantity"],
            },
            {
                "name": "dim_products",
                "source_table": "products",
                "grain": "product_id",
                "attributes": ["product_name", "category", "unit_price", "margin_percentage"],
            },
            {
                "name": "dim_regions",
                "source_table": "regions",
                "grain": "region_id",
                "attributes": ["region_name", "manager"],
            },
        ],
        "relationships": LINEAGE_RELATIONSHIPS,
        "operator_rules": [
            "Aggregate metrics should be traced back to fact_sales grain before approval.",
            "Dimension joins must stay auditable and consistent with the modeled foreign-key relationships.",
            "Reviewers should inspect lineage and quality gates before trusting NL2SQL output.",
        ],
    }


def build_query_audit_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-query-audit-v1",
        "storage_mode": "append-only jsonl snapshots with latest-state views per request_id",
        "required_fields": [
            "request_id",
            "question",
            "status",
            "stage",
            "sql_query",
            "row_count",
            "retry_count",
            "updated_at",
        ],
        "stages": ["accepted", "completed", "failed"],
        "operator_rules": [
            "Each governed query keeps a stable request_id from acceptance through terminal state.",
            "SQL text should remain reviewable even when execution fails.",
            "Audit history is for review posture, not a substitute for warehouse-native lineage tooling.",
        ],
    }


def append_query_audit_snapshot(snapshot: Dict[str, Any]) -> None:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=True) + "\n")


def write_query_audit_snapshot(
    *,
    request_id: str,
    question: str,
    status: str,
    stage: str,
    sql_query: str = "",
    row_count: int = 0,
    retry_count: int = 0,
    chart_type: str = "",
    error: str = "",
) -> None:
    timestamp = utc_now_iso()
    append_query_audit_snapshot(
        {
            "service": "nexus-hive",
            "request_id": request_id,
            "question": question,
            "status": status,
            "stage": stage,
            "sql_query": sql_query,
            "row_count": row_count,
            "retry_count": retry_count,
            "chart_type": chart_type,
            "error": error,
            "updated_at": timestamp,
        }
    )


def list_recent_query_audits(limit: int = 5) -> List[Dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []

    latest_by_request: Dict[str, Dict[str, Any]] = {}
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = str(payload.get("request_id") or "").strip()
            if not request_id:
                continue
            latest_by_request[request_id] = payload

    return sorted(
        latest_by_request.values(),
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )[: max(1, min(limit, 20))]


def build_warehouse_brief() -> Dict[str, Any]:
    table_profiles = build_table_profiles()
    quality_gate = build_quality_gate()
    date_window = fetch_date_window()
    recent_audits = list_recent_query_audits(limit=5)

    return {
        "status": "ok" if quality_gate["status"] == "ok" else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "readiness_contract": "nexus-hive-warehouse-brief-v1",
        "headline": "Governed analytics brief tying warehouse mode, lineage, quality gate, and audit trail into one reviewable surface.",
        "warehouse_mode": "sqlite-demo",
        "adapter_contracts": WAREHOUSE_ADAPTERS,
        "table_profiles": table_profiles,
        "date_window": date_window,
        "quality_gate": quality_gate,
        "lineage": build_lineage_schema(),
        "recent_audit_count": len(recent_audits),
        "policy_examples": [
            "read_only_sql_only",
            "aggregates_before_operator_approval",
            "trace_sql_before_chart_trust",
        ],
        "routes": [
            "/api/runtime/warehouse-brief",
            "/api/schema/lineage",
            "/api/schema/query-audit",
            "/api/query-audit/recent",
        ],
    }

# --- LangGraph State Definition ---
class AgentState(TypedDict):
    user_query: str
    sql_query: str
    db_result: List[Dict[str, Any]]
    chart_config: Dict[str, Any]
    error: str
    retry_count: int
    log_stream: Annotated[List[str], operator.add] # Accumulates logs across nodes

# --- AI Helper Function ---
async def ask_ollama(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(OLLAMA_URL, json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        })
        return response.json().get("response", "")

# --- Node 1: SQL Translator ---
async def translator_node(state: AgentState) -> AgentState:
    state["log_stream"].append(f"[Agent 1: Translator] Analyzing prompt: '{state['user_query']}'")
    
    prompt = f"""You are a senior analytics engineer for governed data platforms.
Translate the following executive question into a valid SQL query for SQLite.
Use only the tables provided in the schema. Return ONLY the SQL query, nothing else (no markdown blocks, no explanations).

Schema:
{DB_SCHEMA}

Question: {state['user_query']}

If previous error exists, fix this issue: {state.get('error', 'None')}
"""
    sql_response = await ask_ollama(prompt)
    
    # Clean markdown if the LLM misbehaves
    sql = sql_response.strip().replace("```sql", "").replace("```", "").strip()
    state["sql_query"] = sql
    state["log_stream"].append(f"[Agent 1: Translator] Generated SQL:\n{sql}")
    return state

# --- Node 2: Data Executor ---
def executor_node(state: AgentState) -> AgentState:
    sql = state["sql_query"]
    state["log_stream"].append(f"[Agent 2: Executor] Auditing and executing SQL against nexus_enterprise.db...")
    
    # Security Audit
    if any(keyword in sql.upper() for keyword in READ_ONLY_BLOCKLIST):
        state["error"] = "Unsafe operations detected. Read-only queries allowed."
        state["log_stream"].append(f"[Agent 2: Executor] ❌ ERROR: {state['error']}")
        return state

    try:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(sql, conn)
            # Limit to 50 rows for frontend visualization
            result = df.head(50).to_dict(orient="records")
            state["db_result"] = result
            state["error"] = ""
            state["log_stream"].append(f"[Agent 2: Executor] ✅ Query successful. Retrieved {len(result)} rows.")
    except Exception as e:
        state["error"] = str(e)
        state["log_stream"].append(f"[Agent 2: Executor] ❌ SQL Execution Error: {e}")
        
    return state

# --- Node 3: Visualizer ---
async def visualizer_node(state: AgentState) -> AgentState:
    state["log_stream"].append(f"[Agent 3: Visualizer] Designing Chart.js configuration for {len(state['db_result'])} data points...")
    
    # We ask the LLM to determine the best chart type and axis categories
    sample_data = state["db_result"][:3] # Show LLM a sample to prevent context overflow
    
    prompt = f"""You are a Frontend Data Visualization Expert.
Look at the user's original question and the sample data structure extracted from the database.
Determine the best Chart.js configuration string (just a valid JSON object).
Do NOT include any markdown formatting, just the raw JSON text.

User Question: {state['user_query']}
Sample Data: {json.dumps(sample_data)}

Return EXACTLY this JSON format (choose type: 'bar', 'line', 'pie', 'doughnut'):
{{
    "type": "bar",
    "labels_key": "<key_from_data_for_x_axis>",
    "data_key": "<key_from_data_for_y_axis>",
    "title": "<Chart Title>"
}}
"""
    config_response = await ask_ollama(prompt)
    try:
        clean_json = config_response.strip().replace("```json", "").replace("```", "").strip()
        config = json.loads(clean_json)
        state["chart_config"] = config
        state["log_stream"].append(f"[Agent 3: Visualizer] ✅ Generated Chart.js config: {config['type'].upper()} Chart.")
    except:
        # Fallback if LLM fails JSON parsing
        keys = list(state["db_result"][0].keys())
        state["chart_config"] = {
            "type": "bar",
            "labels_key": keys[0],
            "data_key": keys[1] if len(keys) > 1 else keys[0],
            "title": "Data Visualization"
        }
        state["log_stream"].append(f"[Agent 3: Visualizer] ⚠️ Fallback chart config used.")
        
    return state

# --- Edge Routing Logic ---
def route_after_execution(state: AgentState) -> str:
    if state["error"] and state["retry_count"] < 3:
        state["retry_count"] += 1
        return "translator" # Self-correction loop
    elif state["error"]:
        return END # Give up after 3 retries
    else:
        return "visualizer"

# --- Build the LangGraph ---
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

graph = build_graph()

# --- FastAPI Server ---
app = FastAPI(title="Nexus-Hive Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_runtime_meta() -> Dict[str, Any]:
    db_exists = DB_PATH.exists()
    db_size_bytes = DB_PATH.stat().st_size if db_exists else 0
    schema_loaded = bool(DB_SCHEMA.strip())
    warehouse_brief = build_warehouse_brief()
    diagnostics = {
        "db_ready": db_exists and schema_loaded,
        "db_size_bytes": db_size_bytes,
        "schema_loaded": schema_loaded,
        "ollama_configured": OLLAMA_URL.startswith("http"),
        "warehouse_mode": warehouse_brief["warehouse_mode"],
        "quality_gate_status": warehouse_brief["quality_gate"]["status"],
        "recent_audit_count": warehouse_brief["recent_audit_count"],
        "next_action": (
            "POST /api/ask with an executive question, then follow the returned /api/stream URL."
            if db_exists and schema_loaded and OLLAMA_URL.startswith("http")
            else "Run `python3 seed_db.py` and verify NEXUS_HIVE_OLLAMA_URL before live demos."
        ),
    }
    return {
        "service": "nexus-hive",
        "model": MODEL_NAME,
        "ollama_url": OLLAMA_URL,
        "db_path": str(DB_PATH),
        "diagnostics": diagnostics,
        "ops_contract": {
            "schema": "ops-envelope-v1",
            "version": 1,
            "required_fields": ["service", "status", "diagnostics.next_action"],
        },
        "routes": [
            "/health",
            "/api/meta",
            "/api/runtime/brief",
            "/api/runtime/warehouse-brief",
            "/api/review-pack",
            "/api/schema/answer",
            "/api/schema/lineage",
            "/api/schema/query-audit",
            "/api/query-audit/recent",
            "/api/ask",
            "/api/stream",
        ],
        "capabilities": [
            "natural-language-to-sql",
            "audit-safe-readonly-execution",
            "chart-config-generation",
            "sse-agent-trace-streaming",
            "runtime-brief-surface",
            "warehouse-brief-surface",
            "lineage-schema-surface",
            "query-audit-surface",
            "review-pack-surface",
            "answer-schema-surface",
        ],
    }


def build_answer_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-answer-v1",
        "required_sections": [
            "question",
            "sql_query",
            "chart_config",
            "result_preview",
            "agent_trace",
            "runtime_posture",
        ],
        "operator_rules": [
            "Only read-only SQL is allowed through the executor agent.",
            "Chart configuration should be derived from result shape, not hard-coded assumptions.",
            "If SQL fails, the self-correction loop retries up to 3 times before returning a controlled failure.",
        ],
    }


def build_runtime_brief() -> Dict[str, Any]:
    runtime_meta = build_runtime_meta()
    warehouse_brief = build_warehouse_brief()
    diagnostics = runtime_meta["diagnostics"]
    db_ready = diagnostics["db_ready"]

    return {
        "status": "ok" if db_ready else "degraded",
        "service": "nexus-hive",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness_contract": "nexus-hive-runtime-brief-v1",
        "headline": (
            "Federated BI copilot that turns executive questions into audited SQL, executes them safely, and renders chart-ready answers."
        ),
        "diagnostics": diagnostics,
        "model": MODEL_NAME,
        "report_contract": build_answer_schema(),
        "evidence_counts": {
            "agent_nodes": 3,
            "retry_budget": 3,
            "seeded_rows": 10000,
            "runtime_routes": len(runtime_meta["routes"]),
        },
        "warehouse_contract": {
            "mode": warehouse_brief["warehouse_mode"],
            "quality_gate_schema": warehouse_brief["quality_gate"]["schema"],
            "lineage_schema": warehouse_brief["lineage"]["schema"],
            "query_audit_schema": build_query_audit_schema()["schema"],
        },
        "review_flow": [
            "Open /health to confirm database and model posture.",
            "Read /api/runtime/warehouse-brief for adapter mode, lineage, and quality-gate posture.",
            "Read /api/runtime/brief for agent contract, retry policy, and reviewer guidance.",
            "Ask a question through /api/ask or the frontend to validate SQL, execution, and chart generation.",
            "Inspect the streamed agent trace before trusting any rendered answer.",
        ],
        "watchouts": [
            "The visualization agent uses the shape of returned rows; poor SQL still yields poor charts.",
            "Ollama availability affects live demos, but the runtime brief remains available without it.",
            "SQLite is used as a local warehouse stand-in, not a claim of production warehouse scale.",
        ],
        "agent_contract": [
            {
                "agent": "translator",
                "responsibility": "Generate SQL from natural language and schema context.",
            },
            {
                "agent": "executor",
                "responsibility": "Block unsafe SQL and execute read-only analytics queries.",
            },
            {
                "agent": "visualizer",
                "responsibility": "Infer a Chart.js payload from the result shape.",
            },
        ],
        "routes": runtime_meta["routes"],
    }


def build_review_pack() -> Dict[str, Any]:
    runtime_brief = build_runtime_brief()
    warehouse_brief = build_warehouse_brief()
    diagnostics = runtime_brief["diagnostics"]
    report_contract = runtime_brief["report_contract"]

    return {
        "status": runtime_brief["status"],
        "service": "nexus-hive",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness_contract": "nexus-hive-review-pack-v1",
        "headline": "Executive BI review pack tying question, safe SQL, chart output, and agent trace into one audited workflow.",
        "proof_bundle": {
            "warehouse_ready": diagnostics["db_ready"],
            "agent_nodes": runtime_brief["evidence_counts"]["agent_nodes"],
            "retry_budget": runtime_brief["evidence_counts"]["retry_budget"],
            "quality_gate_status": warehouse_brief["quality_gate"]["status"],
            "lineage_edges": len(warehouse_brief["lineage"]["relationships"]),
            "recent_audit_count": warehouse_brief["recent_audit_count"],
            "review_routes": [
                "/health",
                "/api/meta",
                "/api/runtime/brief",
                "/api/runtime/warehouse-brief",
                "/api/review-pack",
                "/api/schema/answer",
                "/api/schema/lineage",
                "/api/schema/query-audit",
                "/api/query-audit/recent",
                "/api/ask",
                "/api/stream",
            ],
        },
        "executive_promises": [
            "Every answer keeps the SQL layer visible before the chart layer.",
            "Unsafe write operations are blocked before execution.",
            "The agent trace remains inspectable through SSE rather than hidden behind a single response blob.",
            "Warehouse lineage, quality checks, and query audit stay reviewable before the chart is trusted.",
        ],
        "trust_boundary": [
            "translator: natural language becomes SQL only through warehouse schema context",
            "executor: read-only SQL enforcement blocks destructive operations",
            "visualizer: chart payload is inferred from actual result shape",
            "warehouse brief: lineage and quality gate stay visible before approval",
            "stream: reviewer can audit the agent trace before trusting the rendered chart",
        ],
        "review_sequence": [
            "Open /health to confirm warehouse and model posture.",
            "Read /api/runtime/warehouse-brief for data contracts, lineage, and quality gates.",
            "Read /api/runtime/brief for retry policy and agent responsibilities.",
            "Read /api/review-pack for executive promises, trust boundary, and review routes.",
            "Use /api/ask, /api/stream, and /api/query-audit/recent together before trusting a dashboard answer.",
        ],
        "answer_contract": {
            "schema": report_contract["schema"],
            "required_sections": report_contract["required_sections"],
        },
        "watchouts": runtime_brief["watchouts"],
        "links": {
            "health": "/health",
            "meta": "/api/meta",
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "review_pack": "/api/review-pack",
            "answer_schema": "/api/schema/answer",
            "lineage_schema": "/api/schema/lineage",
            "query_audit_schema": "/api/schema/query-audit",
            "query_audit_recent": "/api/query-audit/recent",
            "ask": "/api/ask",
            "stream": "/api/stream",
        },
    }

async def run_agent_and_stream(question: str, request_id: str):
    state = {
        "user_query": question,
        "sql_query": "",
        "db_result": [],
        "chart_config": {},
        "error": "",
        "retry_count": 0,
        "log_stream": []
    }
    
    # Stream the graph execution over SSE
    async for output in graph.astream(state):
        # Determine which node just finished
        node_name = list(output.keys())[0]
        node_state = output[node_name]
        
        # Flush new logs
        for log in node_state["log_stream"]:
            yield f"data: {json.dumps({'type': 'log', 'content': log})}\n\n"
            await asyncio.sleep(0.1) # Smooth UI feel
            
        # Clear the log stream so we don't repeat events
        node_state["log_stream"] = []
        
        # If it's the final visualizer node, emit the payload
        if node_name == "visualizer":
            yield f"data: {json.dumps({'type': 'chart_data', 'config': node_state['chart_config'], 'data': node_state['db_result']})}\n\n"
            
        # Sync external state
        state = node_state

    if state["error"] and state["retry_count"] >= 3:
        error_message = f"[System] Agent failed after 3 retries. Error: {state.get('error')}"
        yield f"data: {json.dumps({'type': 'log', 'content': error_message})}\n\n"
        write_query_audit_snapshot(
            request_id=request_id,
            question=question,
            status="failed",
            stage="failed",
            sql_query=state.get("sql_query", ""),
            row_count=len(state.get("db_result", [])),
            retry_count=state.get("retry_count", 0),
            chart_type=state.get("chart_config", {}).get("type", ""),
            error=state.get("error", ""),
        )
    else:
        write_query_audit_snapshot(
            request_id=request_id,
            question=question,
            status="completed",
            stage="completed",
            sql_query=state.get("sql_query", ""),
            row_count=len(state.get("db_result", [])),
            retry_count=state.get("retry_count", 0),
            chart_type=state.get("chart_config", {}).get("type", ""),
            error=state.get("error", ""),
        )

    yield "data: {\"type\": \"done\"}\n\n"

class AskRequest(BaseModel):
    question: str


@app.get("/health")
async def health_endpoint():
    runtime_meta = build_runtime_meta()
    return {
        "status": "ok" if runtime_meta["diagnostics"]["db_ready"] else "degraded",
        "links": {
            "meta": "/api/meta",
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "review_pack": "/api/review-pack",
            "answer_schema": "/api/schema/answer",
            "lineage_schema": "/api/schema/lineage",
            "query_audit_schema": "/api/schema/query-audit",
            "query_audit_recent": "/api/query-audit/recent",
            "ask": "/api/ask",
            "stream": "/api/stream",
        },
        **runtime_meta,
    }


@app.get("/api/meta")
async def meta_endpoint():
    runtime_meta = build_runtime_meta()
    return {
        "status": "ok" if runtime_meta["diagnostics"]["db_ready"] else "degraded",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness_contract": "nexus-hive-runtime-brief-v1",
        "warehouse_brief_contract": "nexus-hive-warehouse-brief-v1",
        "review_pack_contract": "nexus-hive-review-pack-v1",
        "report_contract": build_answer_schema(),
        "lineage_contract": build_lineage_schema()["schema"],
        "query_audit_contract": build_query_audit_schema()["schema"],
        **runtime_meta,
    }


@app.get("/api/runtime/brief")
async def runtime_brief_endpoint():
    return build_runtime_brief()


@app.get("/api/runtime/warehouse-brief")
async def warehouse_brief_endpoint():
    return build_warehouse_brief()


@app.get("/api/review-pack")
async def review_pack_endpoint():
    return build_review_pack()


@app.get("/api/schema/answer")
async def answer_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **build_answer_schema(),
    }


@app.get("/api/schema/lineage")
async def lineage_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_lineage_schema(),
    }


@app.get("/api/schema/query-audit")
async def query_audit_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_audit_schema(),
    }


@app.get("/api/query-audit/recent")
async def query_audit_recent_endpoint(limit: int = 5):
    items = list_recent_query_audits(limit=limit)
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_query_audit_schema()["schema"],
        "items": items,
    }


@app.post("/api/ask")
async def ask_endpoint(req: AskRequest, request: Request):
    question = str(req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > 1000:
        raise HTTPException(status_code=413, detail="question is too long")

    request_id = uuid4().hex[:12]
    write_query_audit_snapshot(
        request_id=request_id,
        question=question,
        status="accepted",
        stage="accepted",
    )
    stream_url = str(request.url_for("stream_endpoint"))
    return {
        "status": "accepted",
        "message": "Use the SSE stream endpoint to receive the full agent trace.",
        "request_id": request_id,
        "question": question,
        "stream_url": f"{stream_url}?q={quote_plus(question)}&rid={request_id}",
        "links": {
            "runtime_brief": str(request.url_for("runtime_brief_endpoint")),
            "warehouse_brief": str(request.url_for("warehouse_brief_endpoint")),
            "answer_schema": str(request.url_for("answer_schema_endpoint")),
            "query_audit_recent": str(request.url_for("query_audit_recent_endpoint")),
        },
    }


@app.get("/api/stream")
async def stream_endpoint(q: str, rid: Optional[str] = None):
    request_id = str(rid or uuid4().hex[:12]).strip()
    return StreamingResponse(run_agent_and_stream(q, request_id=request_id), media_type="text/event-stream")

# Mount frontend
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_path, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
