"""
API endpoint tests for Nexus-Hive FastAPI routes.

Covers health, meta, policy check, ask, query audit, and error handling
for invalid inputs. Tests are isolated from the existing runtime endpoint
tests to focus on specific endpoint behaviors and edge cases.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create an isolated test client with a temporary audit path.

    Ensures audit entries created during tests do not leak to other
    test modules.
    """
    audit_path = tmp_path / "api_test_audit.jsonl"

    # Patch config before any request triggers _sync_audit_log_path
    import config as _cfg
    monkeypatch.setattr(_cfg, "AUDIT_LOG_PATH", audit_path)

    # Also patch main module's local reference
    import main as _main
    monkeypatch.setattr(_main, "AUDIT_LOG_PATH", audit_path)

    from fastapi.testclient import TestClient
    return TestClient(_main.app)


# ---------------------------------------------------------------------------
# Health and meta endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, client) -> None:
        """Health endpoint should return 200 with service info."""
        response = client.get("/health")
        assert response.status_code == 200
        payload: Dict[str, Any] = response.json()
        assert payload["service"] == "nexus-hive"
        assert "diagnostics" in payload

    def test_health_includes_request_id(self, client) -> None:
        """Health response should include x-request-id header."""
        response = client.get("/health")
        assert "x-request-id" in response.headers


class TestMetaEndpoint:
    """Tests for the /api/meta endpoint."""

    def test_meta_returns_200(self, client) -> None:
        """Meta endpoint should return 200 with full runtime info."""
        response = client.get("/api/meta")
        assert response.status_code == 200
        payload: Dict[str, Any] = response.json()
        assert "routes" in payload
        assert "capabilities" in payload


# ---------------------------------------------------------------------------
# Ask endpoint edge cases
# ---------------------------------------------------------------------------


class TestAskEndpoint:
    """Tests for the /api/ask endpoint edge cases."""

    def test_empty_question_rejected(self, client) -> None:
        """Empty question should return 400."""
        response = client.post("/api/ask", json={"question": ""})
        assert response.status_code == 400
        assert "required" in response.json()["detail"].lower()

    def test_too_long_question_rejected(self, client) -> None:
        """Question exceeding 1000 chars should return 413."""
        response = client.post("/api/ask", json={"question": "x" * 1001})
        assert response.status_code == 413

    def test_valid_question_accepted(self, client) -> None:
        """Valid question should return 200 with stream URL."""
        response = client.post(
            "/api/ask", json={"question": "Show revenue by region"}
        )
        assert response.status_code == 200
        payload: Dict[str, Any] = response.json()
        assert payload["status"] == "accepted"
        assert "stream_url" in payload
        assert "request_id" in payload


# ---------------------------------------------------------------------------
# Policy check endpoint
# ---------------------------------------------------------------------------


class TestPolicyCheckEndpoint:
    """Tests for the /api/policy/check endpoint."""

    def test_empty_sql_rejected(self, client) -> None:
        """Empty SQL should return 400."""
        response = client.post(
            "/api/policy/check", json={"sql": "", "role": "analyst"}
        )
        assert response.status_code == 400

    def test_safe_sql_allowed(self, client) -> None:
        """Safe SQL should be allowed by policy."""
        response = client.post(
            "/api/policy/check",
            json={
                "sql": "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name LIMIT 10",
                "role": "analyst",
            },
        )
        assert response.status_code == 200
        payload: Dict[str, Any] = response.json()
        assert payload["verdict"]["decision"] == "allow"

    def test_wildcard_sql_denied(self, client) -> None:
        """SELECT * should be denied by policy."""
        response = client.post(
            "/api/policy/check",
            json={"sql": "SELECT * FROM sales", "role": "analyst"},
        )
        assert response.status_code == 200
        assert response.json()["verdict"]["decision"] == "deny"


# ---------------------------------------------------------------------------
# Query audit endpoint
# ---------------------------------------------------------------------------


class TestQueryAuditEndpoint:
    """Tests for query audit endpoints."""

    def test_nonexistent_request_id_404(self, client) -> None:
        """Looking up a nonexistent request_id should return 404."""
        response = client.get("/api/query-audit/nonexistent-id-12345")
        assert response.status_code == 404

    def test_invalid_filter_returns_400(self, client) -> None:
        """Invalid fallback_mode filter should return 400."""
        response = client.get("/api/query-audit/recent?fallback_mode=invalid")
        assert response.status_code == 400

    def test_recent_with_valid_filters(self, client) -> None:
        """Recent audit endpoint should accept valid filters."""
        response = client.get("/api/query-audit/recent?limit=3")
        assert response.status_code == 200
        assert "items" in response.json()


# ---------------------------------------------------------------------------
# Schema endpoints
# ---------------------------------------------------------------------------


class TestSchemaEndpoints:
    """Tests for schema descriptor endpoints."""

    def test_answer_schema(self, client) -> None:
        """Answer schema should return the expected contract."""
        response = client.get("/api/schema/answer")
        assert response.status_code == 200
        assert response.json()["schema"] == "nexus-hive-answer-v1"

    def test_lineage_schema(self, client) -> None:
        """Lineage schema should include relationships."""
        response = client.get("/api/schema/lineage")
        assert response.status_code == 200
        assert len(response.json()["relationships"]) == 2

    def test_metric_schema(self, client) -> None:
        """Metric schema should include certified metrics."""
        response = client.get("/api/schema/metrics")
        assert response.status_code == 200
        assert "metrics" in response.json()

    def test_policy_schema(self, client) -> None:
        """Policy schema should include deny rules."""
        response = client.get("/api/schema/policy")
        assert response.status_code == 200
        assert "deny_rules" in response.json()
