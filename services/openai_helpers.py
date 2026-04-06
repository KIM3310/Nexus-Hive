"""
OpenAI API helper functions for moderation and reviewer demo summaries.

The actual callable references are stored in `moderation_fn` and `summary_fn`
so that test monkeypatching on the main module can propagate here.
"""

import json
from typing import Any, Dict

import httpx
from fastapi import HTTPException

from config import OPENAI_BASE_URL, OPENAI_TIMEOUT_S


async def _call_openai_moderation(api_key: str, payload: str) -> None:
    async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_S) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/moderations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": "omni-moderation-latest", "input": payload},
        )
        response.raise_for_status()
        data = response.json()
    if data.get("results", [{}])[0].get("flagged"):
        raise HTTPException(status_code=400, detail="reviewer scenario blocked by moderation")


async def _call_openai_reviewer_demo_summary(
    api_key: str, model: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_S) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a governed analytics reviewer. Return JSON with keys "
                            "reviewerSummary, warehouseFit, approvalReason, metricTrust, nextAction."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=True),
                    },
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
    content = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=502, detail="OpenAI reviewer demo returned empty content")
    try:
        result: Dict[str, Any] = json.loads(content)
        return result
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail="OpenAI reviewer demo returned invalid JSON"
        ) from exc


# Public references - these are what routes should call.
# main.py re-exports call_openai_moderation / call_openai_reviewer_demo_summary
# so tests can monkeypatch them on the main module.  To make that work the
# route reads through *this* module's attribute at call time.
call_openai_moderation = _call_openai_moderation
call_openai_reviewer_demo_summary = _call_openai_reviewer_demo_summary
