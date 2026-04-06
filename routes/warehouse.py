"""
Warehouse-related route handlers: mode switchboard, target scorecard.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from databricks_adapter import databricks_configured
from policy.governance import build_warehouse_target_scorecard
from snowflake_adapter import snowflake_configured
from warehouse_adapter import get_active_warehouse_adapter

router = APIRouter()


@router.get("/api/runtime/warehouse-mode-switchboard")
async def warehouse_mode_switchboard_endpoint():
    active_adapter = get_active_warehouse_adapter()
    return {
        "status": "ok",
        "service": "nexus-hive",
        "schema": "nexus-hive-warehouse-mode-switchboard-v1",
        "headline": "Compact board for comparing SQLite preview, Snowflake live posture, and Databricks live posture before a reviewer switches lanes.",
        "active_target": active_adapter.contract.name,
        "active_execution_mode": active_adapter.contract.execution_mode,
        "targets": [
            {
                "target": "sqlite-demo",
                "configured": True,
                "execution_mode": "local-sqlite",
                "primary_surface": "/api/runtime/brief",
                "why_it_matters": "Fastest no-key review path for governed analytics and audit posture.",
            },
            {
                "target": "snowflake-sql-contract",
                "configured": snowflake_configured(),
                "execution_mode": "snowflake-live"
                if snowflake_configured()
                else "contract-preview",
                "primary_surface": "/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract",
                "why_it_matters": "Best path when reviewer trust depends on live Snowflake execution and metric certification.",
            },
            {
                "target": "databricks-sql-contract",
                "configured": databricks_configured(),
                "execution_mode": "databricks-live"
                if databricks_configured()
                else "contract-preview",
                "primary_surface": "/api/runtime/lakehouse-readiness-pack?target=databricks-sql-contract",
                "why_it_matters": "Best path when reviewer trust depends on live Databricks SQL execution and lakehouse delivery posture.",
            },
        ],
        "review_sequence": [
            "Read /api/runtime/brief for the overall governed runtime posture.",
            "Use /api/runtime/warehouse-mode-switchboard to decide which warehouse lane is the strongest current proof.",
            "Open the target-specific scorecard or readiness pack before making a live warehouse claim.",
        ],
        "links": {
            "runtime_brief": "/api/runtime/brief",
            "warehouse_brief": "/api/runtime/warehouse-brief",
            "warehouse_target_scorecard": "/api/runtime/warehouse-target-scorecard",
            "lakehouse_readiness_pack": "/api/runtime/lakehouse-readiness-pack",
        },
    }


@router.get("/api/runtime/warehouse-target-scorecard")
async def warehouse_target_scorecard_endpoint(target: Optional[str] = None):
    try:
        return build_warehouse_target_scorecard(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
