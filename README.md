# ⬡ Nexus-Hive: Multi-Agent Federated BI Copilot

**Nexus-Hive** is an autonomous Business Intelligence (BI) copilot designed to empower C-Level executives by instantly translating natural language business questions into complex SQL queries, securely executing them, and returning production-ready interactive charts (Chart.js) on a premium glassmorphic dashboard.

Architected by **Doeon Kim (AI Solutions Architect)**, this project demonstrates extreme proficiency in **Multi-Agent Orchestration (LangGraph)**, **Text-to-SQL Pipelines**, **Data Warehousing Patterns**, and **Enterprise Web UI/UX**.

---

## 🏗️ Architecture: The AI Federation

Nexus-Hive replaces single-prompt LLMs with a **Stateful Multi-Agent Graph Architecture**.

1. **The Translator Agent (Node 1)**: Ingests the Database DDL Schema and the executive's natural language question. Generates a strict SQL query (SQLite/PostgreSQL compatible).
2. **The Auditor & Executor Agent (Node 2)**: Intercepts the query. If a destructive command (`DROP`, `DELETE`) is detected, it returns an error state. Otherwise, it executes the payload against the Warehouse (SQLite DB seeded with 10k rows of historical enterprise data) and extracts raw JSON.
3. **The Visualizer Agent (Node 3)**: Analyzes the shape of the raw JSON data and autonomously determines the optimal Chart.js configuration structure (e.g., choosing a `doughnut` chart for categorical group-bys, or a `line` chart for time-series).
4. **The Self-Correction Loop (Edges)**: If the SQL query throws a syntax error, the LangGraph state machine dynamically routes the error back to the Translator Agent to self-correct up to 3 times before failing gracefully.

---

## 🚀 Quick Start (Local Sandbox)

The entire backend is powered by **FastAPI** streaming **Server-Sent Events (SSE)**, with inference handled *locally* via **Ollama (Phi-3)** to guarantee strict B2B Data Privacy compliance.

### 1. Prerequisites
- Python 3.11+
- `ollama` installed via Homebrew (`brew install ollama`)
- Phi-3 model pulled (`ollama pull phi3`)

### 2. Initialization & Data Seeding
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
python3 seed_db.py  # Generates 10,000 realistic enterprise sales records
```

### 3. Launch the Hive
```bash
uvicorn main:app --port 8000
```

### 4. Experience the Platform
1. Navigate to **http://localhost:8000** in your browser.
2. Ask a natural language SQL query such as *"Show me total net revenue by region grouped as a bar chart"*
3. Watch the left **Thought Process Sidebar** as the AI Agents construct the SQL, test it against the Database, and dynamically render the chart for you.

## Service-Grade Surfaces

- `GET /health`: exposes runtime posture, demo readiness, and direct links to the review surfaces.
- `GET /api/meta`: returns the core ops contract, capabilities, and service routes for reviewers.
- `GET /api/runtime/brief`: summarizes the agent contract, retry budget, watchouts, and validation flow before a live demo.
- `GET /api/runtime/warehouse-brief`: exposes warehouse mode, lineage, quality gate, policy examples, and recent audit volume.
- `GET /api/review-pack`: ties executive promises, trust boundary, answer contract, and review routes into one reviewer surface.
- `GET /api/schema/answer`: pins the expected answer structure for SQL, chart payload, trace, and runtime posture.
- `GET /api/schema/lineage`: documents the semantic model and fact-to-dimension relationships.
- `GET /api/schema/policy`: documents deny/review rules, role-sensitive columns, and current policy posture.
- `GET /api/schema/query-audit`: documents the append-only query audit contract keyed by `request_id`.
- `GET /api/evals/nl2sql-gold`: exposes the canonical NL2SQL review set and fallback verdicts for each question.
- `GET /api/evals/nl2sql-gold/run`: executes the deterministic review suite against the local warehouse and reports pass/fail status.
- `POST /api/policy/check`: previews SQL policy decisions before execution.
- `GET /api/query-audit/recent`: shows the latest governed query requests with stage, SQL, retries, and row counts.
- `GET /api/query-audit/{request_id}`: returns the latest audit record and event history for one governed query.
- `POST /api/ask`: now issues a stable `request_id` and a stream URL so every question can be traced through the audit surface.
- Deterministic fallback: if Ollama is unavailable, heuristic SQL and chart inference keep the governed review path alive with explicit logs.
- Frontend runtime brief + review pack: the landing screen now shows answer schema, model, warehouse readiness, executive promises, trust boundary, and agent responsibilities before a query is run.
- Frontend governed analytics board: the landing screen now adds warehouse mode, fallback mode, lineage relations, quality checks, policy rules, runnable eval status, recent query audit history, and request-level audit summaries before a query is trusted.
- Frontend governance workbench: reviewers can now run a live SQL policy preview, execute the deterministic gold eval suite, and inspect request-level audit detail from the landing screen without leaving the main demo surface.

## 2-Minute Review Path

1. Open `/health` to confirm database posture and review links.
2. Read `/api/runtime/warehouse-brief` for quality-gate, lineage, and policy posture.
3. Use the governance workbench to run `/api/policy/check` and `/api/evals/nl2sql-gold/run` before making correctness claims.
4. Use `/api/ask` together with `/api/query-audit/{request_id}` to inspect one governed answer end to end.

## Proof Assets

- `/health`
- `/api/runtime/warehouse-brief`
- `/api/evals/nl2sql-gold/run`
- `/api/query-audit/{request_id}`

## Platform Expansion

Nexus-Hive is also the best anchor repo to grow into a stronger governed analytics system.

- current proof: natural language -> audited SQL -> chart -> agent trace
- next proof: warehouse adapters, lineage, data-quality gates, policy simulation, and governed NL2SQL evaluation
- working spec: `GOVERNED_ANALYTICS_FLAGSHIP_SPEC.ko.md`

<!-- codex:local-verification:start -->
## Local Verification
```bash
/Library/Developer/CommandLineTools/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
python -m compileall -q main.py tests
python -m pytest
```

## Repository Hygiene
- Keep runtime artifacts out of commits (`.codex_runs/`, cache folders, temporary venvs).
- Prefer running verification commands above before opening a PR.

_Last updated: 2026-03-04_
<!-- codex:local-verification:end -->
