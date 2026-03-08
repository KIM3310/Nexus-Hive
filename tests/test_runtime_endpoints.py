from __future__ import annotations

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
    query_audit_schema = client.get("/api/schema/query-audit")
    lineage_schema = client.get("/api/schema/lineage")
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
    assert meta_payload["query_audit_contract"] == "nexus-hive-query-audit-v1"
    assert "/api/ask" in meta_payload["routes"]
    assert "/api/runtime/brief" in meta_payload["routes"]
    assert "/api/runtime/warehouse-brief" in meta_payload["routes"]
    assert "/api/review-pack" in meta_payload["routes"]
    assert "/api/schema/answer" in meta_payload["routes"]
    assert "/api/schema/lineage" in meta_payload["routes"]
    assert "/api/schema/query-audit" in meta_payload["routes"]
    assert "/api/query-audit/recent" in meta_payload["routes"]

    assert runtime_brief.status_code == 200
    brief_payload = runtime_brief.json()
    assert brief_payload["readiness_contract"] == "nexus-hive-runtime-brief-v1"
    assert brief_payload["evidence_counts"]["agent_nodes"] == 3
    assert brief_payload["report_contract"]["schema"] == "nexus-hive-answer-v1"
    assert brief_payload["warehouse_contract"]["mode"] == "sqlite-demo"
    assert brief_payload["warehouse_contract"]["lineage_schema"] == "nexus-hive-lineage-v1"
    assert brief_payload["warehouse_contract"]["query_audit_schema"] == "nexus-hive-query-audit-v1"

    assert warehouse_brief.status_code == 200
    warehouse_payload = warehouse_brief.json()
    assert warehouse_payload["readiness_contract"] == "nexus-hive-warehouse-brief-v1"
    assert warehouse_payload["warehouse_mode"] == "sqlite-demo"
    assert warehouse_payload["quality_gate"]["schema"] == "nexus-hive-quality-gate-v1"
    assert warehouse_payload["lineage"]["schema"] == "nexus-hive-lineage-v1"
    assert isinstance(warehouse_payload["table_profiles"], list)

    assert review_pack.status_code == 200
    pack_payload = review_pack.json()
    assert pack_payload["readiness_contract"] == "nexus-hive-review-pack-v1"
    assert pack_payload["answer_contract"]["schema"] == "nexus-hive-answer-v1"
    assert "/api/review-pack" in pack_payload["proof_bundle"]["review_routes"]
    assert pack_payload["proof_bundle"]["quality_gate_status"] in {"ok", "degraded"}
    assert isinstance(pack_payload["executive_promises"], list)

    assert answer_schema.status_code == 200
    schema_payload = answer_schema.json()
    assert schema_payload["schema"] == "nexus-hive-answer-v1"
    assert "sql_query" in schema_payload["required_sections"]

    assert query_audit_schema.status_code == 200
    query_audit_schema_payload = query_audit_schema.json()
    assert query_audit_schema_payload["schema"] == "nexus-hive-query-audit-v1"
    assert "request_id" in query_audit_schema_payload["required_fields"]

    assert lineage_schema.status_code == 200
    lineage_payload = lineage_schema.json()
    assert lineage_payload["schema"] == "nexus-hive-lineage-v1"
    assert len(lineage_payload["relationships"]) == 2

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
    assert payload["links"]["query_audit_recent"].endswith("/api/query-audit/recent")

    audit_response = client.get("/api/query-audit/recent")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    assert any(
        item["request_id"] == payload["request_id"]
        and item["status"] == "accepted"
        and item["stage"] == "accepted"
        for item in audit_payload["items"]
    )
