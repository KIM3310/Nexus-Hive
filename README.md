# Nexus-Hive

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

## Example Queries

Nexus-Hive translates plain English into governed SQL. Here are example questions and the SQL they produce:

| Natural Language Question | Generated SQL |
|--------------------------|---------------|
| "Show total revenue by region" | `SELECT r.region_name, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue FROM sales s JOIN regions r ON s.region_id = r.region_id GROUP BY r.region_name ORDER BY total_net_revenue DESC LIMIT 10` |
| "Show top 5 regions by total profit" | `SELECT r.region_name, ROUND(SUM(s.profit), 2) AS total_profit FROM sales s JOIN regions r ON s.region_id = r.region_id GROUP BY r.region_name ORDER BY total_profit DESC LIMIT 5` |
| "What is the average discount per category?" | `SELECT p.category, ROUND(AVG(s.discount_applied), 4) AS average_discount FROM sales s JOIN products p ON s.product_id = p.product_id GROUP BY p.category ORDER BY average_discount DESC LIMIT 10` |
| "Show monthly net revenue trend" | `SELECT SUBSTR(s.date, 1, 7) AS month, ROUND(SUM(s.net_revenue), 2) AS total_net_revenue FROM sales s GROUP BY month ORDER BY month ASC LIMIT 12` |
| "Show total quantity by category" | `SELECT p.category, SUM(s.quantity) AS total_quantity FROM sales s JOIN products p ON s.product_id = p.product_id GROUP BY p.category ORDER BY total_quantity DESC LIMIT 10` |

Every generated query passes through the policy engine before execution. Queries that contain write operations, wildcard projections, or sensitive column access are automatically denied.

## Governance Features

Nexus-Hive enforces enterprise-grade governance at every stage of the NL-to-SQL pipeline:

- **Policy Engine (Deny / Review / Allow)** — Every SQL query is evaluated against configurable rules before execution. Write operations (`DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `TRUNCATE`) are denied outright. `SELECT *` is blocked to prevent data exfiltration. Sensitive columns (e.g., `margin_percentage`) are gated by role. Non-aggregated queries without `LIMIT` are flagged for operator review.

- **Audit Trails** — Every query is logged with a full governance trace: request ID, operator role, policy verdict, adapter used, execution time, and fallback mode. Audit entries are written to a JSONL log and queryable via `/api/query-audit/recent`.

- **Query Tags** — Each query carries a structured tag (`service=nexus-hive;adapter=...;role=...;request_id=...;purpose=...`) that maps directly onto Snowflake `QUERY_TAG` and Databricks warehouse tag conventions for cross-platform audit lineage.

- **Session Boards** — The runtime exposes session governance surfaces (`/api/runtime/query-session-board`, `/api/runtime/query-approval-board`) that let operators inspect pending reviews, approval histories, and query throughput.

- **Gold Evals** — A built-in evaluation suite (`/api/evals/nl2sql-gold/run`) scores generated SQL against expected feature patterns (e.g., correct JOINs, aggregation functions, GROUP BY clauses) to measure heuristic and LLM quality over time.

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
