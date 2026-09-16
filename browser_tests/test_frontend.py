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
    suffix = (
        "without-chart-cdn"
        if not chart_available
        else ("with-brief-failure" if brief_unavailable else "success")
    )
    capture(page, f"live-result-{suffix}")
