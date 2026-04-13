<h1 align="center">Nexus-Hive</h1>

<p align="center">
  <strong>Multi-agent NL-to-SQL copilot with governed analytics, audit trails, and multi-warehouse support</strong>
</p>

<p align="center">
  <a href="https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml"><img src="https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/KIM3310/Nexus-Hive"><img src="https://codecov.io/gh/KIM3310/Nexus-Hive/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.115+-009688.svg" alt="FastAPI"></a>
</p>

---

Nexus-Hive turns natural-language business questions into **audited SQL**, executes them safely against a warehouse, and returns **chart-ready answers with a full agent trace**. Every step -- translation, policy check, execution, visualization -- is independently inspectable, testable, and governed.

**Why this matters:** Most NL-to-SQL tools generate SQL and run it. Nexus-Hive inserts a policy engine, audit trail, and retry loop between generation and execution -- making it safe for environments where data access requires governance.

---

## Architecture

```mermaid
flowchart TB
    User["Business User / Analyst"]
    User -->|"Natural language question"| API["FastAPI Runtime\n/api/ask"]

    subgraph AgentPipeline["LangGraph Multi-Agent Pipeline"]
        direction TB
        T["Agent 1: Translator\nNL --> SQL via Ollama/LLM\n+ heuristic fallback"]
        E["Agent 2: Executor\nPolicy engine + read-only SQL execution"]
        V["Agent 3: Visualizer\nChart.js config generation"]
        T --> E
        E -->|"error + retry budget > 0"| T
        E -->|"success"| V
    end

    API --> AgentPipeline

    subgraph Governance["Governance Layer"]
        direction LR
        PE["Policy Engine\nDeny / Review / Allow"]
        AT["Audit Trail\nJSONL + query tags"]
        GE["Gold Eval Suite\nSQL quality scoring"]
    end

    E --- PE
    E --- AT

    subgraph Warehouses["Warehouse Adapters"]
        direction LR
        SQLite["SQLite\n(demo, active by default)"]
        SF["Snowflake\n(live when configured)"]
        DB["Databricks\n(live when configured)"]
    end

    E --> Warehouses
    V --> UI["Frontend\nChart.js + agent trace viewer"]
```

The pipeline is built with **LangGraph** as a compiled state graph. Each agent is a node with typed state (`AgentState`), connected by edges with conditional routing. When the Executor rejects SQL (policy denial or execution error), the graph routes back to the Translator for correction -- up to 3 retries -- without re-running the Visualizer.

---

## Quick Start

### Local (3 commands)

```bash
git clone https://github.com/KIM3310/Nexus-Hive.git && cd Nexus-Hive
make install                 # creates venv, installs deps
python3 seed_db.py           # seeds 10k enterprise sales records into SQLite
make run                     # starts uvicorn on http://localhost:8000
```

Open [http://localhost:8000](http://localhost:8000) for the frontend, or [http://localhost:8000/docs](http://localhost:8000/docs) for Swagger UI.

### Docker

```bash
docker compose up app
# With live LLM inference via Ollama:
docker compose --profile with-ollama up
docker exec nexus-hive-ollama ollama pull phi3
```

### Verify Everything Works

```bash
make verify   # runs lint + pytest + smoke test against a live server
```

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **API Framework** | FastAPI 0.115+ | Async HTTP, OpenAPI docs, middleware |
| **Agent Orchestration** | LangGraph + LangChain Core | State graph, conditional edges, typed agent state |
| **LLM Runtime** | Ollama (phi3 default) | Local inference for SQL generation + chart config |
| **Policy Engine** | Custom Python | Deny/review/allow decisions, sensitive column gating |
| **Warehouse (Demo)** | SQLite + Pandas | Zero-config local execution with 10k seeded records |
| **Warehouse (Prod)** | Snowflake, Databricks | Live adapters via `snowflake-connector-python` / `databricks-sdk` |
| **Visualization** | Chart.js | Bar, line, pie, doughnut charts from query results |
| **Security** | HMAC-signed cookies, RBAC | Operator sessions, token auth, role-based column gating |
| **Resilience** | Circuit Breaker | Ollama failure isolation with auto-recovery |
| **Infrastructure** | Docker, Kubernetes, Terraform | Container, K8s manifests, GCP Cloud Run via Terraform |
| **CI/CD** | GitHub Actions | Lint (ruff), test (pytest + coverage), Docker build |

---

## Multi-Warehouse Support

| Adapter | Status | Gated By | Execution Mode |
|---------|--------|----------|----------------|
| **SQLite** (demo) | Active by default | -- | `local-sqlite` |
| **Snowflake** | Live when configured | `SNOWFLAKE_ACCOUNT` env var | `snowflake-live` |
| **Databricks** | Live when configured | `DATABRICKS_HOST` + auth | `databricks-live` |

All adapters implement the same 5-method interface (`get_schema`, `run_scalar_query`, `fetch_date_window`, `build_table_profiles`, `execute_sql_preview`) and return results in an identical format. The Executor node and Visualizer node never branch on adapter type. See [ADR-002](docs/adr/002-warehouse-adapter-abstraction.md) for the design rationale.

---

## Governance Features

| Feature | Description | Endpoint |
|---------|------------|----------|
| **Policy Engine** | Deny write ops, block `SELECT *`, gate sensitive columns by role, flag non-aggregated queries for review | `POST /api/policy/check` |
| **Audit Trails** | Every query logged with request ID, role, policy verdict, adapter, execution time | `GET /api/query-audit/recent` |
| **Query Tags** | Structured tags mapping onto Snowflake `QUERY_TAG` and Databricks warehouse tag conventions | `GET /api/schema/query-tag` |
| **Session Boards** | Operator surfaces for pending reviews, approval histories, query throughput | `GET /api/query-session-board` |
| **Gold Evals** | Built-in evaluation suite scoring generated SQL against expected feature patterns | `GET /api/evals/nl2sql-gold/run` |
| **Approval Workflows** | Review-required queries produce actionable approval bundles | `GET /api/query-approval-board` |

---

## Core API

```bash
# Ask a question (returns stream URL for agent trace)
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Show total net revenue by region"}'

# Stream agent trace (SSE)
curl -N "http://localhost:8000/api/stream?q=Show+total+net+revenue+by+region&rid=REQUEST_ID"

# Policy check -- preview SQL before execution
curl -X POST http://localhost:8000/api/policy/check \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name", "role": "analyst"}'

# Runtime metadata
curl http://localhost:8000/api/meta

# Run gold eval suite
curl http://localhost:8000/api/evals/nl2sql-gold/run
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger) | [http://localhost:8000/redoc](http://localhost:8000/redoc) (ReDoc)

---

## Test Results and Benchmarks

> From pytest 8.3.5 on Python 3.11 -- `make verify` (lint + test + smoke)

| Metric | Value |
|--------|-------|
| Test files | 8 |
| Total test cases | 80+ |
| Policy engine tests | 38 (deny, review, allow, sensitive columns, query tags) |
| Agent orchestration tests | 12 (translator, executor, visualizer, routing) |
| API endpoint tests | 15 (health, meta, ask, policy, audit, schema) |
| SQL validation tests | 9 (read-only enforcement, injection blocking) |
| Circuit breaker tests | 6 (state transitions, timeout recovery) |

### Endpoint Response Times (local SQLite)

| Endpoint | Avg Response |
|----------|-------------|
| `GET /health` | 21 ms |
| `GET /api/meta` | 16 ms |
| `GET /api/runtime/brief` | 42 ms |
| `GET /api/evals/nl2sql-gold/run` | 9 ms |
| `GET /api/schema/*` | < 1 ms |

---

## Warehouse Setup

### Snowflake

```bash
pip install -e ".[snowflake]"
export SNOWFLAKE_ACCOUNT=your_account.us-east-1
export SNOWFLAKE_USER=your_username
export SNOWFLAKE_PASSWORD=your_password
export SNOWFLAKE_DATABASE=ANALYTICS
```

### Databricks

```bash
pip install -e ".[databricks]"
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_AUTH_TYPE=databricks-cli
export DATABRICKS_WAREHOUSE_ID=your_sql_warehouse_id
python scripts/bootstrap_databricks_demo.py
```

---

## Deployment

**Kubernetes**
```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/
```

**GCP Cloud Run** -- Terraform configs in `infra/terraform/`. See `infra/terraform/README.md` for variables and outputs.

**Docker**
```bash
docker compose up app
```

---

<details>
<summary><strong>For AI Engineers</strong></summary>

### What to look at

- **`graph/nodes.py`** -- The three LangGraph agent nodes (Translator, Executor, Visualizer) with typed `AgentState`, conditional retry routing, and heuristic fallback paths.
- **`circuit_breaker.py`** -- Thread-safe circuit breaker (CLOSED/OPEN/HALF_OPEN) protecting Ollama calls. Auto-recovers after configurable timeout.
- **`policy/engine.py`** -- Rule-based policy engine with deny/review/allow decisions and heuristic SQL inference for when the LLM is unavailable.
- **Prompt injection defense** -- 6 regex patterns detect injection attempts before any LLM call. Input sanitization truncates, strips control chars, and rejects malicious patterns.
- **Gold eval suite** -- 4 built-in evaluation cases score generated SQL against expected feature patterns (JOINs, aggregations, ordering). Accessible via `GET /api/evals/nl2sql-gold/run`.

### Design decisions

- Multi-agent over monolith -- each agent is independently testable, retryable, and fallback-capable. See [ADR-001](docs/adr/001-multi-agent-over-monolith.md).
- LangGraph state graph over ad-hoc async chains -- typed state, conditional edges, and compiled execution. The retry loop is a graph edge, not application code.
- Heuristic fallback isolation -- when Ollama is down, only the affected agent falls back. The Translator uses keyword-based SQL inference; the Visualizer uses chart type heuristics. The Executor never falls back -- it enforces policy regardless.

### Key patterns

- **Adapter pattern** for warehouse abstraction -- same 5-method interface across SQLite, Snowflake, Databricks. See [ADR-002](docs/adr/002-warehouse-adapter-abstraction.md).
- **Circuit breaker** for LLM resilience -- prevents cascading failures when Ollama is overloaded or unreachable.
- **Structured audit logging** -- every query produces a JSONL audit entry with request ID, policy verdict, adapter name, execution time, and fallback flags.

</details>

<details>
<summary><strong>For Data Engineers</strong></summary>

### What to look at

- **`warehouse_adapter.py`** -- Base adapter class, SQLite implementation, adapter registry, and `get_active_warehouse_adapter()` selection logic.
- **`snowflake_adapter.py`** -- Live Snowflake adapter with connection pooling, schema introspection, and `QUERY_TAG` governance metadata.
- **`databricks_adapter.py`** -- Live Databricks adapter using the Statement Execution API with unified auth (token, profile, or client credentials).
- **`config.py`** -- Centralized env var reading, metric layer definitions, lineage relationships, and policy constants.
- **`seed_db.py`** -- Generates 10k synthetic enterprise sales records across 3 normalized tables (sales, products, regions).

### Data model

The demo database models a B2B sales analytics scenario:
- **`sales`** -- 10k transactions with `transaction_id`, `date`, `product_id`, `region_id`, `quantity`, `gross_revenue`, `net_revenue`, `discount_applied`, `profit`, `margin_percentage`
- **`products`** -- Product catalog with `product_id`, `product_name`, `category`
- **`regions`** -- Regional hierarchy with `region_id`, `region_name`, `manager`

### Metric layer

5 certified metrics are defined in `config.py` with SQL expressions, grain, owner, and default dimensions:
`net_revenue`, `gross_revenue`, `profit`, `average_discount`, `units_sold`

### Lineage

Explicit lineage relationships track dimension joins between `sales.product_id -> products.product_id` and `sales.region_id -> regions.region_id`. Queryable via `GET /api/schema/lineage`.

</details>

<details>
<summary><strong>For Solutions Architects</strong></summary>

### What to look at

- **`docs/solution-architecture.md`** -- System boundary, deployment topology, and reliability posture.
- **`infra/k8s/`** -- Kubernetes manifests: Deployment, Service, Ingress, HPA, ConfigMap, Secret, Namespace.
- **`infra/terraform/`** -- GCP Cloud Run deployment with configurable variables and outputs.
- **`docker-compose.yml`** -- Multi-service compose with optional Ollama profile.
- **`security.py`** -- HMAC-signed session cookies, token auth, role-based access control.

### Deployment topology

```
[Browser] --> [FastAPI Runtime] --> [Policy Engine] --> [Warehouse Adapter]
                    |                                         |
                    v                                         v
              [Audit Trail]                        [SQLite | Snowflake | Databricks]
                    |
                    v
              [Gold Eval Suite]
```

### Security posture

- **Operator authentication** -- Token-based auth via `x-operator-token` header or `Authorization: Bearer` token. Configurable via `NEXUS_HIVE_OPERATOR_TOKEN`.
- **Session management** -- HMAC-SHA256 signed cookies with configurable TTL (default 12h, max 7d). Secure flag auto-enabled in production.
- **Role-based column gating** -- Sensitive columns (e.g., `margin_percentage`) are denied to specific roles at the policy engine level, before SQL execution.
- **SQL validation** -- Dual-layer defense: policy engine (deny/review/allow) + adapter-level read-only validation (whitelist: SELECT/WITH/EXPLAIN only).
- **Prompt injection defense** -- Input sanitization with 6 regex patterns, length truncation, and control character stripping.

### Production readiness checklist

- [x] CI/CD with lint, test, coverage, Docker build
- [x] Structured audit logging (JSONL)
- [x] Health check endpoint with diagnostics
- [x] CORS configuration with origin allowlist
- [x] Kubernetes HPA for autoscaling
- [x] Environment-based adapter selection (no code changes for prod)
- [ ] Signed audit export for external reviewers
- [ ] Row-level access simulation per role
- [ ] Private warehouse networking documentation

</details>

---

## Project Structure

```
Nexus-Hive/
  main.py                    # FastAPI entrypoint (thin, delegates to modules)
  config.py                  # Centralized config, constants, metric definitions
  graph/
    nodes.py                 # LangGraph agent nodes + graph builder
  policy/
    engine.py                # Policy evaluation, query tags, heuristic inference
    audit.py                 # Audit trail writer
    governance.py            # Governance surfaces (scorecard, warehouse brief)
  routes/
    ask.py                   # /api/ask + /api/stream (SSE agent trace)
    health_meta.py           # /health, /api/meta
    warehouse.py             # Warehouse adapter endpoints
    auth.py                  # Operator auth session endpoints
  services/
    build_helpers.py         # Runtime brief, meta builders
    streaming.py             # SSE streaming for agent trace
    openai_helpers.py        # Optional OpenAI integration
  warehouse_adapter.py       # Adapter base class + SQLite + registry
  snowflake_adapter.py       # Live Snowflake adapter
  databricks_adapter.py      # Live Databricks adapter
  circuit_breaker.py         # Ollama circuit breaker
  security.py                # HMAC sessions, token auth, RBAC
  seed_db.py                 # 10k-row synthetic dataset generator
  tests/                     # 8 test modules, 80+ test cases
  infra/
    k8s/                     # Kubernetes manifests
    terraform/               # GCP Cloud Run Terraform configs
  frontend/                  # Chart.js + agent trace viewer
  docs/
    adr/                     # Architecture Decision Records
    solution-architecture.md
    discovery-guide.md
```

---

## Related Projects

| Project | Relationship |
|---------|-------------|
| [lakehouse-contract-lab](https://github.com/KIM3310/lakehouse-contract-lab) | Data pipeline that feeds Nexus-Hive's warehouse |
| [enterprise-llm-adoption-kit](https://github.com/KIM3310/enterprise-llm-adoption-kit) | Enterprise LLM governance patterns |

---

## License

MIT
