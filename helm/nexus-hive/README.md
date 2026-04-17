# Nexus-Hive Helm Chart

Enterprise Helm chart for the Nexus-Hive multi-agent NL-to-SQL copilot.

- Chart version: `0.2.0`
- App version: `0.2.0`
- Kubernetes: `>= 1.26`
- Helm: `>= 3.12`

## TL;DR

```bash
helm upgrade --install nexus-hive helm/nexus-hive \
  --namespace analytics --create-namespace
```

For production:

```bash
helm upgrade --install nexus-hive helm/nexus-hive \
  -n analytics --create-namespace \
  -f helm/nexus-hive/values.yaml \
  -f helm/nexus-hive/values-prod.yaml \
  --set image.tag=0.2.0
```

For airgap:

```bash
helm upgrade --install nexus-hive helm/nexus-hive \
  -n analytics --create-namespace \
  -f helm/nexus-hive/values.yaml \
  -f helm/nexus-hive/values-airgap.yaml \
  --set image.repository=registry.internal.corp/nexus-hive/app
```

## What this chart installs

| Resource | Purpose |
|---|---|
| `Deployment` | Nexus-Hive FastAPI runtime (optionally with Ollama + OTEL sidecars) |
| `Service` | ClusterIP by default; switch to LoadBalancer via `service.type` |
| `Ingress` | Optional; enables nginx-ingress or GKE GCE ingress |
| `HorizontalPodAutoscaler` | CPU + memory autoscale, with configurable custom metrics |
| `PodDisruptionBudget` | Keeps `minAvailable` pods during voluntary disruptions |
| `NetworkPolicy` | Ingress allow-list + egress restriction to DNS/warehouse/Ollama |
| `ConfigMap` | Policy profile, retry budget, audit path (with checksum-triggered rollouts) |
| `ExternalSecret` | Pulls Snowflake / Databricks credentials from Vault/SecretsManager |
| `ServiceAccount` + `Role` + `RoleBinding` | Minimal RBAC scoped to the release |
| `ServiceMonitor` + `PrometheusRule` | kube-prometheus-stack scraping + SLO alerts |

## Values reference

See `values.yaml` for full documentation of every key. The most commonly
overridden sections:

### image

```yaml
image:
  repository: ghcr.io/kim3310/nexus-hive
  tag: "0.2.0"
  pullPolicy: IfNotPresent
```

### env

Environment variables injected into the runtime. Populate Snowflake and
Databricks variables here or, better, via `envFromSecrets` or `externalSecrets`:

```yaml
env:
  SNOWFLAKE_ACCOUNT: "abc123.us-east-1"
  SNOWFLAKE_USER: "NEXUS_HIVE_RW"
  SNOWFLAKE_DATABASE: "ANALYTICS"
  SNOWFLAKE_WAREHOUSE: "AI_WH"
  SNOWFLAKE_ROLE: "NEXUS_HIVE_APP"

envFromSecrets:
  - name: SNOWFLAKE_PASSWORD
    secretName: nexus-hive-snowflake
    key: password
```

### autoscaling

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

### networkPolicy

```yaml
networkPolicy:
  enabled: true
  ingressFrom:
    - namespaceSelector:
        matchLabels:
          networking.nexus-hive.io/ingress: "true"
  egressTo:
    - ports:
        - port: 443
          protocol: TCP
```

### serviceMonitor / prometheusRule

Requires `prometheus-operator` (kube-prometheus-stack). Enable with:

```yaml
serviceMonitor:
  enabled: true
  additionalLabels:
    release: kube-prometheus-stack

prometheusRule:
  enabled: true
  additionalLabels:
    release: kube-prometheus-stack
```

The default ruleset covers:

- `NexusHiveHighErrorRate` - 5xx ratio > 5% for 10 minutes (page)
- `NexusHiveHighLatency` - p99 > 2s for 15 minutes (ticket)
- `NexusHiveCircuitBreakerOpen` - Ollama breaker open for 5+ minutes (ticket)

## Overlays

- `values.yaml` - sensible defaults for dev/staging
- `values-prod.yaml` - tighter resources, HPA, strict security context, HA spread
- `values-airgap.yaml` - disables external LLM, enables Ollama sidecar with persistent volume

## Upgrade path

Deployment strategy is `RollingUpdate` with `maxUnavailable: 0`. The ConfigMap
checksum annotation on the pod template ensures that a config change triggers
a safe rolling restart.

```bash
helm upgrade nexus-hive helm/nexus-hive \
  -n analytics \
  -f helm/nexus-hive/values-prod.yaml \
  --set image.tag=0.2.1

kubectl -n analytics rollout status deploy/nexus-hive --timeout=180s
```

## Uninstall

```bash
helm uninstall nexus-hive -n analytics
kubectl delete pvc -n analytics -l app.kubernetes.io/instance=nexus-hive
```

## Linting and template dry-run

```bash
helm lint helm/nexus-hive -f helm/nexus-hive/values.yaml
helm template nexus-hive helm/nexus-hive \
  -f helm/nexus-hive/values.yaml \
  -f helm/nexus-hive/values-prod.yaml | kubeconform -strict -summary -
```

## See also

- `docs/runbooks/production-deploy.md` - 1-hour production rollout
- `docs/runbooks/airgap-deploy.md` - airgap-specific workflow
- `docs/runbooks/incident-response.md` - on-call runbook
- `docs/adr/005-helm-chart-design.md` - why a chart over raw YAML
- `docs/adr/006-observability-stack.md` - OTel + Prometheus + Loki rationale
