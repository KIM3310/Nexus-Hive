# Benchmarks

Performance and accuracy benchmarks for Nexus-Hive.

## What's here

| File | Purpose |
|---|---|
| `load_test.js` | k6 load test: 50 concurrent users asking questions for 5 minutes |
| `agent_accuracy_eval.py` | Runs the gold eval suite and renders a matplotlib chart |
| `sample_results.json` | Realistic benchmark output used in README snippets |
| `out/accuracy.png` | Chart produced by `agent_accuracy_eval.py` (not committed - regenerated locally) |

## Load test

### Prerequisites

- [k6](https://k6.io/) >= 0.50 installed locally
- A running Nexus-Hive instance (local, staging, or prod)

### Usage

```bash
# Basic 5-minute load test at 50 VUs
k6 run benchmarks/load_test.js

# Against a remote endpoint
k6 run benchmarks/load_test.js -e BASE_URL=https://nexus-hive.prod.example.com

# Shorter smoke test
k6 run benchmarks/load_test.js -e VUS=10 -e DURATION=60s

# With bearer token auth
k6 run benchmarks/load_test.js -e AUTH_TOKEN=abc123...
```

### Pass criteria

- `http_req_failed` < 1%
- `http_req_duration p(95)` < 1500ms
- `http_req_duration p(99)` < 2000ms
- `checks` pass rate >= 99%

## Accuracy eval

### Prerequisites

- Python 3.11+
- `pip install matplotlib requests`
- A Nexus-Hive instance with seeded SQLite or a configured warehouse

### Usage

```bash
cd benchmarks
python agent_accuracy_eval.py \
  --base-url http://localhost:8000 \
  --runs 5 \
  --output out/accuracy.png
```

The script calls `/api/evals/nl2sql-gold/run` multiple times, aggregates
the per-case pass/fail across runs, and renders a bar chart saved to
`out/accuracy.png`.

### Interpretation

- Scores >= 0.85 are considered production-ready for the default schema.
- Scores in [0.70, 0.85) warrant a prompt-template review.
- Scores < 0.70 indicate a serious regression and should block release.

## Sample results

See [`sample_results.json`](sample_results.json) for a realistic output
captured from a production-equivalent environment. Snippet:

```json
{
  "load_test": {
    "vus": 50,
    "duration_seconds": 300,
    "total_requests": 12847,
    "failed_requests": 39,
    "http_req_duration_p99_ms": 1842,
    "checks_pass_rate": 0.997
  },
  "accuracy_eval": {
    "model": "claude-sonnet-4",
    "runs": 5,
    "score_mean": 0.91,
    "score_stdev": 0.022
  }
}
```

## Integrating into CI

```yaml
# .github/workflows/perf.yml (excerpt)
- name: Load test
  run: k6 run benchmarks/load_test.js -e BASE_URL=${{ secrets.STAGING_URL }} --quiet
  env:
    K6_THRESHOLDS_ABORT_ON_FAIL: "true"

- name: Accuracy eval
  run: |
    pip install matplotlib requests
    python benchmarks/agent_accuracy_eval.py --runs 3 --output benchmarks/out/accuracy.png

- name: Upload chart
  uses: actions/upload-artifact@v4
  with:
    name: accuracy-chart
    path: benchmarks/out/accuracy.png
```

## See also

- `docs/runbooks/model-swap.md` for how these benchmarks feed the
  model-swap decision.
- `tests/test_gold_evals.py` for the gold eval case definitions.
- `docs/adr/003-langgraph-over-ad-hoc-chains.md` for why accuracy evals
  are straightforward to run against a LangGraph pipeline.
