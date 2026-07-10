from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def normalize_base_url(raw_url: str, has_operator_token: bool) -> str:
    base_url = raw_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("NEXUS_HIVE_BASE_URL must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise ValueError("NEXUS_HIVE_BASE_URL must not contain user information.")
    if has_operator_token and parsed.scheme != "https" and parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("Operator tokens require HTTPS for non-loopback runtime URLs.")
    return base_url


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


OPERATOR_TOKEN = str(os.getenv("NEXUS_HIVE_OPERATOR_TOKEN", "")).strip()
BASE_URL = normalize_base_url(
    str(os.getenv("NEXUS_HIVE_BASE_URL", "http://127.0.0.1:8000")),
    bool(OPERATOR_TOKEN),
)
BASE_HOST = urllib.parse.urlsplit(BASE_URL).hostname
HTTP_OPENER = urllib.request.build_opener(NoRedirectHandler())


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{BASE_URL}{path}", data=body, method=method)
    request.add_header("Content-Type", "application/json")
    if OPERATOR_TOKEN:
        request.add_header("Authorization", f"Bearer {OPERATOR_TOKEN}")
    try:
        with HTTP_OPENER.open(request, timeout=10) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except urllib.error.URLError:
        if BASE_HOST not in LOOPBACK_HOSTS:
            raise
        with TestClient(app) as client:
            response = client.request(
                method,
                path,
                json=payload,
                headers={
                    "Authorization": f"Bearer {OPERATOR_TOKEN}",
                }
                if OPERATOR_TOKEN
                else None,
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())


def main() -> None:
    accepted = request_json("/api/ask", "POST", {"question": "Show total revenue by region"})
    scorecard = request_json("/api/runtime/governance-scorecard?focus=quality")
    approval_board = request_json("/api/query-approval-board?limit=3")
    review_board = request_json("/api/query-review-board?limit=3")
    audit = request_json("/api/query-audit/recent?limit=1")
    print(
        json.dumps(
            {
                "accepted": {
                    "request_id": accepted["request_id"],
                    "stream_url": accepted["stream_url"],
                },
                "scorecard": scorecard["summary"],
                "approval_board": approval_board["summary"],
                "review_board": review_board["summary"],
                "recent_audit": audit["items"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
