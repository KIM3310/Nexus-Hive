from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_INDEX = ROOT / "frontend" / "index.html"
PREVIEW_CARD = ROOT / "frontend" / "preview-card.svg"


def test_frontend_metadata_contract() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    required_tokens = [
        'name="description"',
        'property="og:title"',
        'property="og:description"',
        'property="og:image"',
        'property="og:image:alt"',
        'name="twitter:title"',
        'name="twitter:description"',
        'name="twitter:image"',
        "<title>Nexus-Hive | Executive BI Copilot</title>",
    ]

    for token in required_tokens:
        assert token in html, token


def test_frontend_preview_asset_exists() -> None:
    assert PREVIEW_CARD.exists()


def test_reviewer_priority_surface_contract() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    required_tokens = [
        'id="reviewer-priority-panel"',
        'id="priority-flow"',
        'id="priority-thread"',
        'id="priority-route"',
        'Keep one request visible from ask to approval to chart to audit.',
        'Recorded review mode demonstrates workflow shape only.',
        'Trace log',
    ]

    for token in required_tokens:
        assert token in html, token
