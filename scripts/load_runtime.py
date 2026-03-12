from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app


ITERATIONS = max(1, int(os.getenv("NEXUS_HIVE_LOAD_ITERATIONS", "6")))
TOKEN = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()


def build_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def main() -> None:
    headers = build_headers()
    with TestClient(app) as client:
        for _ in range(ITERATIONS):
            accepted = client.post(
                "/api/ask",
                json={"question": "Show total revenue by region"},
                headers=headers,
            )
            accepted.raise_for_status()

        preview = client.post(
            "/api/policy/check",
            json={"sql": "SELECT transaction_id FROM sales", "role": "analyst"},
            headers=headers,
        )
        preview.raise_for_status()

        scorecard = client.get("/api/runtime/governance-scorecard?focus=throughput")
        scorecard.raise_for_status()
        approval_board = client.get("/api/query-approval-board?limit=3")
        approval_board.raise_for_status()
        review_board = client.get("/api/query-review-board?limit=3")
        review_board.raise_for_status()
        payload = scorecard.json()

    print(
        json.dumps(
            {
                "summary": payload["summary"],
                "persistence": payload["persistence"],
                "operator_auth": payload["operator_auth"],
                "approval_board": approval_board.json()["summary"],
                "review_board": review_board.json()["summary"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
