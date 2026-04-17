# ADR 005: Helm Chart Over Raw YAML for Kubernetes Deployments

## Status

Accepted

## Date

2026-04-15

## Context

Nexus-Hive ships with a set of raw Kubernetes manifests under
`infra/k8s/` (namespace, deployment, service, configmap, secret, ingress,
hpa). These manifests are sufficient for a single-environment smoke
deployment. They are not sufficient for the enterprise deployments we now
see in production:

- Acme Finance runs four environments (dev, staging, prod, DR) each with
  different replica counts, autoscaling bounds, resource limits, and
  ingress hostnames.
- Northstar Health runs two airgapped clusters where the registry path,
  certificate issuer, and policy profile are all different from the
  upstream defaults.
- Both customers need a reproducible way to track "which manifest is
  running where" via GitOps.

Raw YAML, with or without `kustomize` overlays, forces us into one of
three unattractive positions:

1. **Fork the manifests per environment.** Requires maintaining N copies
   of nearly-identical manifests and hand-merging upstream changes.
2. **Use `kustomize` overlays.** Scales to 3-5 environments but has sharp
   edges around conditional resource inclusion (e.g., `ServiceMonitor`
   only when Prometheus Operator is installed).
3. **Externalize all variance into ConfigMaps.** Hides deployment intent
   behind runtime config, making static review harder and forcing the
   operator to cross-reference runtime state to answer "is HPA enabled?"

We evaluated whether to stay with raw YAML + `kustomize`, introduce
Helm, or adopt a higher-level tool like ArgoCD ApplicationSets or a
Kubernetes Operator.

## Options considered

### Option A: Raw YAML + Kustomize overlays

Pros:

- No new runtime dependency.
- Native to `kubectl apply`.
- Reviewers can read the final rendered YAML directly.

Cons:

- Conditional resource inclusion requires `patches` with `$patch: delete`
  or generating separate overlays per combination of features (HPA, PDB,
  ServiceMonitor, ExternalSecret, etc.). Combinatorial.
- No packaging: no single artifact to push to a registry, sign, and
  reference by digest in GitOps.
- No NOTES.txt-equivalent for operator handoff after install.
- No templated values reference for documentation - the overlays
  themselves become the docs.

### Option B: Helm chart

Pros:

- First-class packaging: chart can be pushed to an OCI registry
  (`ghcr.io/kim3310/nexus-hive` or `registry.internal.corp/helm/...`),
  signed, and pinned by digest.
- Conditional resources via `{{- if .Values... }}` are idiomatic and
  broadly understood.
- Three stock overlays (`values.yaml`, `values-prod.yaml`,
  `values-airgap.yaml`) cover our observed customer patterns.
- Built-in `NOTES.txt` gives the operator actionable next steps post-
  install.
- Lifecycle commands (`upgrade`, `rollback`, `history`, `diff`) match
  the vocabulary our customer SREs already use.
- Well-supported by ArgoCD, Flux, and Terraform's `helm_release`
  resource.

Cons:

- Go template syntax is a known footgun: whitespace, pipelines, and
  `range` loops behave in surprising ways.
- Adds a CLI dependency (`helm 3.12+`) to the operator's machine.
- `helm template` rendering must be validated in CI to catch syntax
  errors that cannot be seen in the source.

### Option C: Kubernetes Operator

A custom Nexus-Hive Operator (CRD + controller) would be the most
polished solution. We rejected it because:

- Not warranted by current feature set. The Operator pattern shines
  when there is meaningful reconciliation logic (upgrade orchestration,
  custom failover, etc.). We have none of that.
- Adds a second component to deploy and monitor (the operator itself).
- Slows iteration: adding a feature requires a new CRD version or
  backwards-compatible schema evolution.
- Raises the barrier for a customer SRE to read and understand the
  deployment.

We may revisit this decision when the product has reconciliation logic
worth centralizing (e.g., multi-region audit-log replication).

### Option D: ArgoCD ApplicationSets + raw YAML

Pros:

- Pure GitOps, no templating layer.
- ApplicationSet generators handle per-environment fan-out.

Cons:

- Couples packaging tightly to a specific GitOps tool. Customers who
  use Flux or Spinnaker would have to re-derive the pattern.
- Does not help with the "render once, verify before apply" workflow
  that our audit customers require.

## Decision

We chose **Option B: ship an official Helm chart** at
`helm/nexus-hive/` with three stock overlays (`values.yaml`,
`values-prod.yaml`, `values-airgap.yaml`).

Raw manifests at `infra/k8s/` are kept for two reasons:

1. Smoke-test deployments without installing Helm.
2. As a readable reference for the final rendered shape.

The chart supersedes the raw manifests for any production deployment.

## Consequences

### Benefits

- **Packaging and provenance.** The chart is published as an OCI
  artifact with a pinned digest. Customers pin to digests, not tags,
  mirroring the supply-chain discipline they already apply to container
  images.

- **Single source of truth for deployment shape.** `values.yaml` is
  self-documenting and linted in CI. Reviewers can answer "is
  NetworkPolicy enabled?" without reading YAML templates.

- **Three overlays cover 90% of customer patterns.** `values-prod.yaml`
  and `values-airgap.yaml` are extracted from the Acme and Northstar
  engagements respectively. New customers starting from one of these
  overlays can usually reach a working install in one day.

- **NOTES.txt is the post-install runbook stub.** It points the
  operator at next steps (rollout status, port-forward, gold eval run)
  and the full runbooks in `docs/runbooks/`.

- **Conditional resources are tractable.** ServiceMonitor,
  PrometheusRule, ExternalSecret, HPA, PDB, NetworkPolicy, and the
  optional Ollama sidecar all guard with `{{- if .Values... }}`.

- **CI enforces correctness.** `helm lint` + `helm template | kubeconform`
  runs on every PR, catching template or Kubernetes schema errors before
  they reach any cluster.

### Tradeoffs

- **Go template syntax remains a source of bugs.** We mitigate this by
  keeping templates small and delegating logic to `values.yaml`
  overlays. A `ct lint` / `kubeconform` CI gate catches most mistakes.

- **Another file to keep in sync with source code.** When we add a new
  env var, it needs to land in `config.py`, `values.yaml`, and one of
  the runbooks. We accept this cost for the packaging and overlay
  benefits.

- **Chart versioning discipline.** The chart `version` (semver of the
  chart itself) and `appVersion` (version of the Nexus-Hive runtime)
  must both be bumped on every release. A CI check enforces this.

- **Two deployment paths (raw YAML and Helm) can diverge.** The raw
  manifests in `infra/k8s/` are not regenerated from the chart; they
  are maintained independently. We accept this because the raw
  manifests are intended as smoke-test scaffolding, not production
  shape.

### Migration path for existing deployments

Deployments currently using raw manifests can migrate in three steps:

1. Install the chart into a new namespace with defaults matching the
   existing deployment (`values.yaml` plus an overlay that mirrors the
   current replica count, resource limits, and env vars).
2. Cut ingress traffic over via a DNS swap or a weighted route.
3. Tear down the old namespace.

No database or state migration is needed because Nexus-Hive is
stateless relative to the warehouse.

## Alternatives reconsidered post-decision

- **Cue or Pulumi for templating**: rejected. Smaller community, steeper
  learning curve for customer SREs. Revisit if Go template limitations
  become blocking.
- **Chart factoring into sub-charts**: rejected for now. Ollama sidecar
  is the only obvious candidate for extraction, and keeping it inline
  simplifies the air-gap story.

## References

- `helm/nexus-hive/Chart.yaml`
- `helm/nexus-hive/values.yaml`
- `helm/nexus-hive/README.md`
- `docs/runbooks/production-deploy.md`
- `docs/runbooks/airgap-deploy.md`
