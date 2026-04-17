# Runbook: Air-Gapped Deployment

> **Audience**: Platform engineers deploying Nexus-Hive to a cluster with
> no outbound internet access (regulated / classified / offline).
>
> **Goal**: Stand up Nexus-Hive in an air-gapped Kubernetes cluster with a
> self-hosted Ollama sidecar and a warehouse reachable only on the internal
> network. Target wall time: 3 hours (plus image mirroring lead time).

## Air-gap constraints

In an air-gap environment:

- No `docker.io`, `ghcr.io`, `gcr.io` pulls. All images must be on the
  internal registry.
- No Let's Encrypt. Certificates come from an internal PKI.
- No OpenAI / Anthropic API. Only the in-cluster Ollama sidecar is used.
- No external DNS. `nexus-hive.intranet.corp` resolves internally.
- No git clone from GitHub. Helm chart must be present on a trusted
  terminal (USB sneakernet or internal mirror).
- No `helm repo add` from upstream; repo index must be internally hosted.

## Prerequisites (T-1w: image mirror)

Mirror the required images into your internal registry. List:

| Upstream | Internal path |
|---|---|
| `ghcr.io/kim3310/nexus-hive:0.2.0` | `registry.internal.corp/nexus-hive/app:0.2.0` |
| `ollama/ollama:0.3.12` | `registry.internal.corp/nexus-hive/ollama:0.3.12` |
| `otel/opentelemetry-collector-contrib:0.109.0` | `registry.internal.corp/observability/otelcol:0.109.0` |
| `quay.io/prometheus/prometheus:v2.53.1` | `registry.internal.corp/observability/prometheus:v2.53.1` |
| `grafana/loki:3.2.1` | `registry.internal.corp/observability/loki:3.2.1` |
| `bitnami/external-secrets:0.10.4` | `registry.internal.corp/platform/external-secrets:0.10.4` |

Mirror with `skopeo`:

```bash
skopeo copy \
  docker://ghcr.io/kim3310/nexus-hive:0.2.0 \
  docker://registry.internal.corp/nexus-hive/app:0.2.0
```

Verify:

```bash
skopeo inspect docker://registry.internal.corp/nexus-hive/app:0.2.0 | \
  jq .Digest
```

Also mirror the Ollama model weights to an internal HTTP server or S3 bucket.
For `phi3:3.8b`, you need roughly 2.3 GiB.

## Prerequisites (T-24h)

- [ ] Internal image registry reachable from cluster nodes.
- [ ] Internal PKI issuer configured in cert-manager as `corp-internal-issuer`.
- [ ] `corp-vault` ClusterSecretStore configured (External Secrets Operator).
- [ ] Kubernetes 1.26+, Helm 3.12+ on an operator laptop inside the enclave.
- [ ] Helm chart tarball present: `scp nexus-hive-0.2.0.tgz operator@bastion:~`.
- [ ] Operator account with `cluster-admin` on the target cluster.

Validate:

```bash
kubectl get nodes
kubectl get clustersecretstore corp-vault -o jsonpath='{.status.conditions[0].status}'
# Expected: True
kubectl get clusterissuer corp-internal-issuer
# Expected: READY True
```

## Phase 1: Namespace baseline (5 min)

Apply the same production baseline:

```bash
kubectl apply -f infra/k8s/production/namespace.yaml
kubectl apply -f infra/k8s/production/resourcequota.yaml
kubectl apply -f infra/k8s/production/limitrange.yaml
kubectl apply -f infra/k8s/production/networkpolicy-default-deny.yaml
kubectl apply -f infra/k8s/production/networkpolicy-allow-ingress.yaml
```

**Do NOT apply `networkpolicy-allow-warehouse-egress.yaml` unchanged.**
The default egress rule allows `0.0.0.0/0:443` excluding private CIDRs,
which is the opposite of what you want in an air-gap.

Edit the policy to allow only your internal warehouse CIDR. Example (on-prem
Snowflake equivalent on `10.42.0.0/16`):

```yaml
egress:
  - to:
      - ipBlock:
          cidr: 10.42.0.0/16
    ports:
      - port: 443
        protocol: TCP
```

Apply after editing:

```bash
kubectl apply -f infra/k8s/production/networkpolicy-allow-warehouse-egress.yaml
```

## Phase 2: Vault-backed secrets (10 min)

Confirm the corp Vault has the Nexus-Hive path populated:

```bash
vault kv get kv/data/nexus-hive/snowflake
# Expected: keys user, password
```

No manual Kubernetes secret creation is needed - the ExternalSecret
resources in the Helm chart will reconcile the values.

## Phase 3: Helm install with airgap overlay (30 min)

The airgap overlay enables the Ollama sidecar and sets
`NEXUS_HIVE_ALLOW_EXTERNAL_LLM=false`.

```bash
helm upgrade --install nexus-hive ~/nexus-hive-0.2.0.tgz \
  -n analytics \
  -f helm/nexus-hive/values.yaml \
  -f helm/nexus-hive/values-airgap.yaml \
  --set image.repository=registry.internal.corp/nexus-hive/app \
  --set image.tag=0.2.0 \
  --set ollama.image.repository=registry.internal.corp/nexus-hive/ollama \
  --set ollama.image.tag=0.3.12 \
  --atomic --timeout 10m
```

The first deploy is slower than a normal prod install because:

- Ollama sidecar pulls 2.3 GiB of model weights.
- The StatefulSet-style PVC for weights has to be provisioned.

Watch:

```bash
kubectl -n analytics get pods -w
```

Expected transitions:

```
nexus-hive-xxx   0/2   Pending           0   0s
nexus-hive-xxx   0/2   ContainerCreating 0   8s
nexus-hive-xxx   1/2   Running           0   90s  # api up, ollama still pulling
nexus-hive-xxx   2/2   Running           0   200s # ollama ready
```

## Phase 4: Pull the model into Ollama (15 min)

Because Ollama cannot reach `ollama.com` from inside the enclave, pre-stage
the model weights on an internal HTTP server, or copy them into the PVC:

**Option A: internal HTTP server**

```bash
kubectl -n analytics exec deploy/nexus-hive -c ollama -- sh -c \
  "OLLAMA_HOST=0.0.0.0:11434 ollama pull http://model-mirror.intranet.corp/phi3.gguf"
```

**Option B: copy into PVC directly**

```bash
kubectl -n analytics cp /path/to/phi3.gguf nexus-hive-xxx:/root/.ollama/models/phi3.gguf -c ollama
kubectl -n analytics exec deploy/nexus-hive -c ollama -- ollama list
```

Expected output:

```
NAME            ID              SIZE     MODIFIED
phi3:latest     abc123          2.3 GB   10 minutes ago
```

## Phase 5: Smoke tests (15 min)

```bash
kubectl -n analytics port-forward svc/nexus-hive 8000:80 &
curl -sf http://localhost:8000/health | jq
curl -sf http://localhost:8000/api/meta | jq '.llm_provider'
# Expected: "ollama"
curl -sf http://localhost:8000/api/meta | jq '.network_policy'
# Expected: "airgap"
```

Ask a question to force an LLM call:

```bash
curl -sX POST http://localhost:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What are the top 5 customers by revenue?"}' | jq
```

First response after a cold start can take 8-20 seconds because Ollama
compiles the prompt graph. Subsequent calls should be < 2 seconds.

## Phase 6: Certificate (internal CA) (10 min)

Create an Ingress + Certificate pointing at the internal issuer:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: nexus-hive-tls
  namespace: analytics
spec:
  secretName: nexus-hive-tls
  issuerRef:
    name: corp-internal-issuer
    kind: ClusterIssuer
  commonName: nexus-hive.intranet.corp
  dnsNames:
    - nexus-hive.intranet.corp
```

```bash
kubectl apply -f certificate.yaml
kubectl -n analytics get certificate nexus-hive-tls -w
```

Expected: `READY True` within 30 seconds (internal PKI is fast).

## Phase 7: Observability (20 min)

Air-gap observability almost always uses an internal Prometheus + Loki
already deployed. Wire Nexus-Hive to it:

```bash
kubectl apply -f infra/k8s/observability/servicemonitor.yaml
kubectl apply -f infra/k8s/observability/prometheus-rules.yaml
```

Adjust `additionalLabels.release` to match your internal Prometheus
Operator release name (not `kube-prometheus-stack`).

Verify Prometheus sees 3+ UP targets.

## Phase 8: Final validation (15 min)

Run the gold eval against the governed production schema:

```bash
curl -s http://localhost:8000/api/evals/nl2sql-gold/run | jq '.summary'
```

Expected (regulated dataset, may differ):

```json
{"total": 20, "passed": 17, "failed": 3, "score": 0.85}
```

Run a k6 smoke test (script sits inside the bastion):

```bash
k6 run --vus 10 --duration 60s benchmarks/load_test.js \
  -e BASE_URL=https://nexus-hive.intranet.corp
```

Expected: `http_req_failed < 1%`, p99 < 3500ms (Ollama is slower than
OpenAI/Anthropic).

## Phase 9: Handoff

Document in the internal wiki:

- Internal registry image digests
- Model weight hashes (`sha256sum phi3.gguf`)
- Vault paths for each secret
- Internal DNS + cert chain
- Link to `docs/runbooks/incident-response.md`

## Air-gap-specific failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Image pull `ErrImagePull ghcr.io/...` | Chart still references upstream | `--set image.repository=registry.internal.corp/...` |
| Ollama pod `CrashLoopBackOff` with "no such model" | Model weights never loaded | Copy the gguf to the PVC or pre-pull via internal mirror |
| Ingress 502 | Internal ingress controller blocked from namespace | Verify namespace label `networking.nexus-hive.io/ingress=true` |
| p99 latency > 5s | Ollama on CPU, model too big | Drop to `phi3:3.8b-mini` or move to GPU node pool |
| Policy denies trivial queries | `NEXUS_HIVE_POLICY_PROFILE=strict` too aggressive for your data | Set `standard` via ConfigMap and reload |
| External secrets unreconciled | `corp-vault` store missing a role | `kubectl describe externalsecret nexus-hive-snowflake` |

## Rollback

Same as production:

```bash
helm history nexus-hive -n analytics
helm rollback nexus-hive <revision> -n analytics --wait
```

## Success criteria

- [ ] Pods `Running 2/2`
- [ ] Curl health from inside cluster returns 200
- [ ] Ollama list shows the staged model
- [ ] Gold eval score >= 0.80 on internal dataset
- [ ] Prometheus scraping Nexus-Hive
- [ ] Zero egress outside internal CIDRs
