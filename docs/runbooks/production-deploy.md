# Runbook: Production Deployment (1 hour)

> **Audience**: Platform engineers deploying Nexus-Hive to a production
> Kubernetes cluster for the first time.
>
> **Goal**: A healthy `nexus-hive` release in the `analytics` namespace,
> authenticating to Snowflake, serving traffic behind an ingress, with
> Prometheus scraping and alerts wired up. Target wall time: 60 minutes.

## Prerequisites (T-24h)

Do these the day before; they will block you if left to the morning of.

- [ ] Kubernetes cluster 1.26+ with `kubectl` context configured.
- [ ] `helm` 3.12+ and `kubectl` 1.26+ installed locally.
- [ ] `kube-prometheus-stack` (Prometheus Operator) installed. Verify with:
      `kubectl get crd servicemonitors.monitoring.coreos.com`.
- [ ] Ingress controller installed (`ingress-nginx` assumed).
- [ ] `cert-manager` installed with a cluster issuer named `letsencrypt-prod`.
- [ ] `external-secrets` operator installed with a `ClusterSecretStore`
      pointing at your Vault / Secrets Manager.
- [ ] Snowflake service user provisioned with the `NEXUS_HIVE_APP` role,
      read-only on the `ANALYTICS` database.
- [ ] Container image built and pushed:
      `docker build -t ghcr.io/kim3310/nexus-hive:0.2.0 . && docker push`.
- [ ] DNS A/CNAME record for `nexus-hive.prod.example.com` pointing at the
      ingress LB.

Validate readiness:

```bash
kubectl get nodes
kubectl get crd servicemonitors.monitoring.coreos.com \
  externalsecrets.external-secrets.io \
  prometheusrules.monitoring.coreos.com
kubectl -n ingress-nginx get svc ingress-nginx-controller
```

## Phase 1: Namespace + baseline policies (5 min)

Apply the namespace with Pod Security Standards, ResourceQuota, LimitRange,
and default-deny NetworkPolicy:

```bash
kubectl apply -f infra/k8s/production/namespace.yaml
kubectl apply -f infra/k8s/production/resourcequota.yaml
kubectl apply -f infra/k8s/production/limitrange.yaml
kubectl apply -f infra/k8s/production/networkpolicy-default-deny.yaml
kubectl apply -f infra/k8s/production/networkpolicy-allow-ingress.yaml
kubectl apply -f infra/k8s/production/networkpolicy-allow-warehouse-egress.yaml
```

Expected output (per apply):

```
namespace/analytics created
resourcequota/nexus-hive-quota created
limitrange/nexus-hive-limits created
networkpolicy.networking.k8s.io/default-deny-all created
networkpolicy.networking.k8s.io/allow-dns-egress created
networkpolicy.networking.k8s.io/nexus-hive-allow-ingress created
networkpolicy.networking.k8s.io/nexus-hive-allow-warehouse-egress created
```

Verify the quota is in force:

```bash
kubectl -n analytics describe resourcequota nexus-hive-quota
```

You should see `Used 0/16` for `requests.cpu`, etc.

## Phase 2: Seed secrets via ExternalSecrets (10 min)

Store the Snowflake credentials in Vault (or equivalent) at
`kv/data/nexus-hive/snowflake` with keys `user` and `password`, and at
`kv/data/nexus-hive/databricks` with key `token`.

Then apply the chart with external secrets enabled; or seed them directly
for a smoke test:

```bash
kubectl -n analytics create secret generic nexus-hive-snowflake \
  --from-literal=SNOWFLAKE_PASSWORD='REPLACE' \
  --from-literal=SNOWFLAKE_USER='NEXUS_HIVE_APP'
```

Verify:

```bash
kubectl -n analytics get secret nexus-hive-snowflake -o yaml | \
  grep -E 'SNOWFLAKE_(USER|PASSWORD)'
```

You should see two base64-encoded values.

## Phase 3: Helm install (10 min)

Use the production overlay:

```bash
helm upgrade --install nexus-hive helm/nexus-hive \
  -n analytics \
  -f helm/nexus-hive/values.yaml \
  -f helm/nexus-hive/values-prod.yaml \
  --set image.tag=0.2.0 \
  --set env.SNOWFLAKE_ACCOUNT=abc123.us-east-1 \
  --set env.SNOWFLAKE_USER=NEXUS_HIVE_APP \
  --set env.SNOWFLAKE_DATABASE=ANALYTICS \
  --set env.SNOWFLAKE_WAREHOUSE=AI_WH \
  --set env.SNOWFLAKE_ROLE=NEXUS_HIVE_APP \
  --atomic \
  --timeout 5m
```

Expected output (truncated):

```
Release "nexus-hive" does not exist. Installing it now.
NAME: nexus-hive
LAST DEPLOYED: Mon Apr 13 15:42:11 2026
NAMESPACE: analytics
STATUS: deployed
REVISION: 1
```

Watch the rollout:

```bash
kubectl -n analytics rollout status deploy/nexus-hive --timeout=5m
```

Target: all 4 pods `Ready 1/1`.

## Phase 4: Smoke tests (10 min)

### Health check

```bash
kubectl -n analytics port-forward svc/nexus-hive 8000:80 &
curl -sf http://localhost:8000/health | jq
```

Expected:

```json
{"status": "ok", "version": "0.2.0", "warehouse": "snowflake-live"}
```

### Meta

```bash
curl -s http://localhost:8000/api/meta | jq .warehouse
```

Expected: `"snowflake-live"`.

### Ask a question

```bash
curl -sX POST http://localhost:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "Show total net revenue by region"}' | jq
```

Expected: a `request_id`, `sql`, and `stream_url`.

### Policy check

```bash
curl -sX POST http://localhost:8000/api/policy/check \
  -H 'Content-Type: application/json' \
  -d '{"sql": "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY 1", "role": "analyst"}' | jq
```

Expected: `verdict: "allow"`.

### Gold eval

```bash
curl -s http://localhost:8000/api/evals/nl2sql-gold/run | jq '.summary'
```

Expected: `passed >= 18` out of 20.

Stop the port-forward (`kill %1`).

## Phase 5: Ingress + TLS (10 min)

Confirm the Ingress was created:

```bash
kubectl -n analytics get ingress nexus-hive -o wide
```

Expected: an `ADDRESS` column populated with the LB IP.

Wait for cert-manager to issue a certificate:

```bash
kubectl -n analytics get certificate nexus-hive-tls-prod -w
```

Expected: `READY True` within 60-120 seconds. If it hangs, check the
`Order` and `Challenge` resources for DNS or HTTP-01 issues.

Smoke test the public URL:

```bash
curl -sf https://nexus-hive.prod.example.com/health | jq
```

## Phase 6: Observability wiring (10 min)

Apply observability manifests:

```bash
kubectl apply -f infra/k8s/observability/servicemonitor.yaml
kubectl apply -f infra/k8s/observability/prometheus-rules.yaml
```

Verify Prometheus discovery:

```bash
kubectl -n observability port-forward svc/prometheus-operated 9090:9090 &
# Open http://localhost:9090/targets and look for nexus-hive.
# You should see 4 targets in state UP.
```

Verify rules loaded:

```bash
kubectl -n analytics get prometheusrule nexus-hive-slo -o jsonpath='{.spec.groups[*].name}'
```

Expected: `nexus-hive.recording nexus-hive.slo`.

Kill the port-forward.

## Phase 7: HPA + PDB sanity (5 min)

```bash
kubectl -n analytics get hpa nexus-hive
kubectl -n analytics get pdb nexus-hive
```

Expected HPA:

```
NAME         REFERENCE               TARGETS     MINPODS   MAXPODS   REPLICAS
nexus-hive   Deployment/nexus-hive   12%/65%     4         20        4
```

Expected PDB:

```
NAME         MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
nexus-hive   2               N/A               2
```

## Phase 8: Load smoke test (5 min)

```bash
cd benchmarks
k6 run --vus 25 --duration 60s load_test.js \
  -e BASE_URL=https://nexus-hive.prod.example.com
```

Expected:

- `http_req_failed` < 1%
- `http_req_duration p(99)` < 2000ms
- `checks` pass rate >= 99%

## Phase 9: Handoff (5 min)

Tag the release:

```bash
helm history nexus-hive -n analytics
# Capture revision 1 for the rollback note.
```

Open in the internal wiki a page titled "Nexus-Hive Production - Prod Release 0.2.0":

- Link to the helm chart values used
- Paste the `kubectl get pods,svc,ing,hpa,pdb -n analytics` output
- Link to the Prometheus dashboard
- Link to `docs/runbooks/incident-response.md`

Notify `#analytics-platform` with a two-line summary.

## Rollback procedure

```bash
helm history nexus-hive -n analytics
helm rollback nexus-hive <previous-revision> -n analytics --wait
```

Expected: rollout within 2 minutes.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Pods `CrashLoopBackOff`, logs show `SNOWFLAKE_ACCOUNT not set` | Secret didn't project into env | `kubectl -n analytics describe pod <name>` and verify envFrom refs |
| Pods Pending | Exceeded ResourceQuota | `kubectl -n analytics describe resourcequota` and raise limits or reduce replicas |
| NetworkPolicy blocks Snowflake | Egress rule missing your Snowflake CIDR | Add your region's egress CIDR to `networkpolicy-allow-warehouse-egress.yaml` |
| ServiceMonitor not scraped | Missing `release` label on SM | Set `serviceMonitor.additionalLabels.release=kube-prometheus-stack` |
| Cert stuck `Pending` | DNS not pointing at LB | Verify `dig nexus-hive.prod.example.com` matches LB IP |

## Verification checklist

- [ ] `kubectl -n analytics get pods` shows 4 `Running 1/1`
- [ ] `curl -sf https://nexus-hive.prod.example.com/health` returns 200
- [ ] `http://prometheus:9090/targets` shows 4 UP targets
- [ ] `http://prometheus:9090/rules` shows the `nexus-hive.slo` group
- [ ] `k6` smoke test passes
- [ ] HPA, PDB, NetworkPolicies all present

Total wall time for a practiced operator: ~55 minutes. First-time runs
land closer to 90 minutes due to certificate issuance and firewall tweaks.
