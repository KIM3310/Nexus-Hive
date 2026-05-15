# Runbook: Incident Response

> **Audience**: On-call platform engineers responding to Nexus-Hive alerts.
>
> **Goal**: Bring the service back into SLO within the applicable MTTR
> window, or escalate with a clean handoff.

## Severity levels

| SEV | Definition | Example | MTTR target | Page? |
|---|---|---|---|---|
| SEV-1 | Total outage or data integrity issue | All /api/ask returning 5xx; audit trail not writing | 30 min | Yes |
| SEV-2 | Partial outage or severe degradation | One AZ down; p99 > 5s; one warehouse adapter broken | 60 min | Yes |
| SEV-3 | Minor degradation or known workaround available | Circuit breaker open but heuristic fallback working | 4 hr | No |
| SEV-4 | Cosmetic or non-urgent | Typo in UI; logs noisy but correct | Next business day | No |

## First 10 minutes (triage)

When a page fires:

1. **Acknowledge** the PagerDuty / Opsgenie incident within 2 minutes.
2. **Check #analytics-platform** Slack for related deploys or outages.
3. **Run the triage one-liner**:

   ```bash
   kubectl -n analytics get pods,svc,ing,hpa,pdb
   kubectl -n analytics top pod
   kubectl -n analytics logs deploy/nexus-hive --tail=200 | tail -50
   ```

4. **Look at Grafana dashboard** `Nexus-Hive / SLO` for the last 30 minutes.
5. **Classify SEV** using the table above. If unsure, default to the higher
   severity - it is cheaper to be wrong up than wrong down.

## Alert-to-action map

### `NexusHiveHighErrorRate` (page)

Symptom: 5xx ratio > 5% for 10 minutes.

```bash
kubectl -n analytics logs deploy/nexus-hive --tail=500 | \
  grep -i 'ERROR\|Exception\|Traceback' | head -20
```

**Decision tree**

| Log signature | Action |
|---|---|
| `snowflake.connector.errors.OperationalError` | Snowflake down or creds rotated. Check `status.snowflake.com`. Rotate key if needed. |
| `httpx.ConnectError: [Errno 111] Connection refused` on Ollama URL | Ollama sidecar crashed. `kubectl delete pod -l app.kubernetes.io/component=ollama`. |
| `PolicyDenied` dominating logs | Unusual query pattern. Check whether `POLICY_PROFILE` was toggled to `strict` without coordination. |
| `OOMKilled` in `kubectl describe pod` | Raise `resources.limits.memory` to 2Gi and redeploy. |
| `Pending DNS` | CoreDNS degraded. Check `kube-system` namespace. |

If nothing matches, pull traces:

```bash
curl -s "http://prometheus:9090/api/v1/query?query=nexus_hive:error_rate:5m" | jq
```

### `NexusHiveHighLatency` (ticket)

Symptom: p99 > 2s for 15 minutes.

```bash
# Check HPA - are we throttled?
kubectl -n analytics get hpa nexus-hive

# Check pod CPU/memory pressure
kubectl -n analytics top pod

# Long-running queries?
kubectl -n analytics logs deploy/nexus-hive --tail=500 | \
  grep 'execution_time_ms' | \
  awk '{print $NF}' | sort -n | tail -20
```

Common causes:

- **Warehouse slow query**: scan the audit trail for query signature.
- **LLM cold start**: check Ollama sidecar container uptime. If > 95% of
  latency is in `agent.translator`, the LLM is the bottleneck.
- **HPA at max**: scale `maxReplicas` via Helm and re-upgrade.
- **Noisy neighbor**: check node-level CPU via Grafana.

### `NexusHiveCircuitBreakerOpen` (ticket)

Symptom: LLM circuit breaker open for 5+ minutes.

```bash
curl -s http://localhost:8000/api/meta | jq '.circuit_breaker'
```

Expected when healthy:

```json
{"state": "CLOSED", "failures": 0, "last_error": null}
```

If `OPEN`:

```bash
# Restart the Ollama sidecar
kubectl -n analytics exec deploy/nexus-hive -c ollama -- \
  ollama list

# If Ollama is healthy, restart the API pod to reset the breaker
kubectl -n analytics rollout restart deploy/nexus-hive
```

Users will continue to receive heuristic SQL while the breaker is open -
service is degraded but not down.

### `NexusHiveAuditWriteStalled` (page)

Symptom: audit trail not written for 5+ minutes while traffic flows.

This is a **governance-critical** alert. Do not silence it.

```bash
kubectl -n analytics exec deploy/nexus-hive -- \
  ls -la /var/log/nexus-hive/audit.jsonl
```

| Observation | Fix |
|---|---|
| File growing but alert firing | `nexus_hive_audit_last_write_timestamp_seconds` metric not being updated. Check for uncaught exception in `policy/audit.py`. Redeploy. |
| File absent or zero bytes | Volume mount failed. `kubectl describe pod` to see volume errors. |
| `Disk full` in container | PVC full. Expand via `kubectl patch pvc ... --patch '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'`. |
| Policy profile misconfiguration | `NEXUS_HIVE_AUDIT_PATH` pointing at read-only path. Fix ConfigMap. |

### `NexusHiveSqlExecutionErrors` (ticket)

Symptom: >10% of SQL executions fail for 10 minutes.

```bash
kubectl -n analytics logs deploy/nexus-hive --tail=500 | \
  grep 'sql_execution_error' | head -30
```

Investigate whether:

- A recent schema change broke existing queries (see
  `docs/runbooks/schema-evolution.md`).
- The warehouse role lost a permission.
- A new policy rule is being misapplied.

### `NexusHivePodRestartsHigh` (ticket)

Symptom: Pod restarting > 0.1/s for 15 minutes.

```bash
kubectl -n analytics describe pod $(kubectl -n analytics get pod -l app.kubernetes.io/name=nexus-hive -o jsonpath='{.items[0].metadata.name}')
```

Look for `Last State: Terminated Reason: OOMKilled` or
`Reason: Error Exit Code: 1`. Most common remedy: raise memory limits and
redeploy.

## Emergency runbook: full rollback

If the incident is tied to a recent deploy:

```bash
# See recent revisions
helm -n analytics history nexus-hive

# Roll back to the last known good
helm -n analytics rollback nexus-hive <rev> --wait --timeout 5m

# Verify
kubectl -n analytics rollout status deploy/nexus-hive --timeout=120s
curl -sf https://nexus-hive.prod.example.com/health | jq
```

Post-rollback: write a brief (3-5 line) incident message in
`#analytics-platform`, open a postmortem ticket, and schedule a blameless
postmortem within 48 hours.

## Escalation path

| Tier | Who | When |
|---|---|---|
| Tier 1 | On-call platform engineer | Every page |
| Tier 2 | Platform owner | SEV-1 beyond 30 min, SEV-2 beyond 60 min |
| Tier 3 | Data governance officer | Any audit-trail alert, any policy-engine mismatch on regulated data |
| Tier 4 | AegisOps (our ops-copilot companion repo) | Cross-service incidents or multiple simultaneous SEV-2 alerts |

### AegisOps handoff

When escalating to AegisOps, use the structured payload it expects:

```bash
aegis-cli incident open \
  --service nexus-hive \
  --severity 1 \
  --runbook docs/runbooks/incident-response.md \
  --context "5xx rate spiked to 18% following deploy rev 7 at 14:22Z" \
  --last-known-good rev-6
```

AegisOps will ingest the audit trail, correlate with recent deploys, and
propose a rollback or mitigation. The operator retains final authority.

## Post-incident: 24-hour checklist

- [ ] Incident channel closed with summary + MTTR
- [ ] Postmortem document started
- [ ] Customer comms drafted if customer-facing impact > 15 min
- [ ] Action items filed as tickets with owners
- [ ] Runbook updated with any new signature/fix discovered
- [ ] Alert thresholds revisited if the incident exposed a gap
- [ ] Monitoring / recording rules patched if data was missing

## SLO budget & error budget

Nexus-Hive is a **tier-1 service** with:

- **Availability SLO**: 99.5% over a rolling 28-day window
- **Latency SLO**: 95% of requests < 1500ms; 99% < 2000ms
- **Correctness SLO**: SQL execution success rate > 99% over rolling 7 days

Error budget remaining is surfaced via the `nexus_hive:error_budget:slo`
recording rule. If < 25% budget remains:

- Freeze all non-critical deploys.
- Prioritize reliability work over feature work for one sprint.
- Open a tracking ticket and report to engineering leadership weekly.
