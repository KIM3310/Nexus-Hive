from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


BASE_URL = str(os.getenv("NEXUS_HIVE_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
OPERATOR_TOKEN = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{BASE_URL}{path}", data=body, method=method)
    request.add_header("Content-Type", "application/json")
    if OPERATOR_TOKEN:
        request.add_header("Authorization", f"Bearer {OPERATOR_TOKEN}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    accepted = request_json("/api/ask", "POST", {"question": "Show total revenue by region"})
    scorecard = request_json("/api/runtime/governance-scorecard?focus=quality")
    audit = request_json("/api/query-audit/recent?limit=1")
    print(
        json.dumps(
            {
                "accepted": {
                    "request_id": accepted["request_id"],
                    "stream_url": accepted["stream_url"],
                },
                "scorecard": scorecard["summary"],
                "recent_audit": audit["items"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
