"""
Shared configuration, constants, and utility functions for Nexus-Hive.

Centralizes environment variable reading, database paths, model settings,
policy constants, metric definitions, and OpenAI runtime contracts so that
all modules share a single source of truth.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------
_logger = logging.getLogger("nexus_hive.config")

# ---------------------------------------------------------------------------
# Core paths and model settings
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DB_PATH: Path = Path(
    os.getenv("NEXUS_HIVE_DB_PATH", str(BASE_DIR / "nexus_enterprise.db"))
).expanduser()
OLLAMA_URL: str = str(
    os.getenv("NEXUS_HIVE_OLLAMA_URL", "http://localhost:11434/api/generate")
).strip()
MODEL_NAME: str = str(os.getenv("NEXUS_HIVE_MODEL", "phi3")).strip() or "phi3"
DEFAULT_ROLE: str = (
    str(os.getenv("NEXUS_HIVE_ROLE", "analyst")).strip().lower() or "analyst"
)
ALLOW_HEURISTIC_FALLBACK: bool = str(
    os.getenv("NEXUS_HIVE_ALLOW_HEURISTIC_FALLBACK", "1")
).strip() not in {"0", "false", "False"}
AUDIT_LOG_PATH: Path = Path(
    os.getenv(
        "NEXUS_HIVE_AUDIT_PATH",
        str(Path(tempfile.gettempdir()) / "nexus_hive_query_audit.jsonl"),
    )
).expanduser()

# ---------------------------------------------------------------------------
# SQL policy constants
# ---------------------------------------------------------------------------
READ_ONLY_BLOCKLIST: Set[str] = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE", "CREATE",
}
SENSITIVE_COLUMNS_BY_ROLE: Dict[str, Set[str]] = {
    "analyst": {"margin_percentage"},
    "viewer": {"margin_percentage", "manager"},
}

# ---------------------------------------------------------------------------
# Schema identifiers
# ---------------------------------------------------------------------------
QUERY_TAG_SCHEMA: str = "nexus-hive-query-tag-v1"
GOVERNANCE_SCORECARD_SCHEMA: str = "nexus-hive-governance-scorecard-v1"
QUERY_SESSION_BOARD_SCHEMA: str = "nexus-hive-query-session-board-v1"
QUERY_APPROVAL_BOARD_SCHEMA: str = "nexus-hive-query-approval-board-v1"
WAREHOUSE_TARGET_SCORECARD_SCHEMA: str = "nexus-hive-warehouse-target-scorecard-v1"
SEMANTIC_GOVERNANCE_PACK_SCHEMA: str = "nexus-hive-semantic-governance-pack-v1"
LAKEHOUSE_READINESS_PACK_SCHEMA: str = "nexus-hive-lakehouse-readiness-pack-v1"
REVIEWER_QUERY_DEMO_SCHEMA: str = "nexus-hive-reviewer-query-demo-v1"

# ---------------------------------------------------------------------------
# Lineage relationships
# ---------------------------------------------------------------------------
LINEAGE_RELATIONSHIPS: List[Dict[str, str]] = [
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

# ---------------------------------------------------------------------------
# Metric layer definitions
# ---------------------------------------------------------------------------
METRIC_LAYER_DEFINITIONS: List[Dict[str, Any]] = [
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

# ---------------------------------------------------------------------------
# Gold eval cases
# ---------------------------------------------------------------------------
GOLD_EVAL_CASES: List[Dict[str, Any]] = [
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

# ---------------------------------------------------------------------------
# Audit and governance enums
# ---------------------------------------------------------------------------
AUDIT_STATUS_VALUES: Set[str] = {"accepted", "completed", "failed"}
AUDIT_POLICY_DECISION_VALUES: Set[str] = {"pending", "allow", "review", "deny"}
GOVERNANCE_SCORECARD_FOCUS_VALUES: Set[str] = {
    "throughput", "policy", "quality", "resilience",
}

# ---------------------------------------------------------------------------
# OpenAI integration constants
# ---------------------------------------------------------------------------
OPENAI_BASE_URL: str = "https://api.openai.com/v1"
OPENAI_PUBLIC_DEFAULT_MODEL: str = "gpt-4.1-mini"
OPENAI_PUBLIC_DEFAULT_DAILY_BUDGET_USD: float = 4.0
OPENAI_PUBLIC_DEFAULT_MONTHLY_BUDGET_USD: float = 120.0
OPENAI_PUBLIC_DEFAULT_RPM: int = 6
OPENAI_TIMEOUT_S: float = 20.0

REVIEWER_QUERY_SCENARIOS: Dict[str, Dict[str, Any]] = {
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

# ---------------------------------------------------------------------------
# Mutable global state
# ---------------------------------------------------------------------------
LAST_OPENAI_LIVE_RUN_AT: Optional[str] = None
OPENAI_REVIEWER_RATE_BUCKETS: Dict[str, Dict[str, float]] = {}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def get_db_schema() -> str:
    """Load and return the database schema DDL from the active warehouse adapter.

    Returns:
        A string containing all table DDL statements, or an empty string
        if the database does not exist.
    """
    from warehouse_adapter import get_active_warehouse_adapter

    return get_active_warehouse_adapter().get_schema(DB_PATH)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        An ISO-formatted UTC timestamp string.
    """
    return datetime.now(timezone.utc).isoformat()


def read_bool_env(name: str, fallback: bool) -> bool:
    """Read a boolean value from an environment variable.

    Recognizes truthy values (1, true, yes, y, on) and falsy values
    (0, false, no, n, off). Returns the fallback for empty or
    unrecognized values.

    Args:
        name: The environment variable name.
        fallback: Default value when the variable is absent or unrecognized.

    Returns:
        The parsed boolean value.
    """
    raw: str = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return fallback
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return fallback


def read_usd_env(name: str, fallback: float) -> float:
    """Read a USD budget value from an environment variable.

    Clamps the result to a minimum of 0.0 and rounds to two decimal places.

    Args:
        name: The environment variable name.
        fallback: Default value when the variable is absent or invalid.

    Returns:
        The parsed USD value, clamped and rounded.
    """
    raw: str = str(os.getenv(name, "")).strip()
    if not raw:
        return fallback
    try:
        value: float = float(raw)
    except ValueError:
        return fallback
    return round(max(0.0, value), 2)


def log_runtime_event(level: str, event: str, **payload: Any) -> None:
    """Emit a structured runtime event to stdout for operational visibility.

    Args:
        level: Severity level (info, warn, error).
        event: Event identifier string.
        **payload: Additional key-value pairs to include in the log entry.
    """
    log_entry: Dict[str, Any] = {
        "at": utc_now_iso(),
        "event": event,
        "level": level,
        "service": "nexus-hive",
        **payload,
    }
    print(json.dumps(log_entry, ensure_ascii=True))

    # Also emit to structured logger
    log_level = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}.get(
        level, logging.INFO
    )
    _logger.log(
        log_level,
        "Runtime event: %s",
        event,
        extra={"extra_fields": payload},
    )


def normalize_operator_roles(value: Any) -> list[str]:
    """Normalize operator roles from a string or list into a clean list of lowercase strings.

    Args:
        value: A comma-separated string or list of role names.

    Returns:
        A deduplicated list of lowercase, stripped role strings.
    """
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return []


def normalize_question(question: str) -> str:
    """Normalize a user question for comparison by lowercasing and collapsing whitespace.

    Args:
        question: The raw user question string.

    Returns:
        A normalized, lowercase, single-spaced version of the question.
    """
    return " ".join(str(question or "").strip().lower().split())


def build_openai_runtime_contract() -> Dict[str, Any]:
    """Build the OpenAI runtime contract describing the current deployment posture.

    Reads API key, budget limits, kill switch, and model configuration from
    environment variables and returns a structured contract dictionary.

    Returns:
        A dictionary describing the OpenAI integration posture.
    """
    api_key: str = str(os.getenv("OPENAI_API_KEY", "")).strip()
    kill_switch: bool = read_bool_env("OPENAI_KILL_SWITCH", False)
    daily_budget: float = read_usd_env(
        "OPENAI_PUBLIC_DAILY_BUDGET_USD", OPENAI_PUBLIC_DEFAULT_DAILY_BUDGET_USD
    )
    monthly_budget: float = read_usd_env(
        "OPENAI_PUBLIC_MONTHLY_BUDGET_USD", OPENAI_PUBLIC_DEFAULT_MONTHLY_BUDGET_USD
    )
    public_live_api: bool = (
        bool(api_key) and not kill_switch and daily_budget > 0 and monthly_budget > 0
    )
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
                int(
                    str(
                        os.getenv("OPENAI_PUBLIC_RPM", OPENAI_PUBLIC_DEFAULT_RPM)
                    ).strip()
                    or OPENAI_PUBLIC_DEFAULT_RPM
                ),
            ),
        ),
        "lastLiveRunAt": LAST_OPENAI_LIVE_RUN_AT,
    }


def enforce_openai_public_rate_limit(key: str, limit: int) -> None:
    """Enforce a per-minute rate limit on OpenAI public API calls.

    Uses an in-memory sliding window to track request counts per key.

    Args:
        key: Rate limit bucket identifier.
        limit: Maximum requests allowed per minute.

    Raises:
        HTTPException: If the rate limit has been exceeded (HTTP 429).
    """
    now: float = datetime.now(timezone.utc).timestamp()
    bucket: Optional[Dict[str, float]] = OPENAI_REVIEWER_RATE_BUCKETS.get(key)
    if bucket is None or bucket["reset_at"] <= now:
        OPENAI_REVIEWER_RATE_BUCKETS[key] = {"count": 1.0, "reset_at": now + 60.0}
        return
    if bucket["count"] >= float(limit):
        _logger.warning(
            "Rate limit exceeded for key=%s, limit=%d",
            key,
            limit,
        )
        raise HTTPException(
            status_code=429, detail="reviewer query demo rate limit exceeded"
        )
    bucket["count"] += 1.0
