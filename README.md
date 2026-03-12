# ⬡ Nexus-Hive: Multi-Agent Federated BI Copilot

**Nexus-Hive** is a governed BI copilot that turns a business question into SQL, executes it against a warehouse, and returns both a chart and an audit trail that a reviewer can inspect.

This portfolio project focuses on **Multi-Agent Orchestration (LangGraph)**, **Text-to-SQL Pipelines**, **Data Warehousing Patterns**, and an executive-facing BI review flow.

The strongest proof path is straightforward: question -> governed SQL -> query audit -> visualization -> review pack. The repo is structured so that translation, policy checks, execution, and visual output stay inspectable instead of collapsing into one prompt-shaped black box.

---

## Portfolio posture
- Read this repo like a governed analytics desk for executive questions, not like a free-form text-to-chart demo.
- Query audit, gold eval, approval board, and review pack are the evidence chain behind any claim of trustworthy BI automation.


## Role signals
- **AI engineer:** text-to-SQL, audit, policy checks, and eval surfaces show more than a prompt-to-chart demo.
- **Solution / cloud architect:** the translation, execution, and visualization layers stay separate enough to explain trust boundaries clearly.
- **Field / solutions engineer:** the repo is set up for a fast executive question -> governed answer -> review-pack walkthrough.


## Portfolio context
- **Portfolio family:** governed ops and control towers
- **This repo's role:** governed analytics / executive BI branch of the control-tower cluster.
- **Related repos:** `regulated-case-workbench`, `fab-ops-yield-control-tower`, `smallbiz-ops-copilot`

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

## Canonical runtime + artifact map
- Canonical runtime: `uvicorn main:app` serves both the governed analytics API and the lightweight local frontend in `frontend/`.
- `nexus_enterprise.db` is the seeded local demo warehouse checked in for reproducible review; `seed_db.py` regenerates it when needed.
- `.runtime/` stores local query-audit and event artifacts for the review surfaces and should be treated as ephemeral runtime state.
- `docs/` is explanatory context; the review APIs and local frontend are the canonical proof surfaces.

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
- `GET /api/query-review-board`: prioritizes failed, denied, review-required, and fallback-heavy requests into one operator triage surface.
- `GET /api/query-approval-board`: isolates review-required queries that still need an explicit human approval pass.
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

## Review Flow

1. Open `/health` to confirm database posture and review links.
2. Read `/api/runtime/warehouse-brief` for quality-gate, lineage, and policy posture.
3. Use the governance workbench to run `/api/policy/check` and `/api/evals/nl2sql-gold/run` before making correctness claims.
4. Open `/api/query-approval-board` to isolate review-required SQL before treating it as execution-ready.
5. Open `/api/query-review-board` to inspect current failed, denied, and fallback-heavy requests.
6. Use `/api/ask` together with `/api/query-audit/{request_id}` to inspect one governed answer end to end.

## Further Reading

- Architecture: [`docs/solution-architecture.md`](docs/solution-architecture.md)
- Overview: [`docs/executive-one-pager.md`](docs/executive-one-pager.md)
- Discovery notes: [`docs/discovery-guide.md`](docs/discovery-guide.md)

## Supporting Files

- `/health`
- `/api/runtime/warehouse-brief`
- `/api/query-review-board`
- `/api/evals/nl2sql-gold/run`
- `/api/query-audit/{request_id}`

## Platform Expansion

Nexus-Hive is also the best anchor repo to grow into a stronger governed analytics system.

- current proof: natural language -> audited SQL -> chart -> agent trace
- next proof: warehouse adapters, lineage, data-quality gates, policy simulation, and governed NL2SQL evaluation

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
