# ADR 006: OpenTelemetry + Prometheus + Loki Observability Stack

## Status

Accepted

## Date

2026-04-15

## Context

Nexus-Hive is a Tier-1 service at customer sites where missed data can
result in compliance violations, not just inconvenience. The observability
story has three overlapping requirements:

1. **Real-time SLO monitoring**: availability, latency, error rate,
   circuit-breaker state. Used by the on-call engineer. Dashboards and
   alerts must be ready in the customer's existing tool.
2. **Audit trail as an SLI**: the audit-write pipeline is itself under
   SLO. Missing audit records are a governance incident, not just a
   logging hiccup. The metric `nexus_hive_audit_last_write_timestamp_seconds`
   must be scraped and alerted on.
3. **Distributed tracing**: when an `/api/ask` call takes 4 seconds, we
   need to know whether the latency is in the Translator, the Executor,
   the warehouse, or the Visualizer. Span-level timing is required.

Every customer has some subset of: Prometheus, Datadog, New Relic,
Dynatrace, Grafana Cloud, Splunk, Elastic, Loki. The question is which
emission format and which stack we ship as a first-class reference.

## Options considered

### Option A: Native Prometheus client + structured logs + Jaeger client

Use the `prometheus_client` Python library for metrics, `structlog` for
JSON logs, and the `opentracing` Jaeger client for traces.

Pros:

- No OpenTelemetry dependency. Each component is directly instrumented
  in its own format.
- Proven stacks; customers understand Prometheus and Jaeger.

Cons:

- Three separate instrumentation libraries in the codebase. Each with
  its own lifecycle, configuration, and context-propagation semantics.
- No automatic correlation between traces, logs, and metrics. Operators
  see a slow span in Jaeger but have to manually search Loki for logs
  of the same request.
- Vendor swap is expensive: changing from Jaeger to Tempo, or adding
  Datadog support, means rewriting the tracing layer.

### Option B: OpenTelemetry for all signals + Prometheus + Loki

Use OpenTelemetry SDK for metrics, logs, and traces. Export via an
OTLP pipeline to a customer-chosen backend. Default reference stack is
Prometheus (metrics), Loki (logs), Tempo/Jaeger (traces), with the
OpenTelemetry Collector as the switchboard.

Pros:

- Single instrumentation library in the codebase.
- Automatic correlation: traces, logs, and metrics share a trace ID and
  span ID. Grafana's Tempo integration lets operators pivot from a slow
  span straight to the log lines of that span.
- Vendor-agnostic wire format (OTLP). Customers who use Datadog or
  Dynatrace can point the OTEL exporter at their receiver without any
  code change in Nexus-Hive.
- First-class support for resource attributes (`service.name`,
  `service.version`, `deployment.environment`), which customers already
  use in their observability taxonomies.

Cons:

- OpenTelemetry Python SDK has a longer startup time than native
  Prometheus instrumentation. Mitigated by lazy initialization.
- The OpenTelemetry Collector adds an operational component (at least a
  DaemonSet or deployment).
- More layers means more places for the pipeline to silently fail. We
  address this with an `up{job="otel-collector"}` alert and a local
  fallback writer.

### Option C: Vendor-specific (e.g., Datadog APM native)

Pros:

- Least work for a Datadog customer: drop in the `ddtrace-run` wrapper
  and you are done.

Cons:

- Excludes every non-Datadog customer. Acme uses Prometheus + Grafana.
  Northstar uses Splunk + a home-grown metrics system.
- Contradicts the vendor-agnostic posture that our other decisions
  (adapter abstraction in ADR-002) have taken.

### Option D: Logs-only with manual metric extraction

Pros:

- Dead simple. JSON logs, let Loki + LogQL derive metrics.

Cons:

- High cardinality in LogQL is expensive at customer scale.
- No distributed tracing without extra work.
- SLOs cannot be expressed cleanly as LogQL queries for all customer
  backends.

## Decision

We chose **Option B: OpenTelemetry for all three signals with a reference
stack of Prometheus (metrics), Loki (logs via Promtail or Fluent Bit),
and Tempo (traces), bridged by the OpenTelemetry Collector.**

The reference stack is called out explicitly in the Helm chart and
`docs/runbooks/production-deploy.md`. Customers with a different backend
point the OTLP endpoint at their own receiver and reuse everything else.

## Consequences

### Benefits

- **One SDK, three signals.** `opentelemetry-instrumentation-fastapi`,
  `opentelemetry-instrumentation-sqlite3`, and custom manual spans in
  `graph/nodes.py` cover the three agents. Context propagation is
  automatic.

- **Automatic trace/log/metric correlation.** A log line emitted inside
  a FastAPI request carries the same `trace_id` as the APM span and
  the same exemplar-enriched Prometheus metric. Grafana's "logs for this
  span" button works out of the box.

- **Resource-attribute-driven grouping.** Prometheus series and Loki log
  streams are both grouped by `service.name`, `service.namespace`,
  `deployment.environment`. Customers can reuse dashboards across
  environments with a single variable change.

- **SLO rules travel with the chart.** `helm/nexus-hive/values.yaml`
  embeds the default `PrometheusRule` set. Customers get
  `NexusHiveHighErrorRate`, `NexusHiveHighLatency`,
  `NexusHiveCircuitBreakerOpen`, and `NexusHiveAuditWriteStalled` with a
  single `prometheusRule.enabled=true` flip.

- **Vendor swap is cheap.** A Datadog customer sets
  `OTEL_EXPORTER_OTLP_ENDPOINT` to their Datadog OTLP receiver. No code
  change. A Dynatrace customer does the same. A self-hosted customer
  points at their Collector.

- **Audit trail becomes a first-class SLI.** The
  `nexus_hive_audit_last_write_timestamp_seconds` metric is a Prometheus
  gauge that we alert on when the audit pipeline stalls while traffic
  continues. This converts "are we capturing audit data correctly" from
  a post-incident question to a pre-incident alert.

### Tradeoffs

- **Startup cost.** OTel SDK initialization adds ~150 ms to cold start.
  Acceptable in Kubernetes but worth measuring in Cloud Run where cold
  starts matter more. We set `startup_cpu_boost = true` in the Cloud Run
  spec to offset this.

- **Pipeline failure modes.** OpenTelemetry Collector failures can
  silently swallow telemetry. We mitigate by:
  - Emitting the `up{job="otel-collector"}` alert.
  - Keeping a lightweight local stdout fallback so logs are always
    recoverable even if the Collector is down.
  - Including `audit_last_write_timestamp` as a gauge so stalled audit
    writes are detectable regardless of Collector health.

- **Dependency weight.** The OTel SDK and instrumentation packages add
  ~40 MB to the container image. We accept the cost.

- **Cardinality discipline is still required.** OTel makes it easy to
  emit high-cardinality attributes (user IDs, request IDs). The
  `PrometheusRule` template drops noisy series at scrape time. A
  cardinality guard in `config.py` caps unbounded labels.

### Rollout / compatibility

Nexus-Hive 0.1.x shipped with native `prometheus_client` instrumentation.
The 0.2.x line introduces OpenTelemetry alongside, in parallel, via the
`NEXUS_HIVE_INSTRUMENTATION=otel` flag. When `otel` is set (the default
in prod):

- Metrics are emitted in OTLP format. The OTel Collector converts to
  Prometheus for scraping by the existing `ServiceMonitor`.
- The legacy `/metrics` endpoint is still available for customers who
  have not yet deployed a Collector.

Both emission modes can coexist during a customer migration. The legacy
path will be removed in 0.4.x at the earliest.

## Alternatives reconsidered post-decision

- **Move to eBPF-based instrumentation (e.g., Pixie):** attractive for
  zero-code metrics but incomplete for business-level SLIs. Revisit if
  Nexus-Hive adopts a language-native agent that makes spans harder to
  emit manually.

- **Drop Loki for the customer's incumbent log aggregator:** reasonable
  in airgap environments with Splunk or Elastic pre-deployed. The
  default `values.yaml` does not enforce Loki; customers override the
  log shipping config freely.

## References

- `helm/nexus-hive/values.yaml` - `serviceMonitor`, `prometheusRule`,
  `otelSidecar`
- `infra/k8s/observability/servicemonitor.yaml`
- `infra/k8s/observability/prometheus-rules.yaml`
- `docs/runbooks/incident-response.md` - how each alert maps to
  action
- `docs/runbooks/production-deploy.md` - Phase 6 observability wiring
- ADR-003 (multi-agent pipeline) - explains why per-agent spans matter
