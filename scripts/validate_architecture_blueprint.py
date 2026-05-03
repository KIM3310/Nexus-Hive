#!/usr/bin/env python3
"""Validate the repository cloud/AI architecture blueprint.

The check is intentionally dependency-free so archived and active repositories can
run the same guard in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "architecture" / "blueprint.json"
DOC = ROOT / "docs" / "cloud-ai-architecture.md"

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "repository",
    "status",
    "neutrality",
    "focus",
    "cloud_architecture",
    "ai_engineering",
    "validation",
    "research_grounding",
}

BANNED_TERMS = {
    "hiring",
    "recruiter",
    "job seeker",
    "job-seeker",
    "interview prep",
    "career signal",
    "채용",
    "취업",
    "구직",
    "입사",
}


def fail(message: str) -> NoReturn:
    print(f"architecture blueprint validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        fail(f"missing {MANIFEST.relative_to(ROOT)}")
    try:
        loaded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc}")
    if not isinstance(loaded, dict):
        fail("manifest root must be an object")
    return cast(dict[str, Any], loaded)


def require_non_empty_list(data: dict[str, Any], key: str, minimum: int = 1) -> None:
    value = data.get(key)
    if not isinstance(value, list) or len(value) < minimum:
        fail(f"{key} must contain at least {minimum} item(s)")


def scan_forbidden(text: str, source: str) -> None:
    lowered = text.lower()
    for term in BANNED_TERMS:
        if term.lower() in lowered:
            fail(f"forbidden positioning term {term!r} found in {source}")


def object_section(data: dict[str, Any], section: str) -> dict[str, Any]:
    value = data.get(section)
    if not isinstance(value, dict):
        fail(f"{section} must be an object")
    return cast(dict[str, Any], value)


def main() -> None:
    data = load_manifest()
    missing = REQUIRED_TOP_LEVEL - set(data)
    if missing:
        fail(f"missing top-level keys: {', '.join(sorted(missing))}")

    if data.get("schema_version") != "1.0":
        fail("schema_version must be 1.0")

    focus = object_section(data, "focus")
    cloud_architecture = object_section(data, "cloud_architecture")
    ai_engineering = object_section(data, "ai_engineering")
    object_section(data, "validation")
    object_section(data, "neutrality")

    require_non_empty_list(focus, "primary_stack")
    require_non_empty_list(focus, "architecture_axes", minimum=3)
    require_non_empty_list(cloud_architecture, "patterns", minimum=1)
    require_non_empty_list(cloud_architecture, "landing_zone_controls", minimum=4)
    require_non_empty_list(cloud_architecture, "resilience_controls", minimum=3)
    require_non_empty_list(ai_engineering, "patterns", minimum=4)
    require_non_empty_list(ai_engineering, "evaluation_controls", minimum=3)
    require_non_empty_list(ai_engineering, "model_risk_controls", minimum=3)
    require_non_empty_list(data, "research_grounding", minimum=3)

    research_grounding = data["research_grounding"]
    if not isinstance(research_grounding, list):
        fail("research_grounding must be a list")
    for ref in research_grounding:
        if not isinstance(ref, dict) or not ref.get("title") or not ref.get("url"):
            fail("each research_grounding entry must contain title and url")

    if not DOC.exists():
        fail(f"missing {DOC.relative_to(ROOT)}")

    manifest_text = json.dumps(data, ensure_ascii=False)
    doc_text = DOC.read_text(encoding="utf-8")
    scan_forbidden(manifest_text, str(MANIFEST.relative_to(ROOT)))
    scan_forbidden(doc_text, str(DOC.relative_to(ROOT)))

    required_doc_phrases = [
        "Cloud Architecture",
        "AI Engineering",
        "Operating Model",
        "Validation",
        "Research Grounding",
    ]
    for phrase in required_doc_phrases:
        if phrase not in doc_text:
            fail(f"document missing section phrase: {phrase}")

    print("architecture blueprint validation ok")


if __name__ == "__main__":
    main()
