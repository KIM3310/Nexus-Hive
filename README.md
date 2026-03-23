# Nexus-Hive

[![CI](https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml/badge.svg)](https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)

**Multi-agent NL-to-SQL BI copilot** with governed analytics, audit trails, and multi-warehouse support.

Nexus-Hive turns executive business questions into audited SQL, executes them safely against a data warehouse, and returns chart-ready answers with a full agent trace. Every step -- translation, policy check, execution, visualization -- is independently inspectable.

---

## Architecture

```
                         +------------------+
                         |   User Question  |
                         +--------+---------+
                                  |
                    +-------------v--------------+
                    |   Agent 1: Translator      |
                    |   NL -> SQL (Ollama/LLM)   |
                    |   + heuristic fallback      |
                    +-------------+--------------+
                                  |
                    +-------------v--------------+
                    |   Agent 2: Executor         |
                    |   Policy engine (deny/      |
                    |   review/allow) + read-only |
                    |   SQL execution             |
                    +-------------+--------------+
                           |             |
                     [error+retry]  [success]
                           |             |
                    +------v------+  +---v------------------+
                    | Translator  |  | Agent 3: Visualizer  |
                    | (up to 3x)  |  | Chart.js config gen  |
                    +-------------+  +----------------------+
                                              |
                    +-------------------------v-----------+
                    |          Warehouse Adapters          |
                    |  SQLite | Snowflake | Databricks     |
                    +-----------------------------------------+
                                              |
                    +-------------------------v-----------+
                    |     Audit Trail + Governance         |
                    |  Query tags, session boards,         |
                    |  approval workflows, gold evals      |
                    +-----------------------------------------+
```

### Multi-Warehouse Support

| Adapter | Status | Execution Mode | Gated By |
|---------|--------|----------------|----------|
| **SQLite** (demo) | Active | Local execution | Default |
| **Snowflake** | Live-ready | `snowflake-connector-python` | `SNOWFLAKE_ACCOUNT` env var |
| **Databricks** | Live-ready | `databricks-sql-connector` | `DATABRICKS_HOST` env var |

All adapters return results in the same format. The active adapter is selected via the `NEXUS_HIVE_WAREHOUSE_ADAPTER` env var or auto-detected from credentials.

---

## Quick Start

### Local (Python)

```bash
# Clone and setup
git clone https://github.com/KIM3310/Nexus-Hive.git
cd Nexus-Hive

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Seed the demo database (10k enterprise sales records)
python3 seed_db.py

# Run the server
uvicorn main:app --port 8000
```

Open **http://localhost:8000** and ask a question like *"Show total net revenue by region"*.

### Docker

```bash
# App only (uses heuristic fallback without Ollama)
docker compose up app

# App + Ollama for live LLM inference
docker compose --profile with-ollama up

# Pull the model after Ollama starts
docker exec nexus-hive-ollama ollama pull phi3
```

### Docker (build only)

```bash
docker build -t nexus-hive .
docker run -p 8000:8000 nexus-hive
```

---

## Snowflake Setup

1. Install the Snowflake connector:
   ```bash
   pip install -e ".[snowflake]"
   ```

2. Set environment variables:
   ```bash
   export SNOWFLAKE_ACCOUNT=your_account.us-east-1
   export SNOWFLAKE_USER=your_username
   export SNOWFLAKE_PASSWORD=your_password
   export SNOWFLAKE_WAREHOUSE=COMPUTE_WH
   export SNOWFLAKE_DATABASE=ANALYTICS
   export SNOWFLAKE_SCHEMA=PUBLIC
   ```

3. The Snowflake adapter activates automatically when `SNOWFLAKE_ACCOUNT` is set. Query execution, schema introspection, and connection pooling are handled transparently.

## Databricks Setup

1. Install the Databricks connector:
   ```bash
   pip install -e ".[databricks]"
   ```

2. Set environment variables:
   ```bash
   export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   export DATABRICKS_TOKEN=dapi_your_token_here
   export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/your_warehouse_id
   export DATABRICKS_CATALOG=main
   export DATABRICKS_SCHEMA=default
   ```

3. The Databricks adapter activates automatically when `DATABRICKS_HOST` is set.

---

## API Documentation

Interactive API docs are available at runtime:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

### Core Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Full runtime metadata
curl http://localhost:8000/api/meta

# Submit a question (returns request_id + stream URL)
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Show total net revenue by region"}'

# Stream the agent trace (SSE)
curl -N "http://localhost:8000/api/stream?q=Show+total+net+revenue+by+region&rid=REQUEST_ID"
```

### Governance Endpoints

```bash
# Runtime brief (agent contract, retry policy)
curl http://localhost:8000/api/runtime/brief

# Review resource pack (built-in no-key walkthrough)
curl http://localhost:8000/api/runtime/review-resource-pack

# Warehouse brief (lineage, quality gate, adapters)
curl http://localhost:8000/api/runtime/warehouse-brief

# Warehouse target scorecard (Snowflake/Databricks fit)
curl "http://localhost:8000/api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract"

# Governance scorecard
curl "http://localhost:8000/api/runtime/governance-scorecard?focus=quality"

# Semantic governance pack (metric certification + approval posture)
curl http://localhost:8000/api/runtime/semantic-governance-pack

# Lakehouse readiness pack
curl "http://localhost:8000/api/runtime/lakehouse-readiness-pack?target=databricks-sql-contract"

# Policy check (preview SQL before execution)
curl -X POST http://localhost:8000/api/policy/check \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name", "role": "analyst"}'
```

### Audit & Evaluation

```bash
# Recent query audits
curl http://localhost:8000/api/query-audit/recent

# Query review board (triage failed/denied requests)
curl http://localhost:8000/api/query-review-board

# Gold eval suite (NL2SQL correctness benchmark)
curl http://localhost:8000/api/evals/nl2sql-gold/run
```

## Reviewer Fast Path

1. `GET /health`
2. `GET /api/runtime/brief`
3. `GET /api/runtime/review-resource-pack`
4. `GET /api/runtime/semantic-governance-pack`
5. `GET /api/runtime/warehouse-target-scorecard?target=snowflake-sql-contract`
6. `GET /api/query-review-board`
7. `GET /api/review-pack`

---

## Infrastructure

### Kubernetes

Production-ready manifests are in `infra/k8s/`:

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/configmap.yaml
kubectl apply -f infra/k8s/secret.yaml    # Edit secrets first
kubectl apply -f infra/k8s/deployment.yaml
kubectl apply -f infra/k8s/service.yaml
kubectl apply -f infra/k8s/ingress.yaml
kubectl apply -f infra/k8s/hpa.yaml
```

### Terraform (GCP)

GCP Cloud Run deployment is in `infra/terraform/`.

---

## Testing

```bash
# Run all tests
pytest tests -v

# Run with coverage (70% minimum enforced in CI)
pytest tests -v --cov=. --cov-fail-under=70

# Lint
pip install ruff
ruff check .
```

### Test Coverage

The test suite covers:
- **API endpoints**: health, meta, ask, stream, policy, audit
- **Agent orchestration**: translator, executor, visualizer nodes
- **SQL generation**: heuristic inference, policy evaluation, validation
- **Circuit breaker**: state transitions, timeout recovery
- **Frontend metadata**: OG tags, preview assets, reviewer UI contract

---

## Project Structure

```
Nexus-Hive/
  main.py                    # FastAPI entrypoint + route handlers
  config.py                  # Shared configuration and constants
  warehouse_adapter.py       # SQLite adapter + base adapter pattern
  snowflake_adapter.py       # Live Snowflake adapter (env-var gated)
  databricks_adapter.py      # Live Databricks adapter (env-var gated)
  security.py                # Operator auth, HMAC sessions, RBAC
  runtime_store.py           # Event persistence (JSONL/SQLite)
  circuit_breaker.py         # Ollama circuit breaker
  exceptions.py              # Custom exception hierarchy
  logging_config.py          # Structured JSON logging
  seed_db.py                 # Demo database generator
  graph/
    nodes.py                 # LangGraph agent nodes
  policy/
    engine.py                # SQL policy engine + heuristic inference
    audit.py                 # Query audit trail + review boards
    governance.py            # Scorecards, warehouse briefs, gold evals
  frontend/                  # Static frontend (Chart.js + SSE)
  tests/                     # pytest suite (98 tests)
  infra/
    k8s/                     # Kubernetes manifests
    terraform/               # GCP Terraform configs
  docker-compose.yml         # Local dev (app + optional Ollama)
  Dockerfile                 # Production container image
  .env.example               # Environment variable reference
```

---

## License

MIT
