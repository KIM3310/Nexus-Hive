"""
Reviewer query demo route handler.
"""

import json
import os

from fastapi import APIRouter, HTTPException, Request
from uuid import uuid4

import config as _config_module
from config import (
    REVIEWER_QUERY_DEMO_SCHEMA,
    REVIEWER_QUERY_SCENARIOS,
    build_openai_runtime_contract,
    enforce_openai_public_rate_limit,
    utc_now_iso,
)
from models import ReviewerQueryDemoRequest
from policy.governance import build_lineage_schema, build_metric_layer_schema
from runtime_store import append_runtime_event
from services.openai_helpers import (
    call_openai_moderation as _default_moderation,
    call_openai_reviewer_demo_summary as _default_summary,
)

router = APIRouter()


@router.post("/api/runtime/reviewer-query-demo")
async def reviewer_query_demo_endpoint(req: ReviewerQueryDemoRequest, request: Request):
    runtime = build_openai_runtime_contract()
    if not runtime["publicLiveApi"]:
        raise HTTPException(
            status_code=503,
            detail="public OpenAI reviewer demo is unavailable; configure OPENAI_API_KEY and keep budgets above zero",
        )
    scenario_id = str(req.question_id or "").strip().lower()
    scenario = REVIEWER_QUERY_SCENARIOS.get(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=400,
            detail="question_id must be one of revenue-by-region or profit-top-regions",
        )
    enforce_openai_public_rate_limit(f"reviewer-demo:{scenario_id}", int(runtime["publicRpm"]))
    payload = {
        "question_id": scenario_id,
        "question": scenario["question"],
        "sql": scenario["sql"],
        "metric_ids": scenario["metric_ids"],
        "warehouse_target": scenario["warehouse_target"],
        "approval_posture": scenario["approval_posture"],
        "lineage_schema": build_lineage_schema()["schema"],
        "metric_layer_schema": build_metric_layer_schema()["schema"],
    }
    api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()

    # Look up helpers via the app state so that test monkeypatching
    # on the correct main module instance propagates correctly.
    _resolve_mod = getattr(request.app.state, "_resolve_moderation", None)
    _resolve_sum = getattr(request.app.state, "_resolve_summary", None)
    _mod_fn = _resolve_mod() if _resolve_mod else _default_moderation
    _sum_fn = _resolve_sum() if _resolve_sum else _default_summary

    if runtime["moderationEnabled"]:
        await _mod_fn(api_key, json.dumps(payload, ensure_ascii=True))
    live_summary = await _sum_fn(api_key, str(runtime["liveModel"]), payload)
    _config_module.LAST_OPENAI_LIVE_RUN_AT = utc_now_iso()
    append_runtime_event(
        {
            "service": "nexus-hive",
            "event_type": "reviewer_query_demo",
            "method": "POST",
            "path": "/api/runtime/reviewer-query-demo",
            "status": "ok",
            "question_id": scenario_id,
            "at": utc_now_iso(),
        }
    )
    return {
        "status": "ok",
        "service": "nexus-hive",
        "schema": REVIEWER_QUERY_DEMO_SCHEMA,
        "mode": runtime["deploymentMode"],
        "model": runtime["liveModel"],
        "scenarioId": scenario_id,
        "moderated": True,
        "capped": True,
        "traceId": uuid4().hex[:12],
        "estimatedCostUsd": scenario["estimated_cost_usd"],
        "nextReviewPath": scenario["next_review_path"],
        "result": {
            "question": scenario["question"],
            "sql": scenario["sql"],
            "metricIds": scenario["metric_ids"],
            "approvalPosture": scenario["approval_posture"],
            "warehouseFit": scenario["warehouse_target"],
            "lineage": build_lineage_schema()["schema"],
            "metricLayer": build_metric_layer_schema()["schema"],
            **live_summary,
        },
    }
