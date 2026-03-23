from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = Path(tempfile.gettempdir()) / "nexus_hive_query_audit_test.jsonl"
RUNTIME_STORE_PATH = Path(tempfile.gettempdir()) / "nexus_hive_runtime_store_test.db"
os.environ["NEXUS_HIVE_AUDIT_PATH"] = str(AUDIT_PATH)
os.environ["NEXUS_HIVE_RUNTIME_STORE_PATH"] = str(RUNTIME_STORE_PATH)
if AUDIT_PATH.exists():
    AUDIT_PATH.unlink()
if RUNTIME_STORE_PATH.exists():
    RUNTIME_STORE_PATH.unlink()


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
    review_resource_pack = client.get("/api/runtime/review-resource-pack")
    warehouse_brief = client.get("/api/runtime/warehouse-brief")
    warehouse_target_scorecard = client.get(
        "/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract"
    )
    governance_scorecard = client.get("/api/runtime/governance-scorecard?focus=quality")
    semantic_governance_pack = client.get("/api/runtime/semantic-governance-pack")
    lakehouse_readiness_pack = client.get(
        "/api/runtime/lakehouse-readiness-pack?target=databricks-sql-contract"
    )
    reviewer_query_demo = client.post(
        "/api/runtime/reviewer-query-demo",
        json={"question_id": "revenue-by-region"},
    )
    review_pack = client.get("/api/review-pack")
    answer_schema = client.get("/api/schema/answer")
    policy_schema = client.get("/api/schema/policy")
    metrics_schema = client.get("/api/schema/metrics")
    query_tag_schema = client.get("/api/schema/query-tag")
    query_audit_schema = client.get("/api/schema/query-audit")
    query_session_board = client.get("/api/query-session-board")
    query_approval_board = client.get("/api/query-approval-board")
    query_review_board = client.get("/api/query-review-board")
    query_audit_summary = client.get("/api/query-audit/summary")
    lineage_schema = client.get("/api/schema/lineage")
    gold_eval = client.get("/api/evals/nl2sql-gold")
    gold_eval_run = client.get("/api/evals/nl2sql-gold/run")
    recent_query_audit = client.get("/api/query-audit/recent")

    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["service"] == "nexus-hive"
    assert health_payload["links"]["meta"] == "/api/meta"
    assert health_payload["links"]["runtime_brief"] == "/api/runtime/brief"
    assert health_payload["links"]["review_resource_pack"] == "/api/runtime/review-resource-pack"
    assert health_payload["links"]["warehouse_brief"] == "/api/runtime/warehouse-brief"
    assert (
        health_payload["links"]["warehouse_target_scorecard"]
        == "/api/runtime/warehouse-target-scorecard"
    )
    assert health_payload["links"]["governance_scorecard"] == "/api/runtime/governance-scorecard"
    assert (
        health_payload["links"]["semantic_governance_pack"]
        == "/api/runtime/semantic-governance-pack"
    )
    assert (
        health_payload["links"]["lakehouse_readiness_pack"]
        == "/api/runtime/lakehouse-readiness-pack"
    )
    assert health_payload["links"]["reviewer_query_demo"] == "/api/runtime/reviewer-query-demo"
    assert health_payload["links"]["auth_session"] == "/api/auth/session"
    assert health_payload["links"]["review_pack"] == "/api/review-pack"
    assert health_payload["links"]["answer_schema"] == "/api/schema/answer"
    assert health_payload["links"]["lineage_schema"] == "/api/schema/lineage"
    assert health_payload["links"]["metric_layer_schema"] == "/api/schema/metrics"
    assert health_payload["links"]["query_audit_schema"] == "/api/schema/query-audit"
    assert health_payload["links"]["query_tag_schema"] == "/api/schema/query-tag"
    assert health_payload["links"]["query_session_board"] == "/api/query-session-board"
    assert health_payload["links"]["query_approval_board"] == "/api/query-approval-board"
    assert health_payload["links"]["query_review_board"] == "/api/query-review-board"
    assert health_payload["links"]["query_audit_summary"] == "/api/query-audit/summary"
    assert health_payload["links"]["query_audit_recent"] == "/api/query-audit/recent"
    assert health_payload["diagnostics"]["db_ready"] is True
    assert health_payload["ops_contract"]["schema"] == "ops-envelope-v1"
    assert "next_action" in health_payload["diagnostics"]

    assert meta.status_code == 200
    meta_payload = meta.json()
    assert meta_payload["service"] == "nexus-hive"
    assert meta_payload["diagnostics"]["schema_loaded"] is True
    assert meta_payload["auth"]["operator_token_enabled"] is False
    assert meta_payload["auth"]["operator_required_roles"] == []
    assert "x-operator-role" in meta_payload["auth"]["operator_role_headers"]
    assert meta_payload["auth"]["operator_session_cookie"] == "nexus_hive_operator_session"
    assert meta_payload["ops_contract"]["schema"] == "ops-envelope-v1"
    assert meta_payload["readiness_contract"] == "nexus-hive-runtime-brief-v1"
    assert meta_payload["warehouse_brief_contract"] == "nexus-hive-warehouse-brief-v1"
    assert (
        meta_payload["warehouse_target_scorecard_contract"]
        == "nexus-hive-warehouse-target-scorecard-v1"
    )
    assert meta_payload["governance_scorecard_contract"] == "nexus-hive-governance-scorecard-v1"
    assert (
        meta_payload["semantic_governance_pack_contract"]
        == "nexus-hive-semantic-governance-pack-v1"
    )
    assert (
        meta_payload["lakehouse_readiness_pack_contract"]
        == "nexus-hive-lakehouse-readiness-pack-v1"
    )
    assert meta_payload["openai"]["deploymentMode"] == "review-only-live"
    assert meta_payload["review_pack_contract"] == "nexus-hive-review-pack-v1"
    assert meta_payload["report_contract"]["schema"] == "nexus-hive-answer-v1"
    assert meta_payload["lineage_contract"] == "nexus-hive-lineage-v1"
    assert meta_payload["metric_layer_contract"] == "nexus-hive-metric-layer-v1"
    assert meta_payload["policy_contract"] == "nexus-hive-policy-v1"
    assert meta_payload["query_tag_contract"] == "nexus-hive-query-tag-v1"
    assert meta_payload["query_audit_contract"] == "nexus-hive-query-audit-v1"
    assert meta_payload["query_session_board_contract"] == "nexus-hive-query-session-board-v1"
    assert meta_payload["query_approval_board_contract"] == "nexus-hive-query-approval-board-v1"
    assert meta_payload["query_review_board_contract"] == "nexus-hive-query-review-board-v1"
    assert meta_payload["query_audit_summary_contract"] == "nexus-hive-query-audit-summary-v1"
    assert meta_payload["gold_eval_contract"] == "nexus-hive-gold-eval-v1"
    assert "/api/ask" in meta_payload["routes"]
    assert "/api/runtime/brief" in meta_payload["routes"]
    assert "/api/runtime/review-resource-pack" in meta_payload["routes"]
    assert "/api/runtime/warehouse-brief" in meta_payload["routes"]
    assert "/api/runtime/warehouse-target-scorecard" in meta_payload["routes"]
    assert "/api/runtime/governance-scorecard" in meta_payload["routes"]
    assert "/api/runtime/semantic-governance-pack" in meta_payload["routes"]
    assert "/api/runtime/lakehouse-readiness-pack" in meta_payload["routes"]
    assert "/api/runtime/reviewer-query-demo" in meta_payload["routes"]
    assert "/api/auth/session" in meta_payload["routes"]
    assert "/api/review-pack" in meta_payload["routes"]
    assert "/api/schema/answer" in meta_payload["routes"]
    assert "/api/schema/lineage" in meta_payload["routes"]
    assert "/api/schema/metrics" in meta_payload["routes"]
    assert "/api/schema/policy" in meta_payload["routes"]
    assert "/api/schema/query-tag" in meta_payload["routes"]
    assert "/api/schema/query-audit" in meta_payload["routes"]
    assert "/api/query-session-board" in meta_payload["routes"]
    assert "/api/query-approval-board" in meta_payload["routes"]
    assert "/api/query-review-board" in meta_payload["routes"]
    assert "/api/query-audit/summary" in meta_payload["routes"]
    assert "/api/evals/nl2sql-gold" in meta_payload["routes"]
    assert "/api/query-audit/recent" in meta_payload["routes"]

    assert runtime_brief.status_code == 200
    brief_payload = runtime_brief.json()
    assert brief_payload["readiness_contract"] == "nexus-hive-runtime-brief-v1"
    assert brief_payload["deploymentMode"] == "review-only-live"
    assert brief_payload["evidence_counts"]["agent_nodes"] == 3
    assert brief_payload["evidence_counts"]["review_pack_scenarios"] >= 4
    assert brief_payload["report_contract"]["schema"] == "nexus-hive-answer-v1"
    assert brief_payload["warehouse_contract"]["mode"] == "sqlite-demo"
    assert brief_payload["warehouse_contract"]["fallback_mode"] in {"heuristic", "disabled"}
    assert brief_payload["warehouse_contract"]["lineage_schema"] == "nexus-hive-lineage-v1"
    assert (
        brief_payload["warehouse_contract"]["metric_layer_schema"] == "nexus-hive-metric-layer-v1"
    )
    assert brief_payload["warehouse_contract"]["policy_schema"] == "nexus-hive-policy-v1"
    assert (
        brief_payload["warehouse_contract"]["semantic_governance_pack_schema"]
        == "nexus-hive-semantic-governance-pack-v1"
    )
    assert (
        brief_payload["warehouse_contract"]["lakehouse_readiness_pack_schema"]
        == "nexus-hive-lakehouse-readiness-pack-v1"
    )
    assert brief_payload["warehouse_contract"]["query_tag_schema"] == "nexus-hive-query-tag-v1"
    assert brief_payload["warehouse_contract"]["query_audit_schema"] == "nexus-hive-query-audit-v1"
    assert (
        brief_payload["warehouse_contract"]["query_session_board_schema"]
        == "nexus-hive-query-session-board-v1"
    )
    assert (
        brief_payload["warehouse_contract"]["query_approval_board_schema"]
        == "nexus-hive-query-approval-board-v1"
    )
    assert (
        brief_payload["warehouse_contract"]["query_review_board_schema"]
        == "nexus-hive-query-review-board-v1"
    )
    assert (
        brief_payload["warehouse_contract"]["query_audit_summary_schema"]
        == "nexus-hive-query-audit-summary-v1"
    )
    assert (
        brief_payload["warehouse_contract"]["governance_scorecard_schema"]
        == "nexus-hive-governance-scorecard-v1"
    )
    assert brief_payload["warehouse_contract"]["gold_eval_schema"] == "nexus-hive-gold-eval-v1"
    assert brief_payload["warehouse_contract"]["operator_auth_enabled"] is False
    assert brief_payload["links"]["reviewer_query_demo"] == "/api/runtime/reviewer-query-demo"

    assert review_resource_pack.status_code == 200
    review_resource_pack_payload = review_resource_pack.json()
    assert review_resource_pack_payload["schema"] == "nexus-hive-review-resource-pack-v1"
    assert review_resource_pack_payload["summary"]["scenario_count"] >= 4
    assert review_resource_pack_payload["reviewer_fast_path"][2] == "/api/runtime/review-resource-pack"

    assert warehouse_brief.status_code == 200
    warehouse_payload = warehouse_brief.json()
    assert warehouse_payload["readiness_contract"] == "nexus-hive-warehouse-brief-v1"
    assert warehouse_payload["warehouse_mode"] == "sqlite-demo"
    assert warehouse_payload["fallback_mode"] in {"heuristic", "disabled"}
    assert warehouse_payload["quality_gate"]["schema"] == "nexus-hive-quality-gate-v1"
    assert warehouse_payload["lineage"]["schema"] == "nexus-hive-lineage-v1"
    assert warehouse_payload["metric_layer"]["schema"] == "nexus-hive-metric-layer-v1"
    assert warehouse_payload["policy"]["schema"] == "nexus-hive-policy-v1"
    assert warehouse_payload["query_tag_contract"]["schema"] == "nexus-hive-query-tag-v1"
    assert warehouse_payload["audit_summary"]["schema"] == "nexus-hive-query-audit-summary-v1"
    assert warehouse_payload["gold_eval"]["schema"] == "nexus-hive-gold-eval-v1"
    assert "/api/query-session-board" in warehouse_payload["routes"]
    assert "/api/runtime/warehouse-target-scorecard" in warehouse_payload["routes"]
    assert isinstance(warehouse_payload["table_profiles"], list)

    assert warehouse_target_scorecard.status_code == 200
    warehouse_target_payload = warehouse_target_scorecard.json()
    assert warehouse_target_payload["schema"] == "nexus-hive-warehouse-target-scorecard-v1"
    assert warehouse_target_payload["filters"]["target"] == "snowflake-sql-contract"
    assert warehouse_target_payload["summary"]["visible_targets"] == 1
    assert warehouse_target_payload["targets"][0]["target"] == "snowflake-sql-contract"
    assert (
        warehouse_target_payload["links"]["warehouse_target_scorecard"]
        == "/api/runtime/warehouse-target-scorecard"
    )
    assert warehouse_target_payload["links"]["metric_layer_schema"] == "/api/schema/metrics"
    assert (
        warehouse_target_payload["links"]["semantic_governance_pack"]
        == "/api/runtime/semantic-governance-pack"
    )

    assert governance_scorecard.status_code == 200
    governance_payload = governance_scorecard.json()
    assert governance_payload["schema"] == "nexus-hive-governance-scorecard-v1"
    assert governance_payload["focus"] == "quality"
    assert governance_payload["summary"]["warehouse_mode"] == "sqlite-demo"
    assert governance_payload["summary"]["persisted_event_count"] >= 1
    assert governance_payload["persistence"]["event_type_counts"]["scorecard_view"] >= 1
    assert governance_payload["persistence"]["backend"] == "sqlite"
    assert governance_payload["operator_auth"]["enabled"] is False
    assert governance_payload["operator_auth"]["session_cookie"] == "nexus_hive_operator_session"
    assert governance_payload["links"]["query_review_board"] == "/api/query-review-board"
    assert governance_payload["links"]["query_session_board"] == "/api/query-session-board"
    assert (
        governance_payload["links"]["governance_scorecard"] == "/api/runtime/governance-scorecard"
    )
    assert governance_payload["links"]["auth_session"] == "/api/auth/session"
    assert isinstance(governance_payload["score_bands"], list)

    assert semantic_governance_pack.status_code == 200
    semantic_pack_payload = semantic_governance_pack.json()
    assert semantic_pack_payload["schema"] == "nexus-hive-semantic-governance-pack-v1"
    assert semantic_pack_payload["summary"]["certified_metric_count"] >= 1
    assert semantic_pack_payload["summary"]["target_count"] >= 3
    assert any(
        item["status"] == "certified" for item in semantic_pack_payload["certification_board"]
    )
    assert any(
        item["target"] == "snowflake-sql-contract"
        for item in semantic_pack_payload["target_posture"]
    )
    assert (
        semantic_pack_payload["links"]["semantic_governance_pack"]
        == "/api/runtime/semantic-governance-pack"
    )
    assert semantic_pack_payload["links"]["metric_layer_schema"] == "/api/schema/metrics"
    assert semantic_pack_payload["links"]["query_approval_board"] == "/api/query-approval-board"

    assert lakehouse_readiness_pack.status_code == 200
    lakehouse_payload = lakehouse_readiness_pack.json()
    assert lakehouse_payload["schema"] == "nexus-hive-lakehouse-readiness-pack-v1"
    assert lakehouse_payload["filters"]["target"] == "databricks-sql-contract"
    assert lakehouse_payload["summary"]["visible_targets"] == 1
    assert lakehouse_payload["platform_cards"][0]["target"] == "databricks-sql-contract"
    assert (
        lakehouse_payload["links"]["lakehouse_readiness_pack"]
        == "/api/runtime/lakehouse-readiness-pack"
    )
    assert lakehouse_payload["links"]["query_tag_schema"] == "/api/schema/query-tag"
    assert any(
        route == "/api/runtime/lakehouse-readiness-pack"
        for route in lakehouse_payload["platform_cards"][0]["review_surfaces"]
    )
    assert len(semantic_pack_payload["review_path"]) >= 3

    assert reviewer_query_demo.status_code == 503
    assert "OPENAI_API_KEY" in reviewer_query_demo.json()["detail"]

    assert review_pack.status_code == 200
    pack_payload = review_pack.json()
    assert pack_payload["readiness_contract"] == "nexus-hive-review-pack-v1"
    assert pack_payload["answer_contract"]["schema"] == "nexus-hive-answer-v1"
    assert "/api/review-pack" in pack_payload["proof_bundle"]["review_routes"]
    assert pack_payload["proof_bundle"]["quality_gate_status"] in {"ok", "degraded"}
    assert pack_payload["proof_bundle"]["review_resource_pack"]["scenario_count"] >= 4
    assert "/api/runtime/review-resource-pack" in pack_payload["proof_bundle"]["review_routes"]
    assert (
        "/api/runtime/warehouse-target-scorecard" in pack_payload["proof_bundle"]["review_routes"]
    )
    assert "/api/runtime/governance-scorecard" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/runtime/semantic-governance-pack" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/runtime/lakehouse-readiness-pack" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/schema/metrics" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/query-session-board" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/evals/nl2sql-gold" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/query-review-board" in pack_payload["proof_bundle"]["review_routes"]
    assert "/api/query-audit/summary" in pack_payload["proof_bundle"]["review_routes"]
    assert isinstance(pack_payload["executive_promises"], list)
    assert len(pack_payload["two_minute_review"]) >= 9
    assert pack_payload["proof_assets"][0]["href"] == "/health"
    assert any(
        asset["href"] == "/api/runtime/review-resource-pack"
        for asset in pack_payload["proof_assets"]
    )
    assert any(
        asset["href"] == "/api/runtime/warehouse-target-scorecard"
        for asset in pack_payload["proof_assets"]
    )
    assert any(
        asset["href"] == "/api/runtime/semantic-governance-pack"
        for asset in pack_payload["proof_assets"]
    )
    assert any(
        asset["href"] == "/api/runtime/lakehouse-readiness-pack"
        for asset in pack_payload["proof_assets"]
    )
    assert any(asset["href"] == "/api/schema/metrics" for asset in pack_payload["proof_assets"])
    assert any(
        asset["href"] == "/api/runtime/governance-scorecard"
        for asset in pack_payload["proof_assets"]
    )
    assert any(
        asset["href"] == "/api/query-session-board" for asset in pack_payload["proof_assets"]
    )
    assert any(asset["href"] == "/api/query-review-board" for asset in pack_payload["proof_assets"])

    assert answer_schema.status_code == 200
    schema_payload = answer_schema.json()
    assert schema_payload["schema"] == "nexus-hive-answer-v1"
    assert "sql_query" in schema_payload["required_sections"]

    assert query_audit_schema.status_code == 200
    query_audit_schema_payload = query_audit_schema.json()
    assert query_audit_schema_payload["schema"] == "nexus-hive-query-audit-v1"
    assert "request_id" in query_audit_schema_payload["required_fields"]

    assert query_session_board.status_code == 200
    query_session_board_payload = query_session_board.json()
    assert query_session_board_payload["schema"] == "nexus-hive-query-session-board-v1"
    assert query_session_board_payload["summary"]["total_sessions"] == 0

    assert query_approval_board.status_code == 200
    query_approval_board_payload = query_approval_board.json()
    assert query_approval_board_payload["schema"] == "nexus-hive-query-approval-board-v1"
    assert query_approval_board_payload["summary"]["pending_count"] == 0

    assert query_review_board.status_code == 200
    query_review_board_payload = query_review_board.json()
    assert query_review_board_payload["schema"] == "nexus-hive-query-review-board-v1"
    assert query_review_board_payload["summary"]["total_requests"] == 0

    assert query_audit_summary.status_code == 200
    query_audit_summary_payload = query_audit_summary.json()
    assert query_audit_summary_payload["schema"] == "nexus-hive-query-audit-summary-v1"
    assert "total_requests" in query_audit_summary_payload["summary"]
    assert isinstance(query_audit_summary_payload["top_questions"], list)

    assert policy_schema.status_code == 200
    policy_schema_payload = policy_schema.json()
    assert policy_schema_payload["schema"] == "nexus-hive-policy-v1"
    assert "wildcard_projection_denied" in policy_schema_payload["deny_rules"]

    assert query_tag_schema.status_code == 200
    query_tag_payload = query_tag_schema.json()
    assert query_tag_payload["schema"] == "nexus-hive-query-tag-v1"
    assert "request_id" in query_tag_payload["required_dimensions"]

    assert lineage_schema.status_code == 200
    lineage_payload = lineage_schema.json()
    assert lineage_payload["schema"] == "nexus-hive-lineage-v1"
    assert len(lineage_payload["relationships"]) == 2

    assert metrics_schema.status_code == 200
    metrics_payload = metrics_schema.json()
    assert metrics_payload["schema"] == "nexus-hive-metric-layer-v1"
    assert metrics_payload["metrics"][0]["metric_id"] == "net_revenue"
    assert "gross_revenue" in metrics_payload["approval_policy"]["certified_metrics"]
    assert metrics_payload["approval_policy"]["warehouse_targets"] == [
        "sqlite-demo",
        "snowflake-sql-contract",
        "databricks-sql-contract",
    ]

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
    assert recent_query_audit_payload["filters"]["limit"] == 5
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
    assert payload["links"]["query_tag_schema"].endswith("/api/schema/query-tag")
    assert payload["links"]["gold_eval"].endswith("/api/evals/nl2sql-gold")
    assert payload["links"]["query_session_board"].endswith("/api/query-session-board")
    assert payload["links"]["query_approval_board"].endswith("/api/query-approval-board")
    assert payload["links"]["query_audit_summary"].endswith("/api/query-audit/summary")
    assert payload["links"]["query_audit_recent"].endswith("/api/query-audit/recent")
    assert payload["links"]["query_audit_detail"].endswith(
        f"/api/query-audit/{payload['request_id']}"
    )
    assert payload["query_tag_preview"].startswith("service=nexus-hive;adapter=sqlite-demo;")

    audit_response = client.get("/api/query-audit/recent")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    assert any(
        item["request_id"] == payload["request_id"]
        and item["status"] == "accepted"
        and item["stage"] == "accepted"
        for item in audit_payload["items"]
    )

    session_board_response = client.get("/api/query-session-board")
    assert session_board_response.status_code == 200
    session_board_payload = session_board_response.json()
    assert session_board_payload["summary"]["total_sessions"] >= 1
    assert any(
        item["request_id"] == payload["request_id"] for item in session_board_payload["items"]
    )


def test_policy_check_exposes_approval_bundle_for_review_queries() -> None:
    client = TestClient(APP_MODULE.app)

    response = client.post(
        "/api/policy/check",
        json={"sql": "SELECT transaction_id FROM sales", "role": "analyst"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"]["decision"] == "review"
    assert payload["approval_required"] is True
    assert (
        "non_aggregated_queries_without_limit_require_operator_review"
        in payload["verdict"]["review_reasons"]
    )
    assert payload["links"]["query_approval_board"] == "/api/query-approval-board"
    assert len(payload["approval_actions"]) >= 3


def test_query_approval_board_surfaces_review_required_requests() -> None:
    APP_MODULE.write_query_audit_snapshot(
        request_id="approval123",
        question="Show raw transaction ids",
        status="completed",
        stage="completed",
        sql_query="SELECT transaction_id FROM sales",
        policy_decision="review",
        policy_reasons=["non_aggregated_queries_without_limit_require_operator_review"],
    )
    client = TestClient(APP_MODULE.app)

    response = client.get("/api/query-approval-board")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["pending_count"] >= 1
    assert any(item["request_id"] == "approval123" for item in payload["items"])


def test_operator_session_cookie_reuses_token_for_protected_routes() -> None:
    previous_token = os.environ.get("NEXUS_HIVE_OPERATOR_TOKEN")
    previous_roles = os.environ.get("NEXUS_HIVE_OPERATOR_ALLOWED_ROLES")
    os.environ["NEXUS_HIVE_OPERATOR_TOKEN"] = "nexus-session-secret"
    os.environ["NEXUS_HIVE_OPERATOR_ALLOWED_ROLES"] = "analyst"
    client = TestClient(APP_MODULE.app)

    try:
        session_response = client.post(
            "/api/auth/session",
            json={
                "credential": "nexus-session-secret",
                "roles": ["analyst"],
            },
        )
        assert session_response.status_code == 200
        assert "nexus_hive_operator_session=" in str(
            session_response.headers.get("set-cookie") or ""
        )

        session_payload = session_response.json()
        assert session_payload["active"] is True
        assert "analyst" in session_payload["session"]["roles"]

        policy_response = client.post(
            "/api/policy/check",
            json={"sql": "SELECT region_name FROM regions", "role": "analyst"},
        )
        assert policy_response.status_code == 200
        assert policy_response.json()["query_tag_preview"].startswith(
            "service=nexus-hive;adapter=sqlite-demo;"
        )

        current_session = client.get("/api/auth/session")
        assert current_session.status_code == 200
        current_session_payload = current_session.json()
        assert current_session_payload["active"] is True
        assert current_session_payload["validation"]["ok"] is True

        cleared = client.delete("/api/auth/session")
        assert cleared.status_code == 200
        assert "Max-Age=0" in str(cleared.headers.get("set-cookie") or "")
    finally:
        if previous_token is None:
            os.environ.pop("NEXUS_HIVE_OPERATOR_TOKEN", None)
        else:
            os.environ["NEXUS_HIVE_OPERATOR_TOKEN"] = previous_token
        if previous_roles is None:
            os.environ.pop("NEXUS_HIVE_OPERATOR_ALLOWED_ROLES", None)
        else:
            os.environ["NEXUS_HIVE_OPERATOR_ALLOWED_ROLES"] = previous_roles


def test_stream_completion_writes_query_audit_detail(monkeypatch) -> None:
    async def fail_ollama(_: str) -> str:
        raise RuntimeError("offline")

    monkeypatch.setattr(APP_MODULE, "ask_ollama", fail_ollama)
    client = TestClient(APP_MODULE.app)

    accepted = client.post("/api/ask", json={"question": "Show total revenue by region"})
    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    request_id = accepted_payload["request_id"]

    stream_response = client.get(
        f"/api/stream?q=Show%20total%20revenue%20by%20region&rid={request_id}"
    )
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

    denied = client.post(
        "/api/policy/check", json={"sql": "SELECT * FROM sales", "role": "analyst"}
    )
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

    governance = client.get("/api/runtime/governance-scorecard?focus=policy")
    assert governance.status_code == 200
    governance_payload = governance.json()
    assert governance_payload["focus"] == "policy"
    assert governance_payload["persistence"]["event_type_counts"]["policy_check"] >= 1
    assert governance_payload["persistence"]["event_type_counts"]["scorecard_view"] >= 1


def test_operator_token_can_guard_mutating_routes() -> None:
    previous = os.environ.get("NEXUS_HIVE_OPERATOR_TOKEN")
    previous_roles = os.environ.get("NEXUS_HIVE_OPERATOR_ALLOWED_ROLES")
    os.environ["NEXUS_HIVE_OPERATOR_TOKEN"] = "nexus-token"
    os.environ["NEXUS_HIVE_OPERATOR_ALLOWED_ROLES"] = "reviewer"
    client = TestClient(APP_MODULE.app)
    try:
        denied = client.post("/api/ask", json={"question": "Show total revenue by region"})
        assert denied.status_code == 403

        denied_role = client.post(
            "/api/ask",
            headers={"authorization": "Bearer nexus-token"},
            json={"question": "Show total revenue by region"},
        )
        assert denied_role.status_code == 403

        allowed = client.post(
            "/api/ask",
            headers={
                "authorization": "Bearer nexus-token",
                "x-operator-role": "reviewer",
            },
            json={"question": "Show total revenue by region"},
        )
        assert allowed.status_code == 200
    finally:
        if previous is None:
            os.environ.pop("NEXUS_HIVE_OPERATOR_TOKEN", None)
        else:
            os.environ["NEXUS_HIVE_OPERATOR_TOKEN"] = previous
        if previous_roles is None:
            os.environ.pop("NEXUS_HIVE_OPERATOR_ALLOWED_ROLES", None)
        else:
            os.environ["NEXUS_HIVE_OPERATOR_ALLOWED_ROLES"] = previous_roles


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
    assert (
        "non_aggregated_queries_without_limit_require_operator_review"
        in review_policy["review_reasons"]
    )


def test_query_audit_summary_filters_and_top_questions(monkeypatch, tmp_path) -> None:
    audit_path = tmp_path / "query_audit.jsonl"
    monkeypatch.setattr(APP_MODULE, "AUDIT_LOG_PATH", audit_path)

    APP_MODULE.write_query_audit_snapshot(
        request_id="req-allow-1",
        question="Show total revenue by region",
        status="completed",
        stage="completed",
        sql_query="SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name LIMIT 10",
        policy_decision="allow",
        fallback_sql_used=False,
        fallback_chart_used=False,
    )
    APP_MODULE.write_query_audit_snapshot(
        request_id="req-review-1",
        question="Show total revenue by region",
        status="completed",
        stage="completed",
        sql_query="SELECT transaction_id FROM sales",
        policy_decision="review",
        policy_reasons=["non_aggregated_queries_without_limit_require_operator_review"],
        fallback_sql_used=True,
        fallback_chart_used=False,
    )
    APP_MODULE.write_query_audit_snapshot(
        request_id="req-deny-1",
        question="Show margin by manager",
        status="failed",
        stage="failed",
        sql_query="SELECT * FROM sales",
        policy_decision="deny",
        policy_reasons=["wildcard_projection_denied"],
        fallback_sql_used=False,
        fallback_chart_used=True,
        error="Policy denied query",
    )

    client = TestClient(APP_MODULE.app)

    summary = client.get("/api/query-audit/summary?limit=2&fallback_mode=any")
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["schema"] == "nexus-hive-query-audit-summary-v1"
    assert summary_payload["filters"]["fallback_mode"] == "any"
    assert summary_payload["summary"]["total_requests"] == 2
    assert summary_payload["summary"]["policy_decision_counts"]["review"] == 1
    assert summary_payload["summary"]["policy_decision_counts"]["deny"] == 1
    assert summary_payload["summary"]["fallback_sql_count"] == 1
    assert summary_payload["summary"]["fallback_chart_count"] == 1
    assert (
        summary_payload["top_policy_reasons"][0]["reason"]
        == "non_aggregated_queries_without_limit_require_operator_review"
    )
    assert {item["normalized_question"] for item in summary_payload["top_questions"]} == {
        "show total revenue by region",
        "show margin by manager",
    }
    assert len(summary_payload["recent_items"]) == 2

    filtered_recent = client.get(
        "/api/query-audit/recent?status=completed&policy_decision=review&fallback_mode=sql&limit=5"
    )
    assert filtered_recent.status_code == 200
    filtered_recent_payload = filtered_recent.json()
    assert filtered_recent_payload["filters"]["fallback_mode"] == "sql"
    assert filtered_recent_payload["filters"]["status"] == "completed"
    assert filtered_recent_payload["filters"]["policy_decision"] == "review"
    assert len(filtered_recent_payload["items"]) == 1
    assert filtered_recent_payload["items"][0]["request_id"] == "req-review-1"

    invalid_filter = client.get("/api/query-audit/summary?fallback_mode=bad")
    assert invalid_filter.status_code == 400


def test_reviewer_query_demo_returns_bounded_live_envelope(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-nexus-live")
    monkeypatch.setenv("OPENAI_PUBLIC_RPM", "3")

    async def _fake_moderation(api_key: str, payload: str) -> None:
        assert api_key == "sk-nexus-live"
        assert "revenue-by-region" in payload

    async def _fake_summary(api_key: str, model: str, payload: dict) -> dict:
        assert api_key == "sk-nexus-live"
        assert model == "gpt-4.1-mini"
        assert payload["warehouse_target"] == "snowflake-sql-contract"
        return {
            "reviewerSummary": "Certified revenue metric survives the Snowflake contract path.",
            "warehouseFit": "snowflake-strong",
            "approvalReason": "Certified metric plus explicit regional grouping",
            "metricTrust": "certified",
            "nextAction": "open semantic governance pack",
        }

    monkeypatch.setattr(APP_MODULE, "call_openai_moderation", _fake_moderation)
    monkeypatch.setattr(APP_MODULE, "call_openai_reviewer_demo_summary", _fake_summary)

    client = TestClient(APP_MODULE.app)
    response = client.post(
        "/api/runtime/reviewer-query-demo",
        json={"question_id": "revenue-by-region"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "nexus-hive-reviewer-query-demo-v1"
    assert payload["mode"] == "public-capped-live"
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["scenarioId"] == "revenue-by-region"
    assert payload["nextReviewPath"] == "/api/runtime/semantic-governance-pack"
    assert payload["result"]["approvalPosture"] == "allow"
    assert payload["result"]["warehouseFit"] == "snowflake-strong"


def test_query_review_board_prioritizes_attention_items(monkeypatch, tmp_path) -> None:
    audit_path = tmp_path / "query_review_board.jsonl"
    monkeypatch.setattr(APP_MODULE, "AUDIT_LOG_PATH", audit_path)

    APP_MODULE.write_query_audit_snapshot(
        request_id="req-failed",
        question="Show failed pipeline revenue",
        status="failed",
        stage="failed",
        sql_query="SELECT region, revenue FROM sales",
        row_count=0,
        retry_count=3,
        chart_type="bar",
        error="sql execution failed",
        policy_decision="allow",
        fallback_sql_used=False,
        fallback_chart_used=False,
    )
    APP_MODULE.write_query_audit_snapshot(
        request_id="req-review",
        question="Show revenue by rep and customer",
        status="completed",
        stage="completed",
        sql_query="SELECT rep_name, customer_name, revenue FROM sales",
        row_count=12,
        retry_count=0,
        chart_type="bar",
        error="",
        policy_decision="review",
        policy_reasons=["sensitive_columns_need_review"],
        fallback_sql_used=True,
        fallback_chart_used=False,
    )
    APP_MODULE.write_query_audit_snapshot(
        request_id="req-healthy",
        question="Show revenue by region",
        status="completed",
        stage="completed",
        sql_query="SELECT region, SUM(revenue) FROM sales GROUP BY region",
        row_count=4,
        retry_count=0,
        chart_type="bar",
        error="",
        policy_decision="allow",
        fallback_sql_used=False,
        fallback_chart_used=False,
    )

    client = TestClient(APP_MODULE.app)
    response = client.get("/api/query-review-board?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "nexus-hive-query-review-board-v1"
    assert payload["summary"]["attention_count"] == 2
    assert payload["attention_items"][0]["request_id"] == "req-failed"
    assert payload["attention_items"][1]["request_id"] == "req-review"
    assert payload["attention_items"][1]["fallback_mode"]["sql"] is True
    assert payload["healthy_items"][0]["request_id"] == "req-healthy"

    invalid = client.get("/api/query-review-board?fallback_mode=bad")
    assert invalid.status_code == 400


def test_runtime_surfaces_can_switch_adapter_contract(monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_HIVE_WAREHOUSE_ADAPTER", "databricks-sql-contract")

    warehouse_brief = APP_MODULE.build_warehouse_brief()
    runtime_brief = APP_MODULE.build_runtime_brief()

    assert warehouse_brief["warehouse_mode"] == "databricks-sql-contract"
    assert warehouse_brief["selected_adapter"]["execution_mode"] == "contract-preview"
    assert runtime_brief["warehouse_contract"]["mode"] == "databricks-sql-contract"
    assert runtime_brief["warehouse_contract"]["query_tag_schema"] == "nexus-hive-query-tag-v1"
