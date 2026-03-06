from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


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

    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["service"] == "nexus-hive"
    assert health_payload["links"]["meta"] == "/api/meta"
    assert health_payload["diagnostics"]["db_ready"] is True
    assert health_payload["ops_contract"]["schema"] == "ops-envelope-v1"
    assert "next_action" in health_payload["diagnostics"]

    assert meta.status_code == 200
    meta_payload = meta.json()
    assert meta_payload["service"] == "nexus-hive"
    assert meta_payload["diagnostics"]["schema_loaded"] is True
    assert meta_payload["ops_contract"]["schema"] == "ops-envelope-v1"
    assert "/api/ask" in meta_payload["routes"]


def test_ask_endpoint_returns_stream_pointer() -> None:
    client = TestClient(APP_MODULE.app)

    response = client.post("/api/ask", json={"question": "Show total revenue by region"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["question"] == "Show total revenue by region"
    assert "/api/stream?q=Show+total+revenue+by+region" in payload["stream_url"]
