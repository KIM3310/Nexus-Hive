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
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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
- `GET /api/review-pack`: ties executive promises, trust boundary, answer contract, and review routes into one reviewer surface.
- `GET /api/schema/answer`: pins the expected answer structure for SQL, chart payload, trace, and runtime posture.
- Frontend runtime brief + review pack: the landing screen now shows answer schema, model, warehouse readiness, executive promises, trust boundary, and agent responsibilities before a query is run.

## Platform Expansion

Nexus-Hive is also the best anchor repo to grow into a stronger governed analytics system.

- current proof: natural language -> audited SQL -> chart -> agent trace
- next proof: warehouse adapters, lineage, data-quality gates, policy simulation, and governed NL2SQL evaluation
- working spec: `GOVERNED_ANALYTICS_FLAGSHIP_SPEC.ko.md`

<!-- codex:local-verification:start -->
## Local Verification
```bash
test -f README.md -o -f README
```

## Repository Hygiene
- Keep runtime artifacts out of commits (`.codex_runs/`, cache folders, temporary venvs).
- Prefer running verification commands above before opening a PR.

_Last updated: 2026-03-04_
<!-- codex:local-verification:end -->
