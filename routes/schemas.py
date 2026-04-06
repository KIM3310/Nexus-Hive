"""
Schema endpoint route handlers.
"""

from fastapi import APIRouter

from config import utc_now_iso
from policy.audit import build_query_audit_schema
from policy.engine import build_policy_schema, build_query_tag_contract
from policy.governance import (
    build_gold_eval_pack,
    build_lineage_schema,
    build_metric_layer_schema,
    run_gold_eval_suite,
)
from services.build_helpers import build_answer_schema

router = APIRouter()


@router.get("/api/schema/answer")
async def answer_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_answer_schema(),
    }


@router.get("/api/schema/lineage")
async def lineage_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_lineage_schema(),
    }


@router.get("/api/schema/metrics")
async def metric_layer_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_metric_layer_schema(),
    }


@router.get("/api/schema/policy")
async def policy_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_policy_schema(),
    }


@router.get("/api/schema/query-tag")
async def query_tag_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_tag_contract(),
    }


@router.get("/api/schema/query-audit")
async def query_audit_schema_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_query_audit_schema(),
    }


@router.get("/api/evals/nl2sql-gold")
async def gold_eval_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **build_gold_eval_pack(),
    }


@router.get("/api/evals/nl2sql-gold/run")
async def gold_eval_run_endpoint():
    return {
        "status": "ok",
        "service": "nexus-hive",
        "generated_at": utc_now_iso(),
        **run_gold_eval_suite(),
    }
