"""
Shared configuration, constants, and utility functions for Nexus-Hive.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

BASE_DIR = Path(__file__).resolve().parent
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
QUERY_TAG_SCHEMA = "nexus-hive-query-tag-v1"
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
METRIC_LAYER_DEFINITIONS = [
    {
        "metric_id": "net_revenue",
        "label": "Net Revenue",
        "sql_expression": "SUM(sales.net_revenue)",
        "grain": "transaction_id",
        "owner": "finance-analytics",
        "certified": True,
        "default_dimensions": ["region_name", "category", "month"],
    },
    {
        "metric_id": "gross_revenue",
        "label": "Gross Revenue",
        "sql_expression": "SUM(sales.gross_revenue)",
        "grain": "transaction_id",
        "owner": "finance-analytics",
        "certified": True,
        "default_dimensions": ["region_name", "category", "month"],
    },
    {
        "metric_id": "profit",
        "label": "Profit",
        "sql_expression": "SUM(sales.profit)",
        "grain": "transaction_id",
        "owner": "finance-analytics",
        "certified": True,
        "default_dimensions": ["region_name", "category", "month"],
    },
    {
        "metric_id": "average_discount",
        "label": "Average Discount",
        "sql_expression": "AVG(sales.discount_applied)",
        "grain": "transaction_id",
        "owner": "pricing-ops",
        "certified": False,
        "default_dimensions": ["category", "month"],
    },
    {
        "metric_id": "units_sold",
        "label": "Units Sold",
        "sql_expression": "SUM(sales.quantity)",
        "grain": "transaction_id",
        "owner": "supply-analytics",
        "certified": True,
        "default_dimensions": ["region_name", "category", "product_name"],
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
QUERY_APPROVAL_BOARD_SCHEMA = "nexus-hive-query-approval-board-v1"
WAREHOUSE_TARGET_SCORECARD_SCHEMA = "nexus-hive-warehouse-target-scorecard-v1"
SEMANTIC_GOVERNANCE_PACK_SCHEMA = "nexus-hive-semantic-governance-pack-v1"
LAKEHOUSE_READINESS_PACK_SCHEMA = "nexus-hive-lakehouse-readiness-pack-v1"
REVIEWER_QUERY_DEMO_SCHEMA = "nexus-hive-reviewer-query-demo-v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_PUBLIC_DEFAULT_MODEL = "gpt-4.1-mini"
OPENAI_PUBLIC_DEFAULT_DAILY_BUDGET_USD = 4.0
OPENAI_PUBLIC_DEFAULT_MONTHLY_BUDGET_USD = 120.0
OPENAI_PUBLIC_DEFAULT_RPM = 6
OPENAI_TIMEOUT_S = 20.0
REVIEWER_QUERY_SCENARIOS = {
    "revenue-by-region": {
        "question": "Show total net revenue by region",
        "sql": (
            "SELECT regions.region_name, SUM(sales.net_revenue) AS total_net_revenue "
            "FROM sales JOIN regions ON sales.region_id = regions.region_id "
            "GROUP BY regions.region_name ORDER BY total_net_revenue DESC"
        ),
        "metric_ids": ["net_revenue"],
        "warehouse_target": "snowflake-sql-contract",
        "approval_posture": "allow",
        "next_review_path": "/api/runtime/semantic-governance-pack",
        "estimated_cost_usd": 0.011,
    },
    "profit-top-regions": {
        "question": "Show top 5 regions by total profit",
        "sql": (
            "SELECT regions.region_name, SUM(sales.profit) AS total_profit "
            "FROM sales JOIN regions ON sales.region_id = regions.region_id "
            "GROUP BY regions.region_name ORDER BY total_profit DESC LIMIT 5"
        ),
        "metric_ids": ["profit"],
        "warehouse_target": "databricks-sql-contract",
        "approval_posture": "review",
        "next_review_path": "/api/runtime/lakehouse-readiness-pack",
        "estimated_cost_usd": 0.012,
    },
}

# Mutable global state
LAST_OPENAI_LIVE_RUN_AT: Optional[str] = None
OPENAI_REVIEWER_RATE_BUCKETS: Dict[str, Dict[str, float]] = {}


def get_db_schema():
    from warehouse_adapter import get_active_warehouse_adapter
    return get_active_warehouse_adapter().get_schema(DB_PATH)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_bool_env(name: str, fallback: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return fallback
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return fallback


def read_usd_env(name: str, fallback: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return fallback
    try:
        value = float(raw)
    except ValueError:
        return fallback
    return round(max(0.0, value), 2)


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


def normalize_question(question: str) -> str:
    return " ".join(str(question or "").strip().lower().split())


def build_openai_runtime_contract() -> Dict[str, Any]:
    api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
    kill_switch = read_bool_env("OPENAI_KILL_SWITCH", False)
    daily_budget = read_usd_env(
        "OPENAI_PUBLIC_DAILY_BUDGET_USD", OPENAI_PUBLIC_DEFAULT_DAILY_BUDGET_USD
    )
    monthly_budget = read_usd_env(
        "OPENAI_PUBLIC_MONTHLY_BUDGET_USD", OPENAI_PUBLIC_DEFAULT_MONTHLY_BUDGET_USD
    )
    public_live_api = bool(api_key) and not kill_switch and daily_budget > 0 and monthly_budget > 0
    return {
        "api_key": api_key,
        "deploymentMode": "public-capped-live" if public_live_api else "review-only-live",
        "publicLiveApi": public_live_api,
        "liveModel": str(os.getenv("OPENAI_MODEL_PUBLIC", "")).strip()
        or OPENAI_PUBLIC_DEFAULT_MODEL,
        "refreshModel": str(os.getenv("OPENAI_MODEL_REFRESH", "")).strip() or "gpt-5.2",
        "dailyBudgetUsd": daily_budget,
        "monthlyBudgetUsd": monthly_budget,
        "killSwitch": kill_switch,
        "moderationEnabled": read_bool_env("OPENAI_MODERATION_ENABLED", True),
        "publicRpm": max(
            1,
            min(
                120,
                int(str(os.getenv("OPENAI_PUBLIC_RPM", OPENAI_PUBLIC_DEFAULT_RPM)).strip() or OPENAI_PUBLIC_DEFAULT_RPM),
            ),
        ),
        "lastLiveRunAt": LAST_OPENAI_LIVE_RUN_AT,
    }


def enforce_openai_public_rate_limit(key: str, limit: int) -> None:
    from fastapi import HTTPException
    now = datetime.now(timezone.utc).timestamp()
    bucket = OPENAI_REVIEWER_RATE_BUCKETS.get(key)
    if bucket is None or bucket["reset_at"] <= now:
        OPENAI_REVIEWER_RATE_BUCKETS[key] = {"count": 1.0, "reset_at": now + 60.0}
        return
    if bucket["count"] >= float(limit):
        raise HTTPException(status_code=429, detail="reviewer query demo rate limit exceeded")
    bucket["count"] += 1.0
