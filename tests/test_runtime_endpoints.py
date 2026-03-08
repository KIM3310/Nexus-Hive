from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = Path(tempfile.gettempdir()) / "nexus_hive_query_audit_test.jsonl"
os.environ["NEXUS_HIVE_AUDIT_PATH"] = str(AUDIT_PATH)
if AUDIT_PATH.exists():
    AUDIT_PATH.unlink()


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


APP_MODULE = load_module("nexus_hive_main", "main.py")


def test_health_and_meta_expose_runtime_diagnostics() -> None:
    client = TestClient(APP_MODULE.app)

    health = client.get("/health")
    meta = client.get("/api/meta")
    runtime_brief = client.get("/api/runtime/brief")
    warehouse_brief = client.get("/api/runtime/warehouse-brief")
    review_pack = client.get("/api/review-pack")
    answer_schema = client.get("/api/schema/answer")
    policy_schema = client.get("/api/schema/policy")
    query_audit_schema = client.get("/api/schema/query-audit")
    lineage_schema = client.get("/api/schema/lineage")
    gold_eval = client.get("/api/evals/nl2sql-gold")
    gold_eval_run = client.get("/api/evals/nl2sql-gold/run")
    recent_query_audit = client.get("/api/query-audit/recent")

    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["service"] == "nexus-hive"
    assert health_payload["links"]["meta"] == "/api/meta"
    assert health_payload["links"]["runtime_brief"] == "/api/runtime/brief"
    assert health_payload["links"]["warehouse_brief"] == "/api/runtime/warehouse-brief"
    assert health_payload["links"]["review_pack"] == "/api/review-pack"
    assert health_payload["links"]["answer_schema"] == "/api/schema/answer"
    assert health_payload["links"]["lineage_schema"] == "/api/schema/lineage"
    assert health_payload["links"]["query_audit_schema"] == "/api/schema/query-audit"
    assert health_payload["links"]["query_audit_recent"] == "/api/query-audit/recent"
    assert health_payload["diagnostics"]["db_ready"] is True
    assert health_payload["ops_contract"]["schema"] == "ops-envelope-v1"
    assert "next_action" in health_payload["diagnostics"]

    assert meta.status_code == 200
    meta_payload = meta.json()
    assert meta_payload["service"] == "nexus-hive"
    assert meta_payload["diagnostics"]["schema_loaded"] is True
    assert meta_payload["ops_contract"]["schema"] == "ops-envelope-v1"
    assert meta_payload["readiness_contract"] == "nexus-hive-runtime-brief-v1"
    assert meta_payload["warehouse_brief_contract"] == "nexus-hive-warehouse-brief-v1"
    assert meta_payload["review_pack_contract"] == "nexus-hive-review-pack-v1"
    assert meta_payload["report_contract"]["schema"] == "nexus-hive-answer-v1"
    assert meta_payload["lineage_contract"] == "nexus-hive-lineage-v1"
    assert meta_payload["policy_contract"] == "nexus-hive-policy-v1"
    assert meta_payload["query_audit_contract"] == "nexus-hive-query-audit-v1"
    assert meta_payload["gold_eval_contract"] == "nexus-hive-gold-eval-v1"
    assert "/api/ask" in meta_payload["routes"]
    assert "/api/runtime/brief" in meta_payload["routes"]
    assert "/api/runtime/warehouse-brief" in meta_payload["routes"]
    assert "/api/review-pack" in meta_payload["routes"]
    assert "/api/schema/answer" in meta_payload["routes"]
    assert "/api/schema/lineage" in meta_payload["routes"]
    assert "/api/schema/policy" in meta_payload["routes"]
    assert "/api/schema/query-audit" in meta_payload["routes"]
    assert "/api/evals/nl2sql-gold" in meta_payload["routes"]
    assert "/api/query-audit/recent" in meta_payload["routes"]

    assert runtime_brief.status_code == 200
    brief_payload = runtime_brief.json()
    assert brief_payload["readiness_contract"] == "nexus-hive-runtime-brief-v1"
    assert brief_payload["evidence_counts"]["agent_nodes"] == 3
    assert brief_payload["report_contract"]["schema"] == "nexus-hive-answer-v1"
    assert brief_payload["warehouse_contract"]["mode"] == "sqlite-demo"
    assert brief_payload["warehouse_contract"]["fallback_mode"] in {"heuristic", "disabled"}
    assert brief_payload["warehouse_contract"]["lineage_schema"] == "nexus-hive-lineage-v1"
    assert brief_payload["warehouse_contract"]["policy_schema"] == "nexus-hive-policy-v1"
    assert brief_payload["warehouse_contract"]["query_audit_schema"] == "nexus-hive-query-audit-v1"
    assert brief_payload["warehouse_contract"]["gold_eval_schema"] == "nexus-hive-gold-eval-v1"

    assert warehouse_brief.status_code == 200
    warehouse_payload = warehouse_brief.json()
    assert warehouse_payload["readiness_contract"] == "nexus-hive-warehouse-brief-v1"
    assert warehouse_payload["warehouse_mode"] == "sqlite-demo"
    assert warehouse_payload["fallback_mode"] in {"heuristic", "disabled"}
    assert warehouse_payload["quality_gate"]["schema"] == "nexus-hive-quality-gate-v1"
    assert warehouse_payload["lineage"]["schema"] == "nexus-hive-lineage-v1"
    assert warehouse_payload["policy"]["schema"] == "nexus-hive-policy-v1"
    assert warehouse_payload["gold_eval"]["schema"] == "nexus-hive-gold-eval-v1"
    assert isinstance(warehouse_payload["table_profiles"], list)

    assert review_pack.status_code == 200
    pack_payload = review_pack.json()
    assert pack_payload["readiness_contract"] == "nexus-hive-review-pack-v1"
    assert pack_payload["answer_contract"]["schema"] == "nexus-hive-answer-v1"
    assert "/api/review-pack" in pack_payload["proof_bundle"]["review_routes"]
    assert pack_payload["proof_bundle"]["quality_gate_status"] in {"ok", "degraded"}
    assert "/api/evals/nl2sql-gold" in pack_payload["proof_bundle"]["review_routes"]
    assert isinstance(pack_payload["executive_promises"], list)

    assert answer_schema.status_code == 200
    schema_payload = answer_schema.json()
    assert schema_payload["schema"] == "nexus-hive-answer-v1"
    assert "sql_query" in schema_payload["required_sections"]

    assert query_audit_schema.status_code == 200
    query_audit_schema_payload = query_audit_schema.json()
    assert query_audit_schema_payload["schema"] == "nexus-hive-query-audit-v1"
    assert "request_id" in query_audit_schema_payload["required_fields"]

    assert policy_schema.status_code == 200
    policy_schema_payload = policy_schema.json()
    assert policy_schema_payload["schema"] == "nexus-hive-policy-v1"
    assert "wildcard_projection_denied" in policy_schema_payload["deny_rules"]

    assert lineage_schema.status_code == 200
    lineage_payload = lineage_schema.json()
    assert lineage_payload["schema"] == "nexus-hive-lineage-v1"
    assert len(lineage_payload["relationships"]) == 2

    assert gold_eval.status_code == 200
    gold_eval_payload = gold_eval.json()
    assert gold_eval_payload["schema"] == "nexus-hive-gold-eval-v1"
    assert gold_eval_payload["summary"]["case_count"] == 4

    assert gold_eval_run.status_code == 200
    gold_eval_run_payload = gold_eval_run.json()
    assert gold_eval_run_payload["schema"] == "nexus-hive-gold-eval-run-v1"
    assert gold_eval_run_payload["summary"]["case_count"] == 4

    assert recent_query_audit.status_code == 200
    recent_query_audit_payload = recent_query_audit.json()
    assert recent_query_audit_payload["schema"] == "nexus-hive-query-audit-v1"
    assert recent_query_audit_payload["items"] == []


def test_ask_endpoint_returns_stream_pointer() -> None:
    client = TestClient(APP_MODULE.app)

    response = client.post("/api/ask", json={"question": "Show total revenue by region"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["request_id"]
    assert payload["question"] == "Show total revenue by region"
    assert "/api/stream?q=Show+total+revenue+by+region&rid=" in payload["stream_url"]
    assert payload["links"]["runtime_brief"].endswith("/api/runtime/brief")
    assert payload["links"]["warehouse_brief"].endswith("/api/runtime/warehouse-brief")
    assert payload["links"]["answer_schema"].endswith("/api/schema/answer")
    assert payload["links"]["gold_eval"].endswith("/api/evals/nl2sql-gold")
    assert payload["links"]["query_audit_recent"].endswith("/api/query-audit/recent")
    assert payload["links"]["query_audit_detail"].endswith(f"/api/query-audit/{payload['request_id']}")

    audit_response = client.get("/api/query-audit/recent")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    assert any(
        item["request_id"] == payload["request_id"]
        and item["status"] == "accepted"
        and item["stage"] == "accepted"
        for item in audit_payload["items"]
    )


def test_stream_completion_writes_query_audit_detail(monkeypatch) -> None:
    async def fail_ollama(_: str) -> str:
        raise RuntimeError("offline")

    monkeypatch.setattr(APP_MODULE, "ask_ollama", fail_ollama)
    client = TestClient(APP_MODULE.app)

    accepted = client.post("/api/ask", json={"question": "Show total revenue by region"})
    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    request_id = accepted_payload["request_id"]

    stream_response = client.get(f"/api/stream?q=Show%20total%20revenue%20by%20region&rid={request_id}")
    assert stream_response.status_code == 200
    assert '"type": "done"' in stream_response.text

    detail_response = client.get(f"/api/query-audit/{request_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["request_id"] == request_id
    assert detail_payload["latest"]["status"] == "completed"
    assert detail_payload["latest"]["policy_decision"] in {"allow", "review"}
    assert detail_payload["latest"]["fallback_sql_used"] is True
    assert detail_payload["latest"]["fallback_chart_used"] is True
    assert detail_payload["latest"]["row_count"] > 0
    assert len(detail_payload["history"]) >= 2


def test_policy_preview_and_gold_eval_run_surfaces() -> None:
    client = TestClient(APP_MODULE.app)

    denied = client.post("/api/policy/check", json={"sql": "SELECT * FROM sales", "role": "analyst"})
    assert denied.status_code == 200
    denied_payload = denied.json()
    assert denied_payload["schema"] == "nexus-hive-policy-v1"
    assert denied_payload["verdict"]["decision"] == "deny"
    assert "wildcard_projection_denied" in denied_payload["verdict"]["deny_reasons"]

    runnable = client.get("/api/evals/nl2sql-gold/run")
    assert runnable.status_code == 200
    runnable_payload = runnable.json()
    assert runnable_payload["schema"] == "nexus-hive-gold-eval-run-v1"
    assert runnable_payload["summary"]["case_count"] == 4
    assert len(runnable_payload["items"]) == 4
    assert all("policy_verdict" in item for item in runnable_payload["items"])


def test_policy_and_fallback_path(monkeypatch) -> None:
    async def fail_ollama(_: str) -> str:
        raise RuntimeError("offline")

    monkeypatch.setattr(APP_MODULE, "ask_ollama", fail_ollama)

    state = {
        "user_query": "Show total net revenue by region",
        "sql_query": "",
        "db_result": [],
        "chart_config": {},
        "error": "",
        "retry_count": 0,
        "log_stream": [],
    }

    translated = asyncio.run(APP_MODULE.translator_node(state))
    assert "SELECT" in translated["sql_query"]
    assert any("Heuristic SQL fallback engaged." in log for log in translated["log_stream"])

    executed = APP_MODULE.executor_node(translated)
    assert executed["error"] == ""
    assert executed["db_result"]

    visualized = asyncio.run(APP_MODULE.visualizer_node(executed))
    assert visualized["chart_config"]["type"] in {"bar", "line", "doughnut"}
    assert any("Heuristic chart config used." in log for log in visualized["log_stream"])

    wildcard_policy = APP_MODULE.evaluate_sql_policy("SELECT * FROM sales")
    sensitive_policy = APP_MODULE.evaluate_sql_policy("SELECT margin_percentage FROM products")
    review_policy = APP_MODULE.evaluate_sql_policy("SELECT transaction_id FROM sales")

    assert wildcard_policy["decision"] == "deny"
    assert "wildcard_projection_denied" in wildcard_policy["deny_reasons"]
    assert sensitive_policy["decision"] == "deny"
    assert "sensitive_columns_require_privileged_role" in sensitive_policy["deny_reasons"]
    assert review_policy["decision"] == "review"
    assert "non_aggregated_queries_without_limit_require_operator_review" in review_policy["review_reasons"]
