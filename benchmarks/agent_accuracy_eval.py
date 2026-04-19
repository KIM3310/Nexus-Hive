"""Agent accuracy eval runner.

Calls the Nexus-Hive gold eval endpoint N times, aggregates per-case
pass/fail results, and renders a bar chart of per-case accuracy plus
a summary score.

Usage:

    python benchmarks/agent_accuracy_eval.py \\
        --base-url http://localhost:8000 \\
        --runs 5 \\
        --output benchmarks/out/accuracy.png

Dependencies:
    pip install matplotlib requests
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import matplotlib.pyplot as plt  # noqa: E402
    import requests  # noqa: E402
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        f"Missing dependency: {exc.name}. Install with `pip install matplotlib requests`.\n"
    )
    raise SystemExit(1) from exc


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_RUNS = 5
DEFAULT_OUTPUT = "benchmarks/out/accuracy.png"
DEFAULT_ENDPOINT = "/api/evals/nl2sql-gold/run"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Nexus-Hive accuracy eval")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEXUS_HIVE_BASE_URL", DEFAULT_BASE_URL),
        help=f"Base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Number of eval runs to average (default: {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output PNG path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Eval endpoint path (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("NEXUS_OPERATOR_TOKEN"),
        help="Bearer token (or set NEXUS_OPERATOR_TOKEN)",
    )
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="Skip chart generation (still writes JSON summary)",
    )
    return parser.parse_args()


def call_eval(base_url: str, endpoint: str, timeout: int, auth_token: str | None) -> dict[str, Any]:
    """Call the eval endpoint and return parsed JSON."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-case pass rate and overall summary across runs."""
    case_passes: dict[str, int] = defaultdict(int)
    case_total: dict[str, int] = defaultdict(int)
    case_labels: dict[str, str] = {}
    run_scores: list[float] = []

    for run in runs:
        summary = run.get("summary", {})
        score = summary.get("score")
        if score is not None:
            run_scores.append(float(score))

        for case in run.get("cases", []):
            case_id = case.get("id") or case.get("case_id") or "unknown"
            case_total[case_id] += 1
            label = case.get("label") or case.get("question") or case_id
            case_labels[case_id] = label[:60]  # truncate long labels
            if case.get("passed") or case.get("verdict") == "pass":
                case_passes[case_id] += 1

    per_case_accuracy = {
        case_id: (case_passes[case_id] / case_total[case_id]) for case_id in case_total
    }

    return {
        "runs_executed": len(runs),
        "score_mean": statistics.mean(run_scores) if run_scores else None,
        "score_stdev": (statistics.stdev(run_scores) if len(run_scores) > 1 else 0.0),
        "score_min": min(run_scores) if run_scores else None,
        "score_max": max(run_scores) if run_scores else None,
        "per_case": per_case_accuracy,
        "per_case_labels": case_labels,
        "total_cases": len(per_case_accuracy),
    }


def render_chart(aggregated: dict[str, Any], output_path: str) -> None:
    """Render per-case accuracy as a horizontal bar chart."""
    per_case = aggregated["per_case"]
    labels_map = aggregated["per_case_labels"]

    # Sort by accuracy ascending so the weakest cases show up on top.
    items = sorted(per_case.items(), key=lambda kv: kv[1])
    ids = [item[0] for item in items]
    values = [item[1] for item in items]
    labels = [f"{i} - {labels_map.get(i, i)[:40]}" for i in ids]

    fig_height = max(4, 0.3 * len(ids))
    fig, ax = plt.subplots(figsize=(10, fig_height))

    colors = ["#d73027" if v < 0.6 else "#fdae61" if v < 0.85 else "#1a9850" for v in values]
    ax.barh(range(len(values)), values, color=colors)
    ax.set_yticks(range(len(values)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Pass rate across runs")
    ax.set_title(
        f"Nexus-Hive gold eval per-case accuracy "
        f"(runs={aggregated['runs_executed']}, "
        f"mean score={aggregated['score_mean']:.3f}, "
        f"stdev={aggregated['score_stdev']:.3f})",
        fontsize=11,
    )
    ax.axvline(0.85, color="gray", linestyle="--", linewidth=0.7)
    ax.grid(axis="x", linestyle=":", alpha=0.5)

    for idx, value in enumerate(values):
        ax.text(value + 0.01, idx, f"{value:.2f}", va="center", fontsize=7)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close(fig)


def main() -> int:
    """CLI entry point."""
    args = parse_args()

    runs: list[dict[str, Any]] = []
    for i in range(args.runs):
        sys.stdout.write(f"[{i + 1}/{args.runs}] Calling eval... ")
        sys.stdout.flush()
        try:
            data = call_eval(
                args.base_url,
                args.endpoint,
                args.timeout,
                args.auth_token,
            )
        except requests.RequestException as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 2

        summary = data.get("summary", {})
        sys.stdout.write(
            f"score={summary.get('score', 'n/a')} "
            f"passed={summary.get('passed', 'n/a')}/"
            f"{summary.get('total', 'n/a')}\n"
        )
        runs.append(data)

    aggregated = aggregate_runs(runs)

    print()
    print("-" * 60)
    print(f"Runs:       {aggregated['runs_executed']}")
    print(f"Score mean: {aggregated['score_mean']:.3f}")
    print(f"Score min:  {aggregated['score_min']:.3f}")
    print(f"Score max:  {aggregated['score_max']:.3f}")
    print(f"Score sd:   {aggregated['score_stdev']:.3f}")
    print(f"Total cases: {aggregated['total_cases']}")
    print("-" * 60)

    json_path = Path(args.output).with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {k: v for k, v in aggregated.items() if k != "per_case_labels"},
            handle,
            indent=2,
            default=str,
        )
    print(f"Wrote JSON summary to {json_path}")

    if not args.no_chart:
        render_chart(aggregated, args.output)
        print(f"Wrote chart to {args.output}")

    # Return non-zero if mean score < 0.70 so CI can gate on it.
    score = aggregated["score_mean"] or 0.0
    return 0 if score >= 0.70 else 3


if __name__ == "__main__":
    sys.exit(main())
