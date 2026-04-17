# Runbook: LLM Model Swap Without Downtime

> **Audience**: Platform engineers swapping the underlying LLM powering
> the Translator agent. Examples: phi3 -> llama3, llama3 -> Claude,
> Claude -> on-prem Qwen.
>
> **Goal**: Ship a new model to production with zero downtime, measurable
> regression checks, and a fast rollback path. Target wall time: 2-4 hours
> for a same-provider swap, 1-2 days for a provider change (OpenAI <->
> Anthropic <-> Ollama).

## Why model swaps are risky

The Translator agent is the only place the LLM is called for SQL
generation. A swap can:

1. **Change SQL syntax preferences**: one model prefers `CASE WHEN`, another
   emits `IIF()` even on SQLite. Breaks gold evals.
2. **Change latency profile**: a larger model can tip p99 over the SLO.
3. **Change cost**: API providers have very different per-token rates.
4. **Regress on sensitive-column refusal**: a model may volunteer a
   column the policy engine then blocks, hurting user trust.

The procedure below catches all four.

## Model candidates and their tradeoffs

| Model | Provider | Latency (p50) | Cost per 1M tok | SQL quality | Use when |
|---|---|---|---|---|---|
| `phi3:3.8b` | Ollama (local) | 1.5-3s | Free | Medium | Airgap, sandboxes |
| `llama3:8b` | Ollama (local) | 2-4s | Free | High | Airgap with GPU |
| `llama3:70b` | Ollama (local) | 8-15s | Free | Very high | Regulated, GPU pool |
| `gpt-4o-mini` | OpenAI | 400-800ms | $0.60 / $2.40 | High | Cost-optimized cloud |
| `claude-sonnet-4` | Anthropic | 600-1200ms | $3.00 / $15.00 | Very high | Customer-facing, quality-first |
| `claude-haiku-4` | Anthropic | 300-700ms | $1.00 / $5.00 | High | Low-latency cloud |

## Overview of the swap workflow

```
1. Dual-run the old and new models in shadow mode against the gold eval
2. If new model is within 2 percentage points of old, proceed
3. Roll out to 10% of traffic (canary)
4. Observe for 30 minutes
5. Roll to 100%
6. Keep rollback available for 72 hours
```

Total clock time: 2-4 hours for a clean swap.

## Phase 1: Shadow eval (30 min)

Nexus-Hive ships a dual-run mode that calls both the incumbent and
candidate model for every gold eval case and compares outputs.

### Configure

```bash
export NEXUS_HIVE_LLM_PROVIDER_SHADOW=anthropic
export NEXUS_HIVE_LLM_MODEL_SHADOW=claude-sonnet-4
export ANTHROPIC_API_KEY=sk-ant-...
```

### Run the shadow eval

```bash
curl -X POST http://localhost:8000/api/evals/nl2sql-gold/shadow \
  -H "Authorization: Bearer $NEXUS_OPERATOR_TOKEN" | jq
```

Expected output:

```json
{
  "incumbent": {"model": "phi3:3.8b", "score": 0.82, "passed": 16, "failed": 4},
  "candidate": {"model": "claude-sonnet-4", "score": 0.91, "passed": 18, "failed": 2},
  "delta": 0.09,
  "disagreements": [
    {"case": "gold-015", "incumbent_verdict": "pass", "candidate_verdict": "fail"},
    {"case": "gold-031", "incumbent_verdict": "fail", "candidate_verdict": "pass"}
  ]
}
```

Rule: the candidate should not regress any `pass` case into `fail`. If it
does, fix the prompt before proceeding.

## Phase 2: Latency baseline (15 min)

```bash
cd benchmarks
k6 run --vus 25 --duration 120s load_test.js \
  -e BASE_URL=http://localhost:8000 \
  -e LLM_PROVIDER=anthropic \
  -e LLM_MODEL=claude-sonnet-4
```

Expected:

```
http_req_duration   p(50)=700ms  p(95)=1400ms  p(99)=1900ms
```

Compare to incumbent. If p99 is more than 25% worse, consider:

- Using a smaller variant (e.g., `claude-haiku-4` instead of `sonnet`).
- Enabling prompt caching.
- Reducing prompt template tokens (fewer example rows in schema hints).

## Phase 3: Cost estimate (10 min)

Nexus-Hive exposes token counters per model:

```bash
curl -s http://localhost:8000/api/meta | jq '.llm_token_budget'
```

Multiply by the candidate's rate. For 50k queries/day at 800 input +
200 output tokens per request:

- `phi3`: free
- `gpt-4o-mini`: 50,000 * (800 * 0.60 + 200 * 2.40) / 1e6 = $48/day
- `claude-sonnet-4`: 50,000 * (800 * 3 + 200 * 15) / 1e6 = $270/day

If the budget delta is unacceptable, get finance sign-off before Phase 4.

## Phase 4: Canary rollout (30 min)

Nexus-Hive uses a weighted provider router. Enable a 10% canary:

```bash
helm upgrade nexus-hive helm/nexus-hive -n analytics \
  -f helm/nexus-hive/values.yaml \
  -f helm/nexus-hive/values-prod.yaml \
  --set env.NEXUS_HIVE_LLM_PROVIDER=weighted \
  --set env.NEXUS_HIVE_LLM_WEIGHT_ollama_phi3=0.9 \
  --set env.NEXUS_HIVE_LLM_WEIGHT_anthropic_sonnet=0.1 \
  --reuse-values --atomic
```

### Observe

Watch these metrics for 30 minutes in Grafana:

| Metric | Pass criterion |
|---|---|
| `nexus_hive:error_rate:5m` | Stable vs baseline (+/- 2pp) |
| `nexus_hive:request_latency_p99:5m` | Stable or improved |
| `nexus_hive_llm_tokens_total{model="claude-sonnet-4"}` | Non-zero, growing |
| `nexus_hive_policy_verdict_total{verdict="deny"}` | No spike |

### If canary is healthy

Proceed to Phase 5.

### If canary is unhealthy

```bash
# Immediate cutover back to incumbent
helm upgrade nexus-hive helm/nexus-hive -n analytics \
  --set env.NEXUS_HIVE_LLM_PROVIDER=ollama \
  --reuse-values --atomic --timeout 2m
```

Takes effect within one rolling restart (~90 seconds).

## Phase 5: Full cutover (15 min)

```bash
helm upgrade nexus-hive helm/nexus-hive -n analytics \
  --set env.NEXUS_HIVE_LLM_PROVIDER=anthropic \
  --set env.NEXUS_HIVE_LLM_MODEL=claude-sonnet-4 \
  --reuse-values --atomic
```

Verify:

```bash
curl -s http://localhost:8000/api/meta | jq '.llm_provider, .llm_model'
# Expected: "anthropic", "claude-sonnet-4"
```

Run the gold eval one more time:

```bash
curl http://localhost:8000/api/evals/nl2sql-gold/run | jq '.summary'
```

Expected: score within 2pp of the shadow eval result.

## Phase 6: Observe for 24 hours

Keep the rollback window open for 24 hours. Track:

- Error-rate trend vs the prior 24h
- p99 latency trend
- Per-user complaint volume (check `#analytics-users` Slack)
- Token spend trajectory (for paid providers)

If any metric degrades beyond the SLO for 1 hour, roll back.

## Rollback

```bash
# Full rollback
helm upgrade nexus-hive helm/nexus-hive -n analytics \
  --set env.NEXUS_HIVE_LLM_PROVIDER=ollama \
  --set env.NEXUS_HIVE_LLM_MODEL=phi3 \
  --reuse-values --atomic --timeout 2m
```

Or via Helm history:

```bash
helm history nexus-hive -n analytics
helm rollback nexus-hive <prior-rev> -n analytics --wait
```

Post-rollback, write a brief incident note even if no alert fired, so the
model evaluation data is captured.

## Special cases

### Swapping from a cloud API to Ollama (offline)

The inverse of the common path:

1. Provision Ollama sidecar first via `values-airgap.yaml` overlay.
2. Pre-stage the model weights on an internal mirror (see
   `docs/runbooks/airgap-deploy.md`).
3. Shadow-eval with a tighter threshold: allow up to 5pp regression vs
   cloud (local models almost always regress a bit).
4. Expect p99 to rise by 2-5x. Adjust SLOs or resources.

### Swapping between Claude versions

Minor-version Claude swaps (sonnet-3.5 -> sonnet-4) typically show only
subtle differences. Skip the shadow eval only if you have recent
regression data on the same prompt set.

### Temporary swap for incident mitigation

If the Translator is misbehaving (e.g., emitting invalid SQL) because of
a model-provider outage, swap via env override without running the full
procedure - the heuristic fallback is still protecting you:

```bash
kubectl -n analytics set env deploy/nexus-hive \
  NEXUS_HIVE_LLM_PROVIDER=ollama NEXUS_HIVE_LLM_MODEL=phi3
kubectl -n analytics rollout status deploy/nexus-hive
```

Return to the intended model once the outage clears. Log in the incident
ticket.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Shadow eval shows 10pp+ regression | Prompt template tuned for old model | Update `graph/prompts/translator.md` and rerun shadow |
| Canary shows no traffic to new model | Weighted router not picking up env vars | Verify env in `kubectl exec ... env | grep LLM_WEIGHT` |
| Cost spike after cutover | Prompt template includes schema sample that exploded | Cap schema hint to 15 tables / 100 columns |
| Latency doubled after cutover | New provider has a TLS handshake cost for first call | Pin `keep_alive` in the Ollama or provider client |
| Gold eval score drops in prod but not in shadow | Production data has patterns not represented in gold | Add 5 more gold cases sampled from audit trail |

## Checklist

- [ ] Shadow eval shows score delta within +/-2pp
- [ ] No pass-to-fail regressions in shadow
- [ ] Latency baseline acceptable
- [ ] Cost estimate approved
- [ ] Canary 10% for 30 minutes without alerts
- [ ] Full cutover + gold eval re-run
- [ ] 24h observation window on calendar
- [ ] Rollback commands documented in the ticket

## See also

- `docs/adr/003-langgraph-over-ad-hoc-chains.md` for why the Translator is
  isolated as a single node (making this swap tractable).
- `circuit_breaker.py` for the LLM failure isolation that lets us experiment
  safely.
- `docs/runbooks/incident-response.md` for what to do if the swap alerts.
