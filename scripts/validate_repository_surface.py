#!/usr/bin/env python3
"""Validate the repository review surface.

The check is intentionally dependency-free so active and archived repositories can
run the same guard in CI. It verifies public-facing docs, local links, architecture
blueprint hooks, and neutral technical positioning.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ARCH_DOC = ROOT / "docs" / "cloud-ai-architecture.md"
ARCH_MANIFEST = ROOT / "docs" / "architecture" / "blueprint.json"
ARCH_VALIDATOR = ROOT / "scripts" / "validate_architecture_blueprint.py"
ARCH_WORKFLOW = ROOT / ".github" / "workflows" / "architecture-blueprint.yml"

REQUIRED_FILES = (
    README,
    ROOT / ".editorconfig",
    ROOT / "CONTRIBUTING.md",
    ARCH_DOC,
    ARCH_MANIFEST,
    ARCH_VALIDATOR,
    ARCH_WORKFLOW,
)

BANNED_TERMS = {
    "hir" + "ing",
    "recr" + "uiter",
    "job" + " seeker",
    "job" + "-seeker",
    "inter" + "view prep",
    "career" + " signal",
    "best" + " fit roles",
    "role" + "-fit",
    "role" + "_fit",
    "cover" + " letter",
    "job" + " description",
    "required" + " qualifications",
    "preferred" + " qualifications",
    "채" + "용",
    "취" + "업",
    "구" + "직",
    "입" + "사",
}

LOCAL_PATH_MARKERS = (
    "/Users/",
    "/home/",
    "C:/Users/",
    "C:\\Users\\",
    "file://",
    "vscode://",
)

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def fail(message: str) -> NoReturn:
    print(f"repository surface validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def require_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        fail(f"missing required file: {path.relative_to(ROOT)}")


def markdown_files() -> list[Path]:
    files = sorted(ROOT.glob("*.md"))
    docs = ROOT / "docs"
    if docs.exists():
        files.extend(sorted(docs.rglob("*.md")))
    return files


TEXT_SUFFIXES = {
    ".css",
    ".go",
    ".js",
    ".json",
    ".html",
    ".jsonl",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".yml",
    ".yaml",
}

SKIP_FILENAMES = {
    "Cargo.lock",
    "Pipfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}

SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}


def is_skipped(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return path.name in SKIP_FILENAMES or any(
        part in SKIP_PARTS for part in relative.parts
    )


def code_and_generated_files() -> list[Path]:
    return [
        path
        for path in sorted(ROOT.rglob("*"))
        if path.is_file() and path.suffix in TEXT_SUFFIXES and not is_skipped(path)
    ]


def is_external_or_route(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith(("http://", "https://", "mailto:", "tel:"))
        or target.startswith("#")
        or (
            target.startswith("/")
            and not any(target.startswith(marker) for marker in LOCAL_PATH_MARKERS)
        )
    )


def check_local_link(source: Path, target: str, line: int) -> None:
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    for marker in LOCAL_PATH_MARKERS:
        if marker in target:
            fail(f"local machine path in {source.relative_to(ROOT)}:{line}: {target}")
    if is_external_or_route(target):
        return
    path_part = target.split("#", 1)[0]
    if not path_part:
        return
    candidate = (source.parent / path_part).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        fail(f"link escapes repository in {source.relative_to(ROOT)}:{line}: {target}")
    if not candidate.exists():
        fail(f"broken local link in {source.relative_to(ROOT)}:{line}: {target}")


def check_markdown_links() -> None:
    for path in markdown_files():
        text = read_text(path)
        for match in MARKDOWN_LINK_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            check_local_link(path, match.group(1).strip(), line)


def scan_positioning_terms() -> None:
    paths = markdown_files() + code_and_generated_files()
    for path in paths:
        text = read_text(path).lower()
        for term in BANNED_TERMS:
            if term.lower() in text:
                fail(f"non-neutral positioning term in {path.relative_to(ROOT)}")


def load_manifest() -> dict[str, Any]:
    try:
        loaded = json.loads(ARCH_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid architecture manifest JSON: {exc}")
    if not isinstance(loaded, dict):
        fail("architecture manifest root must be an object")
    return cast(dict[str, Any], loaded)


def check_architecture_surface() -> None:
    manifest = load_manifest()
    required = {
        "schema_version",
        "repository",
        "neutrality",
        "focus",
        "cloud_architecture",
        "ai_engineering",
        "validation",
        "research_grounding",
    }
    missing = required - set(manifest)
    if missing:
        fail(f"architecture manifest missing keys: {', '.join(sorted(missing))}")

    readme = read_text(README)
    for expected in (
        "docs/cloud-ai-architecture.md",
        "docs/architecture/blueprint.json",
        "scripts/validate_architecture_blueprint.py",
    ):
        if expected not in readme:
            fail(f"README missing architecture reference: {expected}")


def main() -> None:
    for path in REQUIRED_FILES:
        require_file(path)
    if not read_text(README).strip():
        fail("README.md is empty")
    check_architecture_surface()
    check_markdown_links()
    scan_positioning_terms()
    print("repository surface validation ok")


if __name__ == "__main__":
    main()
