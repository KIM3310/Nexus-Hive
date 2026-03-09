import json
import sqlite3
import pandas as pd
from datetime import datetime, timezone
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from urllib.parse import quote_plus
from pathlib import Path
from uuid import uuid4
import sys
from fastapi import FastAPI, HTTPException, Request, Response
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
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from security import (
    apply_operator_session,
    clear_operator_session_cookie,
    create_operator_session_cookie,
    operator_allowed_roles,
    operator_auth_status,
    operator_role_headers,
    operator_session_cookie_name,
    operator_token_enabled,
    read_operator_session,
    require_operator_token,
)
from runtime_store import append_runtime_event, build_runtime_store_summary
DB_PATH = Path(os.getenv("NEXUS_HIVE_DB_PATH", str(BASE_DIR / "nexus_enterprise.db"))).expanduser()
OLLAMA_URL = str(os.getenv("NEXUS_HIVE_OLLAMA_URL", "http://localhost:11434/api/generate")).strip()
MODEL_NAME = str(os.getenv("NEXUS_HIVE_MODEL", "phi3")).strip() or "phi3"
DEFAULT_ROLE = str(os.getenv("NEXUS_HIVE_ROLE", "analyst")).strip().lower() or "analyst"
ALLOW_HEURISTIC_FALLBACK = str(os.getenv("NEXUS_HIVE_ALLOW_HEURISTIC_FALLBACK", "1")).strip() not in {"0", "false", "False"}
AUDIT_LOG_PATH = Path(
    os.getenv(
        "NEXUS_HIVE_AUDIT_PATH",
        str(Path(tempfile.gettempdir()) / "nexus_hive_query_audit.jsonl"),
    )
).expanduser()

READ_ONLY_BLOCKLIST = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE", "CREATE"}
SENSITIVE_COLUMNS_BY_ROLE = {
    "analyst": {"margin_percentage"},
    "viewer": {"margin_percentage", "manager"},
}
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
GOLD_EVAL_CASES = [
    {
        "case_id": "revenue_by_region",
        "question": "Show total net revenue by region",
        "expected_features": ["SUM(net_revenue)", "JOIN regions", "GROUP BY region_name"],
    },
    {
        "case_id": "profit_by_region",
        "question": "Show top 5 regions by total profit",
        "expected_features": ["SUM(profit)", "JOIN regions", "ORDER BY total_profit DESC", "LIMIT 5"],
    },
    {
        "case_id": "discount_by_category",
        "question": "What is the average discount applied per category?",
        "expected_features": ["AVG(discount_applied)", "JOIN products", "GROUP BY category"],
    },
    {
        "case_id": "monthly_revenue_trend",
        "question": "Show monthly net revenue trend",
        "expected_features": ["SUBSTR(date, 1, 7)", "SUM(net_revenue)", "GROUP BY month"],
    },
]
AUDIT_STATUS_VALUES = {"accepted", "completed", "failed"}
AUDIT_POLICY_DECISION_VALUES = {"pending", "allow", "review", "deny"}
GOVERNANCE_SCORECARD_FOCUS_VALUES = {"throughput", "policy", "quality", "resilience"}
GOVERNANCE_SCORECARD_SCHEMA = "nexus-hive-governance-scorecard-v1"
QUERY_SESSION_BOARD_SCHEMA = "nexus-hive-query-session-board-v1"

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


def log_runtime_event(level: str, event: str, **payload: Any) -> None:
    print(
        json.dumps(
            {
                "at": utc_now_iso(),
                "event": event,
                "level": level,
                "service": "nexus-hive",
                **payload,
            },
            ensure_ascii=True,
        )
    )


def normalize_operator_roles(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return []


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
            "policy_decision",
            "fallback_sql_used",
            "fallback_chart_used",
            "updated_at",
        ],
        "stages": ["accepted", "completed", "failed"],
        "operator_rules": [
            "Each governed query keeps a stable request_id from acceptance through terminal state.",
            "SQL text should remain reviewable even when execution fails.",
            "Audit history is for review posture, not a substitute for warehouse-native lineage tooling.",
        ],
    }


def normalize_question(question: str) -> str:
    return " ".join(str(question or "").strip().lower().split())


def infer_sql_from_question(question: str) -> str:
    normalized = normalize_question(question)

    if "discount" in normalized and "category" in normalized:
        return (
            "SELECT p.category, ROUND(AVG(s.discount_applied), 4) AS average_discount "
            "FROM sales s "
            "JOIN products p ON s.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY average_discount DESC "
            "LIMIT 10"
        )

    if "profit" in normalized and "region" in normalized:
        limit = 5 if "top 5" in normalized else 10
        return (
            "SELECT r.region_name, ROUND(SUM(s.profit), 2) AS total_profit "
            "FROM sales s "
            "JOIN regions r ON s.region_id = r.region_id "
            "GROUP BY r.region_name "
            "ORDER BY total_profit DESC "
            f"LIMIT {limit}"
        )

    if ("monthly" in normalized or "trend" in normalized or "month" in normalized) and "revenue" in normalized:
        return (
            "SELECT SUBSTR(s.date, 1, 7) AS month, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue "
            "FROM sales s "
            "GROUP BY month "
            "ORDER BY month ASC "
            "LIMIT 12"
        )

    if "quantity" in normalized and "category" in normalized:
        return (
            "SELECT p.category, SUM(s.quantity) AS total_quantity "
            "FROM sales s "
            "JOIN products p ON s.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY total_quantity DESC "
            "LIMIT 10"
        )

    if "category" in normalized and "revenue" in normalized:
        return (
            "SELECT p.category, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue "
            "FROM sales s "
            "JOIN products p ON s.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY total_net_revenue DESC "
            "LIMIT 10"
        )

    return (
        "SELECT r.region_name, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue "
        "FROM sales s "
        "JOIN regions r ON s.region_id = r.region_id "
        "GROUP BY r.region_name "
        "ORDER BY total_net_revenue DESC "
        "LIMIT 10"
    )


def infer_chart_config_from_question(question: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "type": "bar",
            "labels_key": "label",
            "data_key": "value",
            "title": "Data Visualization",
        }

    keys = list(rows[0].keys())
    label_key = keys[0]
    data_key = keys[1] if len(keys) > 1 else keys[0]
    normalized = normalize_question(question)
    chart_type = "bar"

    if "trend" in normalized or "month" in normalized or "date" in normalized:
        chart_type = "line"
    elif len(rows) <= 6 and any(keyword in normalized for keyword in ["share", "mix", "category", "region"]):
        chart_type = "doughnut"

    return {
        "type": chart_type,
        "labels_key": label_key,
        "data_key": data_key,
        "title": "Governed Analytics View",
    }


def build_policy_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-policy-v1",
        "default_role": DEFAULT_ROLE,
        "deny_rules": [
            "write_operations_blocked",
            "wildcard_projection_denied",
            "sensitive_columns_require_privileged_role",
        ],
        "review_rules": [
            "non_aggregated_queries_without_limit_require_operator_review",
        ],
        "sensitive_columns_by_role": SENSITIVE_COLUMNS_BY_ROLE,
    }


def evaluate_sql_policy(sql: str, role: str = DEFAULT_ROLE) -> Dict[str, Any]:
    normalized_sql = str(sql or "").strip()
    upper_sql = normalized_sql.upper()
    lower_sql = normalized_sql.lower()
    deny_reasons: List[str] = []
    review_reasons: List[str] = []
    sensitive_columns = SENSITIVE_COLUMNS_BY_ROLE.get(role, set())

    if any(keyword in upper_sql for keyword in READ_ONLY_BLOCKLIST):
        deny_reasons.append("write_operations_blocked")
    if "SELECT *" in upper_sql:
        deny_reasons.append("wildcard_projection_denied")
    if any(column in lower_sql for column in sensitive_columns):
        deny_reasons.append("sensitive_columns_require_privileged_role")
    if "GROUP BY" not in upper_sql and "LIMIT" not in upper_sql:
        review_reasons.append("non_aggregated_queries_without_limit_require_operator_review")

    decision = "deny" if deny_reasons else "review" if review_reasons else "allow"
    return {
        "role": role,
        "decision": decision,
        "deny_reasons": deny_reasons,
        "review_reasons": review_reasons,
    }


def evaluate_sql_case(sql: str, expected_features: List[str]) -> Dict[str, Any]:
    upper_sql = str(sql or "").upper()
    matched = [feature for feature in expected_features if feature.upper() in upper_sql]
    return {
        "matched_features": matched,
        "missing_features": [feature for feature in expected_features if feature not in matched],
        "score": len(matched),
        "max_score": len(expected_features),
        "status": "pass" if len(matched) == len(expected_features) else "partial",
    }


def build_gold_eval_pack() -> Dict[str, Any]:
    cases = []
    for case in GOLD_EVAL_CASES:
        fallback_sql = infer_sql_from_question(case["question"])
        verdict = evaluate_sql_case(fallback_sql, case["expected_features"])
        cases.append(
            {
                **case,
                "fallback_sql_preview": fallback_sql,
                "fallback_verdict": verdict,
            }
        )

    passing_cases = sum(1 for case in cases if case["fallback_verdict"]["status"] == "pass")
    return {
        "schema": "nexus-hive-gold-eval-v1",
        "headline": "Canonical NL2SQL review set used to judge governed analytics behavior before demo claims.",
        "summary": {
            "case_count": len(cases),
            "fallback_pass_count": passing_cases,
        },
        "cases": cases,
    }


def execute_sql_preview(sql: str) -> Dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(sql, conn)
    elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    rows = df.head(5).to_dict(orient="records")
    return {
        "row_count": int(len(df.index)),
        "preview": rows,
        "elapsed_ms": elapsed_ms,
    }


def run_gold_eval_suite(strategy: str = "heuristic") -> Dict[str, Any]:
    items = []
    passed = 0

    for case in GOLD_EVAL_CASES:
        sql = infer_sql_from_question(case["question"])
        feature_verdict = evaluate_sql_case(sql, case["expected_features"])
        policy_verdict = evaluate_sql_policy(sql)
        execution = None
        execution_error = ""

        if policy_verdict["decision"] != "deny":
            try:
                execution = execute_sql_preview(sql)
            except Exception as exc:
                execution_error = str(exc)
        else:
            execution_error = "policy denied"

        status = "pass"
        if feature_verdict["status"] != "pass":
            status = "partial"
        if policy_verdict["decision"] == "deny" or execution_error:
            status = "fail"

        if status == "pass":
            passed += 1

        items.append(
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "strategy": strategy,
                "sql": sql,
                "feature_verdict": feature_verdict,
                "policy_verdict": policy_verdict,
                "execution": execution
                or {
                    "row_count": 0,
                    "preview": [],
                    "elapsed_ms": 0,
                },
                "error": execution_error,
                "status": status,
            }
        )

    return {
        "schema": "nexus-hive-gold-eval-run-v1",
        "headline": "Runnable gold eval suite that checks SQL features, policy verdicts, and executable previews.",
        "strategy": strategy,
        "summary": {
            "case_count": len(items),
            "pass_count": passed,
            "fail_count": len([item for item in items if item["status"] == "fail"]),
        },
        "items": items,
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
    policy_decision: str = "",
    policy_reasons: Optional[List[str]] = None,
    fallback_sql_used: bool = False,
    fallback_chart_used: bool = False,
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
            "policy_decision": policy_decision,
            "policy_reasons": policy_reasons or [],
            "fallback_sql_used": fallback_sql_used,
            "fallback_chart_used": fallback_chart_used,
            "updated_at": timestamp,
        }
    )


def iter_query_audit_snapshots() -> List[Dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []

    snapshots: List[Dict[str, Any]] = []
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                snapshots.append(payload)

    return snapshots


def clamp_audit_limit(limit: int, *, default: int = 5, maximum: int = 20) -> int:
    if not isinstance(limit, int):
        return default
    return max(1, min(limit, maximum))


def normalize_audit_status_filter(status: Optional[str]) -> Optional[str]:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return None
    if normalized not in AUDIT_STATUS_VALUES:
        raise HTTPException(status_code=400, detail="invalid status filter")
    return normalized


def normalize_policy_decision_filter(policy_decision: Optional[str]) -> Optional[str]:
    normalized = str(policy_decision or "").strip().lower()
    if not normalized:
        return None
    if normalized not in AUDIT_POLICY_DECISION_VALUES:
        raise HTTPException(status_code=400, detail="invalid policy_decision filter")
    return normalized


def normalize_fallback_mode_filter(fallback_mode: Optional[str]) -> Optional[str]:
    normalized = str(fallback_mode or "").strip().lower()
    if not normalized:
        return None
    if normalized not in {"none", "sql", "chart", "any"}:
        raise HTTPException(status_code=400, detail="invalid fallback_mode filter")
    return normalized


def matches_fallback_mode(item: Dict[str, Any], fallback_mode: Optional[str]) -> bool:
    if fallback_mode is None:
        return True
    fallback_sql = bool(item.get("fallback_sql_used"))
    fallback_chart = bool(item.get("fallback_chart_used"))
    if fallback_mode == "sql":
        return fallback_sql
    if fallback_mode == "chart":
        return fallback_chart
    if fallback_mode == "any":
        return fallback_sql or fallback_chart
    return not fallback_sql and not fallback_chart


def list_latest_query_audits(
    *,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> List[Dict[str, Any]]:
    latest_by_request: Dict[str, Dict[str, Any]] = {}
    for payload in iter_query_audit_snapshots():
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            continue
        latest_by_request[request_id] = payload

    items = list(latest_by_request.values())
    if status:
        items = [item for item in items if str(item.get("status") or "").strip().lower() == status]
    if policy_decision:
        items = [
            item
            for item in items
            if str(item.get("policy_decision") or "").strip().lower() == policy_decision
        ]
    if fallback_mode:
        items = [item for item in items if matches_fallback_mode(item, fallback_mode)]

    return sorted(
        items,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )


def list_recent_query_audits(
    limit: int = 5,
    *,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> List[Dict[str, Any]]:
    items = list_latest_query_audits(
        fallback_mode=fallback_mode,
        status=status,
        policy_decision=policy_decision,
    )
    return items[:clamp_audit_limit(limit)]


def build_query_audit_summary(
    *,
    fallback_mode: Optional[str] = None,
    limit: int = 5,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> Dict[str, Any]:
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    recent_limit = clamp_audit_limit(limit, maximum=50)
    latest_items = list_latest_query_audits(
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )
    recent_items = latest_items[:recent_limit]

    status_counts: Dict[str, int] = {}
    policy_counts: Dict[str, int] = {}
    policy_reason_counts: Dict[str, int] = {}
    top_questions: Dict[str, Dict[str, Any]] = {}
    fallback_sql_count = 0
    fallback_chart_count = 0
    denied_count = 0
    review_count = 0
    error_count = 0

    for item in latest_items:
        item_status = str(item.get("status") or "unknown").strip().lower() or "unknown"
        item_policy = str(item.get("policy_decision") or "unknown").strip().lower() or "unknown"
        status_counts[item_status] = status_counts.get(item_status, 0) + 1
        policy_counts[item_policy] = policy_counts.get(item_policy, 0) + 1
        fallback_sql_count += 1 if item.get("fallback_sql_used") else 0
        fallback_chart_count += 1 if item.get("fallback_chart_used") else 0
        denied_count += 1 if item_policy == "deny" else 0
        review_count += 1 if item_policy == "review" else 0
        error_count += 1 if str(item.get("error") or "").strip() else 0
        for reason in item.get("policy_reasons") or []:
            normalized_reason = str(reason or "").strip().lower()
            if normalized_reason:
                policy_reason_counts[normalized_reason] = policy_reason_counts.get(normalized_reason, 0) + 1

        question = str(item.get("question") or "").strip()
        normalized_question = normalize_question(question)
        if not normalized_question:
            continue
        bucket = top_questions.setdefault(
            normalized_question,
            {
                "question": question,
                "normalized_question": normalized_question,
                "count": 0,
                "sample_request_ids": [],
            },
        )
        bucket["count"] += 1
        if len(bucket["sample_request_ids"]) < 3:
            bucket["sample_request_ids"].append(str(item.get("request_id") or "").strip())

    sorted_top_questions = sorted(
        top_questions.values(),
        key=lambda item: (-int(item["count"]), str(item["question"]).lower()),
    )[:5]
    top_policy_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(
            policy_reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]

    return {
        "schema": "nexus-hive-query-audit-summary-v1",
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": recent_limit,
        },
        "summary": {
            "total_requests": len(latest_items),
            "status_counts": status_counts,
            "policy_decision_counts": policy_counts,
            "fallback_sql_count": fallback_sql_count,
            "fallback_chart_count": fallback_chart_count,
            "denied_count": denied_count,
            "review_required_count": review_count,
            "error_count": error_count,
            "latest_updated_at": recent_items[0]["updated_at"] if recent_items else None,
        },
        "top_policy_reasons": top_policy_reasons,
        "top_questions": sorted_top_questions,
        "recent_items": recent_items,
        "watchouts": [
            "Query audit summary reflects the latest state per request_id, not every intermediate log line.",
            "Fallback counters separate resilience posture from model quality posture.",
            "Policy review and deny counts should be inspected before trusting a demo claim.",
        ],
    }


def build_query_review_board(
    *,
    fallback_mode: Optional[str] = None,
    limit: int = 5,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> Dict[str, Any]:
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    board_limit = clamp_audit_limit(limit)
    latest_items = list_latest_query_audits(
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )

    def item_priority(item: Dict[str, Any]) -> tuple[int, str]:
        item_status = str(item.get("status") or "").strip().lower()
        item_policy = str(item.get("policy_decision") or "").strip().lower()
        if item_status == "failed":
            rank = 0
        elif item_policy == "deny":
            rank = 1
        elif item_policy == "review":
            rank = 2
        elif item.get("fallback_sql_used") or item.get("fallback_chart_used"):
            rank = 3
        else:
            rank = 4
        return (rank, str(item.get("updated_at") or ""))

    attention_items = sorted(latest_items, key=item_priority)[:board_limit]
    healthy_items = [
        item
        for item in latest_items
        if str(item.get("status") or "").strip().lower() == "completed"
        and str(item.get("policy_decision") or "").strip().lower() == "allow"
    ][:board_limit]

    def to_board_item(item: Dict[str, Any]) -> Dict[str, Any]:
        item_status = str(item.get("status") or "").strip().lower() or "unknown"
        item_policy = str(item.get("policy_decision") or "").strip().lower() or "unknown"
        uses_fallback = bool(item.get("fallback_sql_used")) or bool(item.get("fallback_chart_used"))
        if item_status == "failed":
            next_action = "Inspect the audit detail and retry only after fixing the governed SQL path."
        elif item_policy == "deny":
            next_action = "Review deny reasons, remove blocked SQL patterns, and rerun the request."
        elif item_policy == "review":
            next_action = "Validate sensitive columns and escalation reasons before approval."
        elif uses_fallback:
            next_action = "Compare fallback output against the gold eval run before sharing the answer."
        else:
            next_action = "Spot-check SQL, chart payload, and row counts before sharing the answer."
        return {
            "request_id": str(item.get("request_id") or ""),
            "question": str(item.get("question") or ""),
            "status": item_status,
            "policy_decision": item_policy,
            "stage": str(item.get("stage") or ""),
            "updated_at": item.get("updated_at"),
            "fallback_mode": {
                "sql": bool(item.get("fallback_sql_used")),
                "chart": bool(item.get("fallback_chart_used")),
            },
            "row_count": int(item.get("row_count") or 0),
            "retry_count": int(item.get("retry_count") or 0),
            "policy_reasons": item.get("policy_reasons") or [],
            "next_action": next_action,
        }

    audit_summary = build_query_audit_summary(
        fallback_mode=fallback_filter,
        limit=board_limit,
        status=status_filter,
        policy_decision=policy_filter,
    )

    return {
        "schema": "nexus-hive-query-review-board-v1",
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": board_limit,
        },
        "summary": {
            "total_requests": audit_summary["summary"]["total_requests"],
            "attention_count": len(attention_items),
            "healthy_count": len(healthy_items),
            "latest_updated_at": audit_summary["summary"]["latest_updated_at"],
        },
        "attention_items": [to_board_item(item) for item in attention_items],
        "healthy_items": [to_board_item(item) for item in healthy_items],
        "policy_reasons": audit_summary["top_policy_reasons"],
        "review_actions": [
            "Start with failed or denied requests before reviewing successful output.",
            "Use /api/query-audit/{request_id} to inspect one request in detail.",
            "Use /api/policy/check before approving risky SQL changes.",
            "Run /api/evals/nl2sql-gold/run when fallback or review-required items appear.",
        ],
        "links": {
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": "/api/query-audit/{request_id}",
            "policy_check": "/api/policy/check",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
        },
    }


def build_query_session_board(
    *,
    fallback_mode: Optional[str] = None,
    limit: int = 6,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> Dict[str, Any]:
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    session_limit = clamp_audit_limit(limit)
    latest_items = list_latest_query_audits(
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )[:session_limit]

    def to_session_item(item: Dict[str, Any]) -> Dict[str, Any]:
        item_status = str(item.get("status") or "").strip().lower() or "unknown"
        item_policy = str(item.get("policy_decision") or "").strip().lower() or "unknown"
        uses_fallback = bool(item.get("fallback_sql_used")) or bool(item.get("fallback_chart_used"))
        if item_status == "failed" or item_policy == "deny":
            session_state = "attention"
            next_action = "Reopen audit detail, fix the SQL path, and rerun before sharing."
        elif item_policy == "review":
            session_state = "review"
            next_action = "Check escalation reasons and sensitive columns before approval."
        elif uses_fallback:
            session_state = "compare"
            next_action = "Compare fallback output against the gold eval run before reuse."
        else:
            session_state = "ready"
            next_action = "Spot-check SQL and row counts, then reuse this session as a reference."

        request_id = str(item.get("request_id") or "").strip()
        return {
            "request_id": request_id,
            "headline": str(item.get("question") or "Saved query session"),
            "status": item_status,
            "policy_decision": item_policy,
            "session_state": session_state,
            "updated_at": item.get("updated_at"),
            "row_count": int(item.get("row_count") or 0),
            "retry_count": int(item.get("retry_count") or 0),
            "chart_type": str(item.get("chart_type") or "").strip() or None,
            "fallback_mode": {
                "sql": bool(item.get("fallback_sql_used")),
                "chart": bool(item.get("fallback_chart_used")),
            },
            "review_url": f"/api/query-audit/{request_id}",
            "next_action": next_action,
        }

    session_items = [to_session_item(item) for item in latest_items]
    return {
        "schema": QUERY_SESSION_BOARD_SCHEMA,
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": session_limit,
        },
        "summary": {
            "total_sessions": len(session_items),
            "ready_count": sum(1 for item in session_items if item["session_state"] == "ready"),
            "attention_count": sum(1 for item in session_items if item["session_state"] == "attention"),
            "review_count": sum(1 for item in session_items if item["session_state"] == "review"),
            "compare_count": sum(1 for item in session_items if item["session_state"] == "compare"),
            "latest_updated_at": session_items[0]["updated_at"] if session_items else None,
        },
        "items": session_items,
        "review_actions": [
            "Open the saved session detail before reusing a generated chart or answer.",
            "Keep attention and review sessions visible until their policy issues are resolved.",
            "Promote ready sessions only after a quick SQL and row-count check.",
        ],
        "links": {
            "query_session_board": "/api/query-session-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": "/api/query-audit/{request_id}",
        },
    }


def normalize_governance_focus(focus: Optional[str]) -> str:
    normalized = str(focus or "").strip().lower()
    if not normalized:
        return "quality"
    if normalized not in GOVERNANCE_SCORECARD_FOCUS_VALUES:
        raise HTTPException(status_code=400, detail="invalid governance focus")
    return normalized


def build_governance_scorecard(focus: str = "quality") -> Dict[str, Any]:
    normalized_focus = normalize_governance_focus(focus)
    db_ready = DB_PATH.exists() and bool(DB_SCHEMA.strip())
    quality_gate = build_quality_gate()
    gold_eval_run = run_gold_eval_suite()
    audit_summary = build_query_audit_summary(limit=10)
    persisted = build_runtime_store_summary(10)
    latest_items = list_latest_query_audits()
    fallback_any_count = len(list_latest_query_audits(fallback_mode="any"))
    denied_items = list_recent_query_audits(limit=3, policy_decision="deny")
    review_items = list_recent_query_audits(limit=3, policy_decision="review")
    failed_items = list_recent_query_audits(limit=3, status="failed")
    total_requests = int(audit_summary["summary"]["total_requests"])
    gold_case_count = int(gold_eval_run["summary"]["case_count"])
    gold_pass_count = int(gold_eval_run["summary"]["pass_count"])
    quality_failures = len(quality_gate["failed_checks"])
    review_required_count = int(audit_summary["summary"]["review_required_count"])
    denied_count = int(audit_summary["summary"]["denied_count"])
    error_count = int(audit_summary["summary"]["error_count"])
    fallback_rate_pct = round((fallback_any_count / total_requests) * 100, 1) if total_requests else 0.0
    guarded_rate_pct = (
        round(((review_required_count + denied_count) / total_requests) * 100, 1)
        if total_requests
        else 0.0
    )
    gold_eval_pass_rate_pct = round((gold_pass_count / gold_case_count) * 100, 1) if gold_case_count else 0.0
    error_rate_pct = round((error_count / total_requests) * 100, 1) if total_requests else 0.0

    score_bands = [
        {
            "id": "query-safety",
            "label": "Query safety",
            "score_pct": max(0.0, round(100.0 - error_rate_pct - quality_failures * 5, 1)),
            "signal": "strong" if denied_count + review_required_count > 0 else "watch",
            "evidence": "policy previews, deny rules, review-required counts",
        },
        {
            "id": "resilience",
            "label": "Resilience",
            "score_pct": max(0.0, round(100.0 - error_rate_pct, 1)),
            "signal": "strong" if error_count == 0 else "watch",
            "evidence": "fallback ratio and runtime error rate",
        },
        {
            "id": "quality",
            "label": "Quality",
            "score_pct": gold_eval_pass_rate_pct,
            "signal": "strong" if quality_gate["status"] == "ok" and gold_eval_pass_rate_pct >= 75 else "watch",
            "evidence": "gold eval run + modeled table quality gate",
        },
        {
            "id": "throughput",
            "label": "Throughput",
            "score_pct": min(100.0, float(total_requests) * 10.0),
            "signal": "strong" if total_requests >= 3 else "watch",
            "evidence": "query audit volume and latest request activity",
        },
    ]

    if normalized_focus == "policy":
        spotlight = {
            "headline": "Policy posture surfaces the main approval reasons before governed analytics claims are made.",
            "top_policy_reasons": audit_summary["top_policy_reasons"],
            "recent_denied": denied_items,
            "recent_review_required": review_items,
        }
    elif normalized_focus == "resilience":
        spotlight = {
            "headline": "Resilience posture keeps fallback and runtime error pressure visible before demos.",
            "fallback_any_count": fallback_any_count,
            "error_rate_pct": error_rate_pct,
            "recent_failed": failed_items,
        }
    elif normalized_focus == "throughput":
        spotlight = {
            "headline": "Throughput posture shows current audit volume and the latest governed questions.",
            "total_requests": total_requests,
            "latest_requests": latest_items[:5],
        }
    else:
        spotlight = {
            "headline": "Quality posture ties gold eval readiness, modeled-table integrity, and audit hygiene together.",
            "gold_eval_failures": gold_case_count - gold_pass_count,
            "quality_gate_failures": quality_gate["failed_checks"],
            "recent_quality_reviews": review_items,
        }

    recommendations = [
        None if db_ready else "Seed the warehouse and verify schema load before judging governed analytics quality.",
        None if quality_gate["status"] == "ok" else "Resolve modeled-table quality gate failures before claiming governed SQL readiness.",
        None if gold_eval_pass_rate_pct >= 75 else "Improve NL2SQL heuristics or prompt quality until the gold eval pass rate clears 75%.",
        None if denied_count + review_required_count > 0 else "Exercise /api/policy/check with risky SQL so the policy boundary remains visible.",
        None if error_count == 0 else "Inspect failed audit items before relying on live SSE walkthroughs during demos.",
    ]

    return {
        "status": "ok" if db_ready else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": GOVERNANCE_SCORECARD_SCHEMA,
        "focus": normalized_focus,
        "summary": {
            "db_ready": db_ready,
            "warehouse_mode": "sqlite-demo",
            "fallback_mode": "heuristic" if ALLOW_HEURISTIC_FALLBACK else "disabled",
            "quality_gate_status": quality_gate["status"],
            "quality_gate_failures": quality_failures,
            "total_requests": total_requests,
            "guarded_rate_pct": guarded_rate_pct,
            "fallback_rate_pct": fallback_rate_pct,
            "error_rate_pct": error_rate_pct,
            "gold_eval_pass_rate_pct": gold_eval_pass_rate_pct,
            "latest_updated_at": audit_summary["summary"]["latest_updated_at"],
            "persisted_event_count": persisted["persisted_count"],
        },
        "persistence": persisted,
        "operator_auth": {
            **operator_auth_status(),
            "protected_routes": ["/api/ask", "/api/policy/check"],
        },
        "score_bands": score_bands,
        "spotlight": spotlight,
        "recommendations": [item for item in recommendations if item],
        "links": {
            "health": "/health",
            "meta": "/api/meta",
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "auth_session": "/api/auth/session",
            "review_pack": "/api/review-pack",
            "policy_check": "/api/policy/check",
            "query_session_board": "/api/query-session-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
            "governance_scorecard": "/api/runtime/governance-scorecard",
        },
    }


def get_query_audit_history(request_id: str) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    for payload in iter_query_audit_snapshots():
        if str(payload.get("request_id") or "").strip() == request_id:
            history.append(payload)

    return sorted(history, key=lambda item: item.get("updated_at", ""))


def build_warehouse_brief() -> Dict[str, Any]:
    table_profiles = build_table_profiles()
    quality_gate = build_quality_gate()
    date_window = fetch_date_window()
    recent_audits = list_recent_query_audits(limit=5)
    gold_eval = build_gold_eval_pack()
    gold_eval_run = run_gold_eval_suite()
    policy_schema = build_policy_schema()

    return {
        "status": "ok" if quality_gate["status"] == "ok" else "degraded",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "readiness_contract": "nexus-hive-warehouse-brief-v1",
        "headline": "Governed analytics brief tying warehouse mode, lineage, quality gate, and audit trail into one reviewable surface.",
        "warehouse_mode": "sqlite-demo",
        "fallback_mode": "heuristic" if ALLOW_HEURISTIC_FALLBACK else "disabled",
        "adapter_contracts": WAREHOUSE_ADAPTERS,
        "table_profiles": table_profiles,
        "date_window": date_window,
        "quality_gate": quality_gate,
        "lineage": build_lineage_schema(),
        "policy": policy_schema,
        "gold_eval": gold_eval,
        "gold_eval_run": gold_eval_run,
        "recent_audit_count": len(recent_audits),
        "audit_summary": build_query_audit_summary(limit=5),
        "policy_examples": [
            "read_only_sql_only",
            "aggregates_before_operator_approval",
            "trace_sql_before_chart_trust",
            "sensitive_columns_require_role_escalation",
        ],
        "routes": [
            "/api/runtime/warehouse-brief",
            "/api/schema/lineage",
            "/api/schema/policy",
            "/api/schema/query-audit",
            "/api/evals/nl2sql-gold",
            "/api/query-session-board",
            "/api/query-review-board",
            "/api/query-audit/summary",
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
    fallback_sql_used: bool
    fallback_chart_used: bool
    policy_verdict: Dict[str, Any]
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
    sql = ""
    try:
        sql_response = await ask_ollama(prompt)
        sql = sql_response.strip().replace("```sql", "").replace("```", "").strip()
    except Exception as exc:
        state["log_stream"].append(f"[Agent 1: Translator] ⚠️ Ollama unavailable: {exc}")

    if not sql and ALLOW_HEURISTIC_FALLBACK:
        sql = infer_sql_from_question(state["user_query"])
        state["fallback_sql_used"] = True
        state["log_stream"].append("[Agent 1: Translator] ⚠️ Heuristic SQL fallback engaged.")

    state["sql_query"] = sql
    state["log_stream"].append(f"[Agent 1: Translator] Generated SQL:\n{sql}")
    return state

# --- Node 2: Data Executor ---
def executor_node(state: AgentState) -> AgentState:
    sql = state["sql_query"]
    state["log_stream"].append(f"[Agent 2: Executor] Auditing and executing SQL against nexus_enterprise.db...")

    policy = evaluate_sql_policy(sql)
    state["policy_verdict"] = policy
    if policy["decision"] == "deny":
        state["error"] = f"Policy denied query: {', '.join(policy['deny_reasons'])}"
        state["log_stream"].append(f"[Agent 2: Executor] ❌ ERROR: {state['error']}")
        return state
    if policy["review_reasons"]:
        state["log_stream"].append(
            f"[Agent 2: Executor] ⚠️ Review required: {', '.join(policy['review_reasons'])}"
        )

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
    config_response = ""
    try:
        config_response = await ask_ollama(prompt)
        clean_json = config_response.strip().replace("```json", "").replace("```", "").strip()
        config = json.loads(clean_json)
        state["chart_config"] = config
        state["log_stream"].append(f"[Agent 3: Visualizer] ✅ Generated Chart.js config: {config['type'].upper()} Chart.")
    except Exception as exc:
        if exc:
            state["log_stream"].append(f"[Agent 3: Visualizer] ⚠️ LLM chart config unavailable: {exc}")
        state["chart_config"] = infer_chart_config_from_question(state["user_query"], state["db_result"])
        state["fallback_chart_used"] = True
        state["log_stream"].append(f"[Agent 3: Visualizer] ⚠️ Heuristic chart config used.")
        
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


@app.middleware("http")
async def session_and_logging_middleware(request: Request, call_next):
    request_id = str(request.headers.get("x-request-id") or uuid4().hex[:12]).strip()
    request.state.request_id = request_id
    request.state.operator_session = apply_operator_session(request)
    started = datetime.now(timezone.utc)
    try:
        response = await call_next(request)
    except Exception as error:
        elapsed_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        log_runtime_event(
            "error",
            "request-failed",
            elapsed_ms=elapsed_ms,
            error=str(error),
            method=request.method,
            operator_auth_mode=(request.state.operator_session or {}).get("auth_mode")
            if hasattr(request.state, "operator_session")
            else None,
            operator_roles=(request.state.operator_session or {}).get("roles", [])
            if hasattr(request.state, "operator_session")
            else [],
            path=request.url.path,
            request_id=request_id,
        )
        raise

    response.headers["x-request-id"] = request_id
    response.headers["cache-control"] = "no-store"
    elapsed_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    log_runtime_event(
        "warn" if response.status_code >= 400 or elapsed_ms >= 4000 else "info",
        "request-finished",
        elapsed_ms=elapsed_ms,
        method=request.method,
        operator_auth_mode=(request.state.operator_session or {}).get("auth_mode")
        if hasattr(request.state, "operator_session")
        else None,
        operator_roles=(request.state.operator_session or {}).get("roles", [])
        if hasattr(request.state, "operator_session")
        else [],
        path=request.url.path,
        request_id=request_id,
        session_active=bool(getattr(request.state, "operator_session", None)),
        status_code=response.status_code,
    )
    return response


def build_runtime_meta() -> Dict[str, Any]:
    db_exists = DB_PATH.exists()
    db_size_bytes = DB_PATH.stat().st_size if db_exists else 0
    schema_loaded = bool(DB_SCHEMA.strip())
    warehouse_brief = build_warehouse_brief()
    runtime_persistence = build_runtime_store_summary(5)
    diagnostics = {
        "db_ready": db_exists and schema_loaded,
        "db_size_bytes": db_size_bytes,
        "schema_loaded": schema_loaded,
        "ollama_configured": OLLAMA_URL.startswith("http"),
        "warehouse_mode": warehouse_brief["warehouse_mode"],
        "fallback_mode": warehouse_brief["fallback_mode"],
        "quality_gate_status": warehouse_brief["quality_gate"]["status"],
        "recent_audit_count": warehouse_brief["recent_audit_count"],
        "runtime_event_count": runtime_persistence["persisted_count"],
        "next_action": (
            "POST /api/ask with an executive question, then follow the returned /api/stream URL."
            if db_exists and schema_loaded and (OLLAMA_URL.startswith("http") or ALLOW_HEURISTIC_FALLBACK)
            else "Run `python3 seed_db.py` and verify either Ollama or heuristic fallback is enabled before live demos."
        ),
    }
    return {
        "service": "nexus-hive",
        "model": MODEL_NAME,
        "ollama_url": OLLAMA_URL,
        "db_path": str(DB_PATH),
        "diagnostics": diagnostics,
        "auth": {
            "operator_token_enabled": operator_token_enabled(),
            "operator_required_roles": operator_auth_status()["required_roles"],
            "operator_role_headers": operator_role_headers(),
            "operator_session_cookie": operator_session_cookie_name(),
        },
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
            "/api/runtime/governance-scorecard",
            "/api/auth/session",
            "/api/review-pack",
            "/api/schema/answer",
            "/api/schema/lineage",
            "/api/schema/policy",
            "/api/schema/query-audit",
            "/api/evals/nl2sql-gold",
            "/api/evals/nl2sql-gold/run",
            "/api/policy/check",
            "/api/query-session-board",
            "/api/query-review-board",
            "/api/query-audit/summary",
            "/api/query-audit/recent",
            "/api/query-audit/{request_id}",
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
            "policy-schema-surface",
            "query-audit-surface",
            "gold-eval-surface",
            "policy-preview-surface",
            "query-session-board-surface",
            "query-review-board-surface",
            "query-audit-summary-surface",
            "query-audit-detail-surface",
            "governance-scorecard-surface",
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
    governance_scorecard = build_governance_scorecard("quality")
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
            "fallback_mode": warehouse_brief["fallback_mode"],
            "quality_gate_schema": warehouse_brief["quality_gate"]["schema"],
            "lineage_schema": warehouse_brief["lineage"]["schema"],
            "policy_schema": warehouse_brief["policy"]["schema"],
            "query_audit_schema": build_query_audit_schema()["schema"],
            "query_session_board_schema": QUERY_SESSION_BOARD_SCHEMA,
            "query_review_board_schema": build_query_review_board()["schema"],
            "query_audit_summary_schema": warehouse_brief["audit_summary"]["schema"],
            "governance_scorecard_schema": GOVERNANCE_SCORECARD_SCHEMA,
            "gold_eval_schema": warehouse_brief["gold_eval"]["schema"],
            "gold_eval_run_schema": warehouse_brief["gold_eval_run"]["schema"],
            "operator_auth_enabled": operator_token_enabled(),
            "operator_required_roles": operator_auth_status()["required_roles"],
            "runtime_persistence_enabled": governance_scorecard["persistence"]["enabled"],
        },
        "review_flow": [
            "Open /health to confirm database and model posture.",
            "Read /api/runtime/warehouse-brief for adapter mode, lineage, and quality-gate posture.",
            "Read /api/runtime/brief for agent contract, retry policy, and reviewer guidance.",
            "Open /api/query-session-board to revisit saved analyst sessions before re-running a question.",
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
    governance_scorecard = build_governance_scorecard("quality")
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
            "gold_eval_pass_count": warehouse_brief["gold_eval_run"]["summary"]["pass_count"],
            "runtime_event_count": governance_scorecard["persistence"]["persisted_count"],
            "review_routes": [
                "/health",
                "/api/meta",
                "/api/runtime/brief",
                "/api/runtime/warehouse-brief",
                "/api/runtime/governance-scorecard",
                "/api/review-pack",
                "/api/schema/answer",
                "/api/schema/lineage",
                "/api/schema/policy",
                "/api/schema/query-audit",
                "/api/evals/nl2sql-gold",
                "/api/evals/nl2sql-gold/run",
                "/api/policy/check",
                "/api/query-session-board",
                "/api/query-review-board",
                "/api/query-audit/summary",
                "/api/query-audit/recent",
                "/api/query-audit/{request_id}",
                "/api/ask",
                "/api/stream",
            ],
        },
        "executive_promises": [
            "Every answer keeps the SQL layer visible before the chart layer.",
            "Unsafe write operations are blocked before execution.",
            "The agent trace remains inspectable through SSE rather than hidden behind a single response blob.",
            "Warehouse lineage, quality checks, and query audit stay reviewable before the chart is trusted.",
            "If Ollama is unavailable, deterministic fallback keeps the review path alive with explicit logging.",
        ],
        "trust_boundary": [
            "translator: natural language becomes SQL only through warehouse schema context",
            "executor: read-only SQL enforcement blocks destructive operations",
            "visualizer: chart payload is inferred from actual result shape",
            "warehouse brief: lineage and quality gate stay visible before approval",
            "policy: wildcard projections and sensitive columns are denied before execution",
            "stream: reviewer can audit the agent trace before trusting the rendered chart",
        ],
        "review_sequence": [
            "Open /health to confirm warehouse and model posture.",
            "Read /api/runtime/warehouse-brief for data contracts, lineage, and quality gates.",
            "Read /api/evals/nl2sql-gold for the canonical review set and fallback verdicts.",
            "Use /api/policy/check to preview SQL before execution when reviewing risky changes.",
            "Use /api/query-session-board to reopen reusable governed query sessions before re-running them.",
            "Read /api/runtime/brief for retry policy and agent responsibilities.",
            "Read /api/review-pack for executive promises, trust boundary, and review routes.",
            "Use /api/query-review-board to prioritize failed, denied, and review-required requests before trusting output.",
            "Use /api/ask, /api/stream, /api/query-audit/recent, and /api/query-audit/{request_id} together before trusting a dashboard answer.",
        ],
        "two_minute_review": [
            "Open /health to confirm database posture and review links.",
            "Read /api/runtime/warehouse-brief for quality-gate, lineage, and policy posture.",
            "Read /api/evals/nl2sql-gold/run before making correctness claims.",
            "Open /api/query-session-board to inspect reusable governed sessions.",
            "Open /api/query-review-board to inspect current governed analytics risks.",
            "Use /api/ask plus /api/query-audit/{request_id} to inspect one governed answer end to end.",
        ],
        "proof_assets": [
            {"label": "Health Surface", "href": "/health", "kind": "route"},
            {"label": "Warehouse Brief", "href": "/api/runtime/warehouse-brief", "kind": "route"},
            {"label": "Governance Scorecard", "href": "/api/runtime/governance-scorecard", "kind": "route"},
            {"label": "Query Session Board", "href": "/api/query-session-board", "kind": "route"},
            {"label": "Query Review Board", "href": "/api/query-review-board", "kind": "route"},
            {"label": "Gold Eval Run", "href": "/api/evals/nl2sql-gold/run", "kind": "route"},
            {"label": "Query Audit Detail", "href": "/api/query-audit/{request_id}", "kind": "route"},
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
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "auth_session": "/api/auth/session",
            "review_pack": "/api/review-pack",
            "answer_schema": "/api/schema/answer",
            "lineage_schema": "/api/schema/lineage",
            "policy_schema": "/api/schema/policy",
            "query_audit_schema": "/api/schema/query-audit",
            "query_session_board": "/api/query-session-board",
            "query_review_board": "/api/query-review-board",
            "gold_eval": "/api/evals/nl2sql-gold",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
            "policy_check": "/api/policy/check",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": "/api/query-audit/{request_id}",
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
        "fallback_sql_used": False,
        "fallback_chart_used": False,
        "policy_verdict": {},
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
            policy_decision=state.get("policy_verdict", {}).get("decision", ""),
            policy_reasons=state.get("policy_verdict", {}).get("deny_reasons", [])
            + state.get("policy_verdict", {}).get("review_reasons", []),
            fallback_sql_used=state.get("fallback_sql_used", False),
            fallback_chart_used=state.get("fallback_chart_used", False),
        )
        append_runtime_event(
            {
                "service": "nexus-hive",
                "event_type": "stream_failed",
                "method": "GET",
                "path": "/api/stream",
                "request_id": request_id,
                "status": "failed",
                "policy_decision": state.get("policy_verdict", {}).get("decision", ""),
                "fallback_sql_used": state.get("fallback_sql_used", False),
                "fallback_chart_used": state.get("fallback_chart_used", False),
                "at": utc_now_iso(),
            }
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
            policy_decision=state.get("policy_verdict", {}).get("decision", ""),
            policy_reasons=state.get("policy_verdict", {}).get("deny_reasons", [])
            + state.get("policy_verdict", {}).get("review_reasons", []),
            fallback_sql_used=state.get("fallback_sql_used", False),
            fallback_chart_used=state.get("fallback_chart_used", False),
        )
        append_runtime_event(
            {
                "service": "nexus-hive",
                "event_type": "stream_completed",
                "method": "GET",
                "path": "/api/stream",
                "request_id": request_id,
                "status": "completed",
                "policy_decision": state.get("policy_verdict", {}).get("decision", ""),
                "fallback_sql_used": state.get("fallback_sql_used", False),
                "fallback_chart_used": state.get("fallback_chart_used", False),
                "at": utc_now_iso(),
            }
        )

    yield "data: {\"type\": \"done\"}\n\n"

class AskRequest(BaseModel):
    question: str


class PolicyCheckRequest(BaseModel):
    sql: str
    role: str = DEFAULT_ROLE


@app.get("/health")
async def health_endpoint():
    runtime_meta = build_runtime_meta()
    return {
        "status": "ok" if runtime_meta["diagnostics"]["db_ready"] else "degraded",
        "links": {
            "meta": "/api/meta",
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "governance_scorecard": "/api/runtime/governance-scorecard",
            "auth_session": "/api/auth/session",
            "review_pack": "/api/review-pack",
            "answer_schema": "/api/schema/answer",
            "lineage_schema": "/api/schema/lineage",
            "policy_schema": "/api/schema/policy",
            "query_audit_schema": "/api/schema/query-audit",
            "gold_eval": "/api/evals/nl2sql-gold",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
            "policy_check": "/api/policy/check",
            "query_session_board": "/api/query-session-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": "/api/query-audit/{request_id}",
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
        "governance_scorecard_contract": GOVERNANCE_SCORECARD_SCHEMA,
        "review_pack_contract": "nexus-hive-review-pack-v1",
        "report_contract": build_answer_schema(),
        "lineage_contract": build_lineage_schema()["schema"],
        "policy_contract": build_policy_schema()["schema"],
        "query_audit_contract": build_query_audit_schema()["schema"],
        "query_session_board_contract": QUERY_SESSION_BOARD_SCHEMA,
        "query_review_board_contract": build_query_review_board()["schema"],
        "query_audit_summary_contract": build_query_audit_summary()["schema"],
        "gold_eval_contract": build_gold_eval_pack()["schema"],
        **runtime_meta,
    }


@app.get("/api/runtime/brief")
async def runtime_brief_endpoint():
    return build_runtime_brief()


@app.get("/api/runtime/warehouse-brief")
async def warehouse_brief_endpoint():
    return build_warehouse_brief()


@app.get("/api/runtime/governance-scorecard")
async def governance_scorecard_endpoint(focus: Optional[str] = None):
    normalized_focus = normalize_governance_focus(focus)
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "scorecard_view",
            "method": "GET",
            "path": "/api/runtime/governance-scorecard",
            "status": "ok",
            "focus": normalized_focus,
            "at": utc_now_iso(),
        }
    )
    return build_governance_scorecard(normalized_focus)


@app.get("/api/auth/session")
async def auth_session_endpoint(request: Request):
    session = read_operator_session(request)
    validation = None
    if session:
        try:
            require_operator_token(request)
            validation = {"ok": True, "reason": None}
        except HTTPException as error:
            validation = {"ok": False, "reason": error.detail}
    return {
        "ok": True,
        "active": bool(session and validation and validation["ok"]),
        "cookie_name": operator_session_cookie_name(),
        "session": session,
        "validation": validation,
    }


@app.post("/api/auth/session")
async def create_auth_session(request: Request, response: Response):
    if not operator_token_enabled():
        raise HTTPException(status_code=409, detail="operator auth is not configured for session login")

    payload = await request.json()
    credential = str(payload.get("credential") or "").strip() if isinstance(payload, dict) else ""
    roles = normalize_operator_roles(payload.get("roles")) if isinstance(payload, dict) else []
    if not credential:
        raise HTTPException(status_code=400, detail="missing credential")

    expected = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
    if credential != expected:
        raise HTTPException(status_code=403, detail="missing or invalid operator token")

    allowed_roles = operator_allowed_roles()
    if allowed_roles and not any(role in allowed_roles for role in roles):
        raise HTTPException(status_code=403, detail="missing required operator role")

    cookie, session = create_operator_session_cookie(
        credential=credential,
        roles=roles or allowed_roles,
        subject="token-operator",
    )
    response.headers["set-cookie"] = cookie
    log_runtime_event(
        "info",
        "operator-session-created",
        request_id=getattr(request.state, "request_id", None),
        roles=session["roles"],
        subject=session["subject"],
    )
    return {
        "ok": True,
        "active": True,
        "cookie_name": operator_session_cookie_name(),
        "session": session,
    }


@app.delete("/api/auth/session")
async def clear_auth_session(request: Request, response: Response):
    response.headers["set-cookie"] = clear_operator_session_cookie()
    log_runtime_event(
        "info",
        "operator-session-cleared",
        request_id=getattr(request.state, "request_id", None),
    )
    return {
        "ok": True,
        "active": False,
        "cookie_name": operator_session_cookie_name(),
    }


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


@app.get("/api/schema/policy")
async def policy_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_policy_schema(),
    }


@app.get("/api/schema/query-audit")
async def query_audit_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_audit_schema(),
    }


@app.get("/api/evals/nl2sql-gold")
async def gold_eval_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_gold_eval_pack(),
    }


@app.get("/api/evals/nl2sql-gold/run")
async def gold_eval_run_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **run_gold_eval_suite(),
    }


@app.post("/api/policy/check")
async def policy_check_endpoint(req: PolicyCheckRequest, request: Request):
    require_operator_token(request)
    sql = str(req.sql or "").strip()
    role = str(req.role or DEFAULT_ROLE).strip().lower() or DEFAULT_ROLE
    if not sql:
        raise HTTPException(status_code=400, detail="sql is required")
    verdict = evaluate_sql_policy(sql, role=role)
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "policy_check",
            "method": "POST",
            "path": "/api/policy/check",
            "status": "ok",
            "role": role,
            "policy_decision": verdict["decision"],
            "at": utc_now_iso(),
        }
    )
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_policy_schema()["schema"],
        "sql": sql,
        "verdict": verdict,
    }


@app.get("/api/query-audit/summary")
async def query_audit_summary_endpoint(
    limit: int = 5,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_audit_summary(
            fallback_mode=fallback_mode,
            limit=limit,
            status=status,
            policy_decision=policy_decision,
        ),
    }


@app.get("/api/query-review-board")
async def query_review_board_endpoint(
    limit: int = 5,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_review_board(
            fallback_mode=fallback_mode,
            limit=limit,
            status=status,
            policy_decision=policy_decision,
        ),
    }


@app.get("/api/query-session-board")
async def query_session_board_endpoint(
    limit: int = 6,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_session_board(
            fallback_mode=fallback_mode,
            limit=limit,
            status=status,
            policy_decision=policy_decision,
        ),
    }


@app.get("/api/query-audit/recent")
async def query_audit_recent_endpoint(
    limit: int = 5,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
):
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    items = list_recent_query_audits(
        limit=limit,
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_query_audit_schema()["schema"],
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": clamp_audit_limit(limit),
        },
        "items": items,
    }


@app.get("/api/query-audit/{request_id}")
async def query_audit_detail_endpoint(request_id: str):
    history = get_query_audit_history(request_id)
    if not history:
        raise HTTPException(status_code=404, detail="request_id not found")

    latest = history[-1]
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        "schema": build_query_audit_schema()["schema"],
        "request_id": request_id,
        "latest": latest,
        "history": history,
    }


@app.post("/api/ask")
async def ask_endpoint(req: AskRequest, request: Request):
    require_operator_token(request)
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
        policy_decision="pending",
        policy_reasons=[],
        fallback_sql_used=False,
        fallback_chart_used=False,
    )
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "ask_accepted",
            "method": "POST",
            "path": "/api/ask",
            "request_id": request_id,
            "status": "accepted",
            "question": question,
            "at": utc_now_iso(),
        }
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
            "gold_eval": str(request.url_for("gold_eval_endpoint")),
            "query_session_board": str(request.url_for("query_session_board_endpoint")),
            "query_audit_summary": str(request.url_for("query_audit_summary_endpoint")),
            "query_audit_recent": str(request.url_for("query_audit_recent_endpoint")),
            "query_audit_detail": str(request.url_for("query_audit_detail_endpoint", request_id=request_id)),
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
