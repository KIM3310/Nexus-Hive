# Nexus-Hive
[![codecov](https://codecov.io/gh/KIM3310/Nexus-Hive/branch/main/graph/badge.svg)](https://codecov.io/gh/KIM3310/Nexus-Hive)

[![CI](https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml/badge.svg)](https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)

**Multi-agent NL-to-SQL BI copilot** with governed analytics, audit trails, and multi-warehouse support.

Nexus-Hive turns business questions into audited SQL, executes them safely against a warehouse, and returns chart-ready answers with a full agent trace. Every step — translation, policy check, execution, visualization — is independently inspectable.

## Multi-Warehouse Support

| Adapter | Status | Gated By |
|---------|--------|----------|
| **SQLite** (demo) | Active by default | — |
| **Snowflake** | Live when configured | `SNOWFLAKE_ACCOUNT` env var |
| **Databricks** | Live when configured | `DATABRICKS_HOST` + profile/token/client credentials |

All adapters return results in the same format. Auto-detected from credentials or set via `NEXUS_HIVE_WAREHOUSE_ADAPTER`.

## Architecture

```
User Question
     ↓
Agent 1: Translator  (NL → SQL via Ollama/LLM + heuristic fallback)
     ↓
Agent 2: Executor    (policy engine: deny/review/allow + read-only SQL execution)
     ↓                    ↓ (error → retry up to 3x back to Translator)
Agent 3: Visualizer  (Chart.js config generation)
     ↓
Warehouse Adapters   (SQLite | Snowflake | Databricks)
     ↓
Audit Trail + Governance (query tags, session boards, approval workflows, gold evals)
```

## Governance Features

- **Policy Engine (Deny / Review / Allow)** — Write operations are denied outright. `SELECT *` is blocked. Sensitive columns are gated by role. Non-aggregated queries without `LIMIT` are flagged for review.
- **Audit Trails** — Every query is logged with request ID, operator role, policy verdict, adapter used, and execution time. Queryable via `/api/query-audit/recent`.
- **Query Tags** — Structured tags map onto Snowflake `QUERY_TAG` and Databricks warehouse tag conventions for cross-platform audit lineage.
- **Session Boards** — Operator surfaces for pending reviews, approval histories, and query throughput.
- **Gold Evals** — Built-in evaluation suite scores generated SQL against expected feature patterns.

## Quick Start

```bash
git clone https://github.com/KIM3310/Nexus-Hive.git && cd Nexus-Hive
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python3 seed_db.py        # seed 10k enterprise sales records
uvicorn main:app --port 8000
# open http://localhost:8000
```

Docker:
```bash
docker compose up app
# with live LLM inference:
docker compose --profile with-ollama up
docker exec nexus-hive-ollama ollama pull phi3
```

## Core API

```bash
# Ask a question
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Show total net revenue by region"}'

# Stream agent trace (SSE)
curl -N "http://localhost:8000/api/stream?q=Show+total+net+revenue+by+region&rid=REQUEST_ID"

# Runtime metadata
curl http://localhost:8000/api/meta

# Policy check — preview SQL before execution
curl -X POST http://localhost:8000/api/policy/check \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT region_name, SUM(net_revenue) FROM sales GROUP BY region_name", "role": "analyst"}'
```

Interactive docs at http://localhost:8000/docs (Swagger UI) and http://localhost:8000/redoc.

## Snowflake Setup

```bash
pip install -e ".[snowflake]"
export SNOWFLAKE_ACCOUNT=your_account.us-east-1
export SNOWFLAKE_USER=your_username
export SNOWFLAKE_PASSWORD=your_password
export SNOWFLAKE_DATABASE=ANALYTICS
```

## Databricks Setup

```bash
pip install -e ".[databricks]"
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_AUTH_TYPE=databricks-cli
export DATABRICKS_WAREHOUSE_ID=your_sql_warehouse_id
python scripts/bootstrap_databricks_demo.py
```

## Deployment

**Kubernetes**
```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/
```

**GCP Cloud Run** — Terraform configs in `infra/terraform/`.

## Tech Stack

Python · FastAPI · LangGraph · Ollama · Snowflake · Databricks (Statement Execution API) · SQLite · Chart.js · Kubernetes · Terraform

## Related Projects

For the data pipeline that feeds Nexus-Hive's warehouse, see [lakehouse-contract-lab](https://github.com/KIM3310/lakehouse-contract-lab). For enterprise LLM governance patterns, see [enterprise-llm-adoption-kit](https://github.com/KIM3310/enterprise-llm-adoption-kit).

## License

MIT
