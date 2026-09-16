import re

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("width,height", [(390, 844), (768, 1000), (1440, 1000)])
def test_layout_keeps_publication_below_app(page, static_url, capture, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(static_url)
    expect(page.locator("#status-text")).to_have_text("Recorded review only")
    capture(page, f"layout-{width}")
    app = page.locator(".app-container").bounding_box()
    publication = page.locator(".adsense-publication-nav").bounding_box()
    assert app["width"] >= width * 0.90
    assert publication["y"] >= app["y"] + app["height"] - 1
    assert page.locator("#ask-btn").bounding_box()["width"] >= 120
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_recorded_action_opens_identified_audit_without_asking(page, static_url, capture):
    api_requests = []
    page.on(
        "request",
        lambda request: api_requests.append(request.url) if "/api/" in request.url else None,
    )
    page.goto(static_url)
    try:
        button = page.get_by_role("button", name="View recorded example", exact=True)
        expect(button).to_be_visible()
        question = page.get_by_label("Analytics question", exact=True)
        expect(question).to_have_value("Which region saw the highest Q4 revenue dip?")
        expect(question).to_have_attribute("readonly", "")
        page.evaluate("""() => {
            window.auditFetches = [];
            const originalFetch = window.fetch;
            window.fetch = (...args) => {
                window.auditFetches.push(String(args[0]));
                return originalFetch(...args);
            };
        }""")
        question.evaluate("input => { input.value = 'An unrelated new question'; }")
        button.click()
        expect(question).to_have_value("Which region saw the highest Q4 revenue dip?")
        detail = page.locator("#audit-detail")
        expect(detail).to_contain_text("req-recorded-1042")
        expect(detail).to_contain_text("Decision: REVIEW")
        expect(detail).to_contain_text("regional_revenue")
        expect(detail).to_be_focused()
        expect(page.locator("#query-status")).to_contain_text("No new query")
        assert api_requests == []
        assert page.evaluate("window.auditFetches") == []
        assert "Failed to register" not in page.locator("#agent-logs").inner_text()
    finally:
        capture(page, "recorded-action")


def test_trace_disclosure_has_keyboard_state(page, static_url, capture):
    page.goto(static_url)
    disclosure = page.locator("#sidebarCollapseBtn")
    expect(disclosure).to_have_attribute("aria-controls", "agent-logs")
    expect(disclosure).to_have_attribute("aria-expanded", "true")
    disclosure.focus()
    disclosure.press("Enter")
    expect(disclosure).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#agent-logs")).to_be_hidden()
    disclosure.press("Enter")
    expect(disclosure).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#agent-logs")).to_be_visible()
    capture(page, "trace-disclosure")


def test_recorded_action_does_not_require_chart_cdn(page, static_url, capture):
    page.route("https://cdn.jsdelivr.net/npm/chart.js", lambda route: route.abort())
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(static_url)
    try:
        page.get_by_role("button", name="View recorded example", exact=True).click()
        expect(page.locator("#audit-detail")).to_contain_text("req-recorded-1042")
        expect(page.locator("#audit-detail")).to_contain_text("Decision: REVIEW")
        expect(page.locator("#biChart")).to_be_hidden()
        assert errors == []
    finally:
        capture(page, "recorded-without-chart-cdn")


@pytest.mark.parametrize(
    "brief_unavailable,chart_available", [(False, True), (True, True), (False, False)]
)
def test_live_mode_runs_real_synthetic_query(
    page, live_url, capture, brief_unavailable, chart_available
):
    if not chart_available:
        page.route("https://cdn.jsdelivr.net/npm/chart.js", lambda route: route.abort())
    if brief_unavailable:
        page.route(
            "**/api/runtime/brief",
            lambda route: route.fulfill(status=503, body="Synthetic brief failure"),
        )
    page.add_init_script(f"window.NEXUS_API_BASE = {live_url!r}")
    page.goto(live_url)
    if brief_unavailable:
        expect(page.locator("#brief-badge")).to_have_text("RECORDED")
    question = page.get_by_label("Analytics question", exact=True)
    expect(question).to_be_editable()
    page.get_by_role("button", name="Revenue by Category", exact=True).click()
    expect(question).to_be_focused()
    question.fill("Show total net revenue by region")
    with page.expect_response(lambda response: response.url == f"{live_url}/api/ask") as response:
        question.press("Enter")
    accepted = response.value.json()
    assert response.value.status == 200
    assert re.fullmatch(r"[0-9a-f]{12}", accepted["request_id"])
    expect(page.locator("#audit-detail")).to_contain_text(accepted["request_id"])
    expect(page.locator("#audit-detail")).to_contain_text("Decision: ALLOW")
    expect(page.locator("#audit-detail")).to_contain_text("Rows: 2")
    expect(page.locator("#audit-detail")).to_contain_text("Fallback: fallback=yes")
    expect(page.locator("#ask-btn")).to_be_enabled()
    expect(question).to_be_focused()
    audit = page.request.get(f"{live_url}/api/query-audit/{accepted['request_id']}").json()
    assert audit["latest"]["status"] == "completed"
    assert audit["latest"]["row_count"] == 2
    assert audit["latest"]["fallback_sql_used"] is True
    logs = page.locator("#agent-logs").inner_text()
    if chart_available:
        assert "Chart rendered successfully using 2 data points." in logs
        expect(page.locator("#biChart")).to_be_visible()
    else:
        assert "Chart library unavailable. Review the query audit instead." in logs
        expect(page.locator("#biChart")).to_be_hidden()
        expect(page.locator('#priority-flow [data-step="chart"]')).not_to_have_class(
            re.compile(r".*complete.*")
        )
        expect(page.locator("#priority-lock")).to_contain_text("blocked")
        expect(page.locator("#empty-state")).to_contain_text("Chart library unavailable")
    suffix = (
        "without-chart-cdn"
        if not chart_available
        else ("with-brief-failure" if brief_unavailable else "success")
    )
    capture(page, f"live-result-{suffix}")


def run_synthetic_question(page, live_url, question):
    page.get_by_label("Analytics question", exact=True).fill(question)
    with page.expect_response(lambda response: response.url == f"{live_url}/api/ask") as response:
        page.get_by_label("Analytics question", exact=True).press("Enter")
    request_id = response.value.json()["request_id"]
    expect(page.locator("#audit-detail")).to_contain_text(request_id)
    expect(page.locator("#audit-detail")).to_contain_text("Decision: ALLOW")
    expect(page.locator("#ask-btn")).to_be_enabled()
    return request_id


def test_new_question_clears_previous_evidence(page, live_url, capture):
    page.add_init_script(f"window.NEXUS_API_BASE = {live_url!r}")
    page.goto(live_url)
    previous_id = run_synthetic_question(page, live_url, "Show total net revenue by region")
    pending = []
    page.route(f"{live_url}/api/ask", lambda route: pending.append(route))
    page.get_by_label("Analytics question", exact=True).fill("Show top 5 regions by total profit")
    page.get_by_label("Analytics question", exact=True).press("Enter")
    try:
        expect(page.locator("#ask-btn")).to_be_disabled()
        expect(page.locator("#audit-detail")).not_to_contain_text(previous_id)
        expect(page.locator("#priority-request")).not_to_have_text(previous_id)
        expect(page.locator("#policy-sql-input")).to_have_value("")
    finally:
        for route in pending:
            route.abort()
        expect(page.locator("#ask-btn")).to_be_enabled()
        capture(page, "new-question-evidence")


def test_late_audit_response_cannot_replace_new_query(page, live_url, capture):
    page.add_init_script(f"window.NEXUS_API_BASE = {live_url!r}")
    page.goto(live_url)
    old_id = run_synthetic_question(page, live_url, "Show total net revenue by region")
    old_audit_url = f"{live_url}/api/query-audit/{old_id}"
    held = {}

    def hold_old_audit(route):
        held["response"] = route.fetch()
        held["route"] = route
        page.evaluate("window.oldAuditHeld = true")

    page.route(old_audit_url, hold_old_audit)
    page.get_by_role("button", name="Load Latest SQL", exact=True).click()
    page.wait_for_function("window.oldAuditHeld === true")
    new_id = run_synthetic_question(page, live_url, "Show top 5 regions by total profit")
    try:
        with page.expect_response(lambda response: response.url == old_audit_url) as late_response:
            held["route"].fulfill(response=held["response"])
        assert old_id.encode() in late_response.value.body()
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        expect(page.locator("#audit-detail")).to_contain_text(new_id)
        expect(page.locator("#priority-request")).to_have_text(new_id)
        expect(page.locator("#biChart")).to_be_visible()
    finally:
        capture(page, "late-audit-response")


def test_background_feed_cannot_change_active_request(page, live_url, capture):
    page.add_init_script(f"window.NEXUS_API_BASE = {live_url!r}")
    page.goto(live_url)
    old_id = run_synthetic_question(page, live_url, "Show total net revenue by region")
    held = {}

    def hold_once(name, route):
        if name in held:
            route.continue_()
            return
        held[name] = (route, route.fetch())
        page.evaluate(f"window.{name}Held = true")

    page.route(f"{live_url}/api/query-audit/recent", lambda route: hold_once("feed", route))
    page.route(
        f"{live_url}/api/query-session-board?limit=6", lambda route: hold_once("sessions", route)
    )
    page.reload()
    page.wait_for_function("window.feedHeld && window.sessionsHeld")
    stream = []
    page.route(f"{live_url}/api/stream?**", lambda route: stream.append(route))
    page.get_by_label("Analytics question", exact=True).fill("Show top 5 regions by total profit")
    with page.expect_response(lambda response: response.url == f"{live_url}/api/ask") as accepted:
        page.get_by_label("Analytics question", exact=True).press("Enter")
    active_id = accepted.value.json()["request_id"]
    assert active_id != old_id
    expect(page.locator("#priority-request")).to_have_text(active_id)
    try:
        for name in ("feed", "sessions"):
            route, response = held[name]
            with page.expect_response(lambda candidate: candidate.url == response.url) as released:
                route.fulfill(response=response)
            released.value.body()
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
        expect(page.locator("#priority-request")).to_have_text(active_id)
        expect(page.locator("#audit-detail")).not_to_contain_text(old_id)
    finally:
        for route in stream:
            route.abort()
        expect(page.locator("#ask-btn")).to_be_enabled()
        capture(page, "background-feed-identity")


def test_done_without_chart_finishes_loading_state(page, live_url, capture):
    page.route("https://cdn.jsdelivr.net/npm/chart.js", lambda route: route.abort())
    page.route(
        f"{live_url}/api/stream?**",
        lambda route: route.fulfill(
            content_type="text/event-stream", body='data: {"type": "done"}\n\n'
        ),
    )
    page.add_init_script(f"window.NEXUS_API_BASE = {live_url!r}")
    page.goto(live_url)
    page.get_by_label("Analytics question", exact=True).fill("Show total net revenue by region")
    page.get_by_label("Analytics question", exact=True).press("Enter")
    try:
        expect(page.locator("#query-status")).to_contain_text("finished")
        expect(page.locator("#empty-state")).to_contain_text("Chart library unavailable")
        expect(page.locator("#biChart")).to_be_hidden()
        expect(page.locator("#ask-btn")).to_be_enabled()
    finally:
        capture(page, "done-without-chart-data")
