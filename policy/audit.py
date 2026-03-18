"""
Query audit trail: snapshot storage, filtering, summary, review board, session board, approval board.
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from config import (
    AUDIT_LOG_PATH,
    AUDIT_POLICY_DECISION_VALUES,
    AUDIT_STATUS_VALUES,
    QUERY_APPROVAL_BOARD_SCHEMA,
    QUERY_SESSION_BOARD_SCHEMA,
    normalize_question,
    utc_now_iso,
)


def build_query_audit_schema() -> Dict[str, Any]:
    return {
        "schema": "nexus-hive-query-audit-v1",
        "storage_mode": "append-only jsonl snapshots with latest-state views per request_id",
        "required_fields": [
            "request_id",
            "question",
            "status",
            "stage",
            "adapter_name",
            "query_tag",
            "sql_query",
            "row_count",
            "retry_count",
            "policy_decision",
            "fallback_sql_used",
            "fallback_chart_used",
            "updated_at",
        ],
        "stages": ["accepted", "completed", "failed"],
        "operator_rules": [
            "Each governed query keeps a stable request_id from acceptance through terminal state.",
            "SQL text should remain reviewable even when execution fails.",
            "Audit history is for review posture, not a substitute for warehouse-native lineage tooling.",
        ],
    }


def append_query_audit_snapshot(snapshot: Dict[str, Any]) -> None:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=True) + "\n")


def write_query_audit_snapshot(
    *,
    request_id: str,
    question: str,
    status: str,
    stage: str,
    adapter_name: str = "sqlite-demo",
    query_tag: str = "",
    sql_query: str = "",
    row_count: int = 0,
    retry_count: int = 0,
    chart_type: str = "",
    error: str = "",
    policy_decision: str = "",
    policy_reasons: Optional[List[str]] = None,
    fallback_sql_used: bool = False,
    fallback_chart_used: bool = False,
) -> None:
    timestamp = utc_now_iso()
    append_query_audit_snapshot(
        {
            "service": "nexus-hive",
            "request_id": request_id,
            "question": question,
            "status": status,
            "stage": stage,
            "adapter_name": adapter_name,
            "query_tag": query_tag,
            "sql_query": sql_query,
            "row_count": row_count,
            "retry_count": retry_count,
            "chart_type": chart_type,
            "error": error,
            "policy_decision": policy_decision,
            "policy_reasons": policy_reasons or [],
            "fallback_sql_used": fallback_sql_used,
            "fallback_chart_used": fallback_chart_used,
            "updated_at": timestamp,
        }
    )


def iter_query_audit_snapshots() -> List[Dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []

    snapshots: List[Dict[str, Any]] = []
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                snapshots.append(payload)

    return snapshots


def clamp_audit_limit(limit: int, *, default: int = 5, maximum: int = 20) -> int:
    if not isinstance(limit, int):
        return default
    return max(1, min(limit, maximum))


def normalize_audit_status_filter(status: Optional[str]) -> Optional[str]:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return None
    if normalized not in AUDIT_STATUS_VALUES:
        raise HTTPException(status_code=400, detail="invalid status filter")
    return normalized


def normalize_policy_decision_filter(policy_decision: Optional[str]) -> Optional[str]:
    normalized = str(policy_decision or "").strip().lower()
    if not normalized:
        return None
    if normalized not in AUDIT_POLICY_DECISION_VALUES:
        raise HTTPException(status_code=400, detail="invalid policy_decision filter")
    return normalized


def normalize_fallback_mode_filter(fallback_mode: Optional[str]) -> Optional[str]:
    normalized = str(fallback_mode or "").strip().lower()
    if not normalized:
        return None
    if normalized not in {"none", "sql", "chart", "any"}:
        raise HTTPException(status_code=400, detail="invalid fallback_mode filter")
    return normalized


def matches_fallback_mode(item: Dict[str, Any], fallback_mode: Optional[str]) -> bool:
    if fallback_mode is None:
        return True
    fallback_sql = bool(item.get("fallback_sql_used"))
    fallback_chart = bool(item.get("fallback_chart_used"))
    if fallback_mode == "sql":
        return fallback_sql
    if fallback_mode == "chart":
        return fallback_chart
    if fallback_mode == "any":
        return fallback_sql or fallback_chart
    return not fallback_sql and not fallback_chart


def list_latest_query_audits(
    *,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> List[Dict[str, Any]]:
    latest_by_request: Dict[str, Dict[str, Any]] = {}
    for payload in iter_query_audit_snapshots():
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            continue
        latest_by_request[request_id] = payload

    items = list(latest_by_request.values())
    if status:
        items = [item for item in items if str(item.get("status") or "").strip().lower() == status]
    if policy_decision:
        items = [
            item
            for item in items
            if str(item.get("policy_decision") or "").strip().lower() == policy_decision
        ]
    if fallback_mode:
        items = [item for item in items if matches_fallback_mode(item, fallback_mode)]

    return sorted(
        items,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )


def list_recent_query_audits(
    limit: int = 5,
    *,
    fallback_mode: Optional[str] = None,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> List[Dict[str, Any]]:
    items = list_latest_query_audits(
        fallback_mode=fallback_mode,
        status=status,
        policy_decision=policy_decision,
    )
    return items[:clamp_audit_limit(limit)]


def get_query_audit_history(request_id: str) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    for payload in iter_query_audit_snapshots():
        if str(payload.get("request_id") or "").strip() == request_id:
            history.append(payload)

    return sorted(history, key=lambda item: item.get("updated_at", ""))


def build_query_audit_summary(
    *,
    fallback_mode: Optional[str] = None,
    limit: int = 5,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> Dict[str, Any]:
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    recent_limit = clamp_audit_limit(limit, maximum=50)
    latest_items = list_latest_query_audits(
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )
    recent_items = latest_items[:recent_limit]

    status_counts: Dict[str, int] = {}
    policy_counts: Dict[str, int] = {}
    adapter_counts: Dict[str, int] = {}
    policy_reason_counts: Dict[str, int] = {}
    top_questions: Dict[str, Dict[str, Any]] = {}
    fallback_sql_count = 0
    fallback_chart_count = 0
    denied_count = 0
    review_count = 0
    error_count = 0

    for item in latest_items:
        item_status = str(item.get("status") or "unknown").strip().lower() or "unknown"
        item_policy = str(item.get("policy_decision") or "unknown").strip().lower() or "unknown"
        item_adapter = str(item.get("adapter_name") or "unknown").strip().lower() or "unknown"
        status_counts[item_status] = status_counts.get(item_status, 0) + 1
        policy_counts[item_policy] = policy_counts.get(item_policy, 0) + 1
        adapter_counts[item_adapter] = adapter_counts.get(item_adapter, 0) + 1
        fallback_sql_count += 1 if item.get("fallback_sql_used") else 0
        fallback_chart_count += 1 if item.get("fallback_chart_used") else 0
        denied_count += 1 if item_policy == "deny" else 0
        review_count += 1 if item_policy == "review" else 0
        error_count += 1 if str(item.get("error") or "").strip() else 0
        for reason in item.get("policy_reasons") or []:
            normalized_reason = str(reason or "").strip().lower()
            if normalized_reason:
                policy_reason_counts[normalized_reason] = policy_reason_counts.get(normalized_reason, 0) + 1

        question = str(item.get("question") or "").strip()
        normalized_q = normalize_question(question)
        if not normalized_q:
            continue
        bucket = top_questions.setdefault(
            normalized_q,
            {
                "question": question,
                "normalized_question": normalized_q,
                "count": 0,
                "sample_request_ids": [],
            },
        )
        bucket["count"] += 1
        if len(bucket["sample_request_ids"]) < 3:
            bucket["sample_request_ids"].append(str(item.get("request_id") or "").strip())

    sorted_top_questions = sorted(
        top_questions.values(),
        key=lambda item: (-int(item["count"]), str(item["question"]).lower()),
    )[:5]
    top_policy_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(
            policy_reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]

    return {
        "schema": "nexus-hive-query-audit-summary-v1",
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": recent_limit,
        },
        "summary": {
            "total_requests": len(latest_items),
            "status_counts": status_counts,
            "policy_decision_counts": policy_counts,
            "adapter_counts": adapter_counts,
            "fallback_sql_count": fallback_sql_count,
            "fallback_chart_count": fallback_chart_count,
            "denied_count": denied_count,
            "review_required_count": review_count,
            "error_count": error_count,
            "latest_updated_at": recent_items[0]["updated_at"] if recent_items else None,
        },
        "top_policy_reasons": top_policy_reasons,
        "top_questions": sorted_top_questions,
        "recent_items": recent_items,
        "watchouts": [
            "Query audit summary reflects the latest state per request_id, not every intermediate log line.",
            "Fallback counters separate resilience posture from model quality posture.",
            "Policy review and deny counts should be inspected before trusting a demo claim.",
        ],
    }


def build_query_review_board(
    *,
    fallback_mode: Optional[str] = None,
    limit: int = 5,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> Dict[str, Any]:
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    board_limit = clamp_audit_limit(limit)
    latest_items = list_latest_query_audits(
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )

    def item_priority(item: Dict[str, Any]) -> tuple[int, str]:
        item_status = str(item.get("status") or "").strip().lower()
        item_policy = str(item.get("policy_decision") or "").strip().lower()
        if item_status == "failed":
            rank = 0
        elif item_policy == "deny":
            rank = 1
        elif item_policy == "review":
            rank = 2
        elif item.get("fallback_sql_used") or item.get("fallback_chart_used"):
            rank = 3
        else:
            rank = 4
        return (rank, str(item.get("updated_at") or ""))

    attention_items = sorted(latest_items, key=item_priority)[:board_limit]
    healthy_items = [
        item
        for item in latest_items
        if str(item.get("status") or "").strip().lower() == "completed"
        and str(item.get("policy_decision") or "").strip().lower() == "allow"
    ][:board_limit]

    def to_board_item(item: Dict[str, Any]) -> Dict[str, Any]:
        item_status = str(item.get("status") or "").strip().lower() or "unknown"
        item_policy = str(item.get("policy_decision") or "").strip().lower() or "unknown"
        uses_fallback = bool(item.get("fallback_sql_used")) or bool(item.get("fallback_chart_used"))
        if item_status == "failed":
            next_action = "Inspect the audit detail and retry only after fixing the governed SQL path."
        elif item_policy == "deny":
            next_action = "Review deny reasons, remove blocked SQL patterns, and rerun the request."
        elif item_policy == "review":
            next_action = "Validate sensitive columns and escalation reasons before approval."
        elif uses_fallback:
            next_action = "Compare fallback output against the gold eval run before sharing the answer."
        else:
            next_action = "Spot-check SQL, chart payload, and row counts before sharing the answer."
        return {
            "request_id": str(item.get("request_id") or ""),
            "question": str(item.get("question") or ""),
            "status": item_status,
            "policy_decision": item_policy,
            "stage": str(item.get("stage") or ""),
            "updated_at": item.get("updated_at"),
            "fallback_mode": {
                "sql": bool(item.get("fallback_sql_used")),
                "chart": bool(item.get("fallback_chart_used")),
            },
            "row_count": int(item.get("row_count") or 0),
            "retry_count": int(item.get("retry_count") or 0),
            "policy_reasons": item.get("policy_reasons") or [],
            "next_action": next_action,
        }

    audit_summary = build_query_audit_summary(
        fallback_mode=fallback_filter,
        limit=board_limit,
        status=status_filter,
        policy_decision=policy_filter,
    )

    return {
        "schema": "nexus-hive-query-review-board-v1",
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": board_limit,
        },
        "summary": {
            "total_requests": audit_summary["summary"]["total_requests"],
            "attention_count": len(attention_items),
            "healthy_count": len(healthy_items),
            "latest_updated_at": audit_summary["summary"]["latest_updated_at"],
        },
        "attention_items": [to_board_item(item) for item in attention_items],
        "healthy_items": [to_board_item(item) for item in healthy_items],
        "policy_reasons": audit_summary["top_policy_reasons"],
        "review_actions": [
            "Start with failed or denied requests before reviewing successful output.",
            "Use /api/query-audit/{request_id} to inspect one request in detail.",
            "Use /api/policy/check before approving risky SQL changes.",
            "Run /api/evals/nl2sql-gold/run when fallback or review-required items appear.",
        ],
        "links": {
            "query_approval_board": "/api/query-approval-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": "/api/query-audit/{request_id}",
            "policy_check": "/api/policy/check",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
        },
    }


def build_query_session_board(
    *,
    fallback_mode: Optional[str] = None,
    limit: int = 6,
    status: Optional[str] = None,
    policy_decision: Optional[str] = None,
) -> Dict[str, Any]:
    fallback_filter = normalize_fallback_mode_filter(fallback_mode)
    status_filter = normalize_audit_status_filter(status)
    policy_filter = normalize_policy_decision_filter(policy_decision)
    session_limit = clamp_audit_limit(limit)
    latest_items = list_latest_query_audits(
        fallback_mode=fallback_filter,
        status=status_filter,
        policy_decision=policy_filter,
    )[:session_limit]

    def to_session_item(item: Dict[str, Any]) -> Dict[str, Any]:
        item_status = str(item.get("status") or "").strip().lower() or "unknown"
        item_policy = str(item.get("policy_decision") or "").strip().lower() or "unknown"
        uses_fallback = bool(item.get("fallback_sql_used")) or bool(item.get("fallback_chart_used"))
        if item_status == "failed" or item_policy == "deny":
            session_state = "attention"
            next_action = "Reopen audit detail, fix the SQL path, and rerun before sharing."
        elif item_policy == "review":
            session_state = "review"
            next_action = "Check escalation reasons and sensitive columns before approval."
        elif uses_fallback:
            session_state = "compare"
            next_action = "Compare fallback output against the gold eval run before reuse."
        else:
            session_state = "ready"
            next_action = "Spot-check SQL and row counts, then reuse this session as a reference."

        request_id = str(item.get("request_id") or "").strip()
        return {
            "request_id": request_id,
            "headline": str(item.get("question") or "Saved query session"),
            "status": item_status,
            "policy_decision": item_policy,
            "session_state": session_state,
            "updated_at": item.get("updated_at"),
            "row_count": int(item.get("row_count") or 0),
            "retry_count": int(item.get("retry_count") or 0),
            "chart_type": str(item.get("chart_type") or "").strip() or None,
            "fallback_mode": {
                "sql": bool(item.get("fallback_sql_used")),
                "chart": bool(item.get("fallback_chart_used")),
            },
            "review_url": f"/api/query-audit/{request_id}",
            "next_action": next_action,
        }

    session_items = [to_session_item(item) for item in latest_items]
    return {
        "schema": QUERY_SESSION_BOARD_SCHEMA,
        "filters": {
            "fallback_mode": fallback_filter,
            "status": status_filter,
            "policy_decision": policy_filter,
            "limit": session_limit,
        },
        "summary": {
            "total_sessions": len(session_items),
            "ready_count": sum(1 for item in session_items if item["session_state"] == "ready"),
            "attention_count": sum(1 for item in session_items if item["session_state"] == "attention"),
            "review_count": sum(1 for item in session_items if item["session_state"] == "review"),
            "compare_count": sum(1 for item in session_items if item["session_state"] == "compare"),
            "latest_updated_at": session_items[0]["updated_at"] if session_items else None,
        },
        "items": session_items,
        "review_actions": [
            "Open the saved session detail before reusing a generated chart or answer.",
            "Keep attention and review sessions visible until their policy issues are resolved.",
            "Promote ready sessions only after a quick SQL and row-count check.",
        ],
        "links": {
            "query_session_board": "/api/query-session-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_summary": "/api/query-audit/summary",
            "query_audit_recent": "/api/query-audit/recent",
            "query_audit_detail": "/api/query-audit/{request_id}",
        },
    }


def build_query_approval_board(limit: int = 5) -> Dict[str, Any]:
    board_limit = clamp_audit_limit(limit)
    pending_items = list_recent_query_audits(limit=board_limit, policy_decision="review")

    def to_approval_item(item: Dict[str, Any]) -> Dict[str, Any]:
        request_id = str(item.get("request_id") or "").strip()
        return {
            "request_id": request_id,
            "question": str(item.get("question") or ""),
            "sql_query": str(item.get("sql_query") or ""),
            "status": str(item.get("status") or "").strip().lower() or "unknown",
            "stage": str(item.get("stage") or ""),
            "updated_at": item.get("updated_at"),
            "policy_reasons": item.get("policy_reasons") or [],
            "fallback_mode": {
                "sql": bool(item.get("fallback_sql_used")),
                "chart": bool(item.get("fallback_chart_used")),
            },
            "next_action": "Review the SQL scope, rerun /api/policy/check if needed, then inspect /api/query-audit/{request_id} before trusting the answer.",
            "review_url": f"/api/query-audit/{request_id}",
        }

    items = [to_approval_item(item) for item in pending_items]
    return {
        "schema": QUERY_APPROVAL_BOARD_SCHEMA,
        "filters": {
            "limit": board_limit,
            "policy_decision": "review",
        },
        "summary": {
            "pending_count": len(items),
            "fallback_count": sum(
                1 for item in items if item["fallback_mode"]["sql"] or item["fallback_mode"]["chart"]
            ),
            "latest_updated_at": items[0]["updated_at"] if items else None,
        },
        "items": items,
        "review_actions": [
            "Keep review-required queries separate from healthy completed traffic.",
            "Use /api/policy/check to restate why the SQL needs a human look.",
            "Open /api/query-audit/{request_id} before approving the chart or answer.",
        ],
        "links": {
            "query_approval_board": "/api/query-approval-board",
            "query_review_board": "/api/query-review-board",
            "query_audit_detail": "/api/query-audit/{request_id}",
            "policy_check": "/api/policy/check",
            "gold_eval_run": "/api/evals/nl2sql-gold/run",
        },
    }
