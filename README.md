# Nexus-Hive: Governed Analytics Runtime

**Nexus-Hive** turns a business question into SQL, executes it against a warehouse, and returns both a chart and an audit trail.

The pipeline flow is: question -> governed SQL -> query audit -> visualization -> summary. Translation, policy checks, execution, and visual output stay separate so each step can be inspected independently.

---

## Architecture

Nexus-Hive uses a **Stateful Multi-Agent Graph** instead of a single-prompt LLM.

1. **Translator Agent (Node 1)**: Takes the database DDL schema and a natural language question, generates a strict SQL query (SQLite/PostgreSQL compatible).
2. **Auditor & Executor Agent (Node 2)**: Intercepts the query. Blocks destructive commands (`DROP`, `DELETE`). Otherwise executes against the warehouse (SQLite DB seeded with 10k rows) and extracts raw JSON.
3. **Visualizer Agent (Node 3)**: Analyzes the JSON shape and picks the right Chart.js config (e.g., `doughnut` for categorical, `line` for time-series).
4. **Self-Correction Loop (Edges)**: On SQL syntax errors, the state machine routes back to the Translator for up to 3 retries before failing gracefully.

---

## Quick start

The backend uses **FastAPI** with **SSE streaming**, and inference is handled locally via **Ollama (Phi-3)** for data privacy.

### Prerequisites
- Python 3.11+
- `ollama` installed (`brew install ollama`)
- Phi-3 model pulled (`ollama pull phi3`)

### Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
python3 seed_db.py  # Generates 10,000 realistic enterprise sales records
```

### Run
```bash
uvicorn main:app --port 8000
```

Open **http://localhost:8000**, ask something like *"Show me total net revenue by region as a bar chart"*, and watch the agent pipeline work through each step in the sidebar.

## Runtime notes
- `uvicorn main:app` serves both the API and the local frontend in `frontend/`.
- `nexus_enterprise.db` is the seeded demo warehouse (checked in for reproducibility); `seed_db.py` regenerates it.
- `.runtime/` stores local query-audit and event artifacts (ephemeral).

## API endpoints

### Core
- `GET /health` -- runtime status and config
- `GET /api/meta` -- service capabilities and routes
- `POST /api/ask` -- submit a question, get a stable `request_id` and stream URL

### Governance
- `GET /api/runtime/brief` -- agent contract, retry budget, and validation flow
- `GET /api/runtime/warehouse-brief` -- warehouse mode, lineage, quality gate, and policy info
- `GET /api/runtime/semantic-governance-pack` -- metric certification and approval posture
- `GET /api/runtime/lakehouse-readiness-pack` -- connector posture and delivery boundaries
- `GET /api/review-pack` -- executive summary, trust boundary, and answer contract
- `POST /api/policy/check` -- preview SQL policy decisions before execution

### Schema
- `GET /api/schema/answer` -- expected answer structure (SQL, chart, trace)
- `GET /api/schema/lineage` -- semantic model and fact-to-dimension relationships
- `GET /api/schema/policy` -- deny/review rules and role-sensitive columns
- `GET /api/schema/query-audit` -- append-only audit contract keyed by `request_id`

### Audit and evaluation
- `GET /api/query-audit/recent` -- latest governed query requests
- `GET /api/query-audit/{request_id}` -- audit record and event history for one query
- `GET /api/query-review-board` -- triage view for failed, denied, and fallback requests
- `GET /api/query-approval-board` -- review-required queries needing human approval
- `GET /api/evals/nl2sql-gold` -- canonical NL2SQL evaluation set
- `GET /api/evals/nl2sql-gold/run` -- execute the eval suite and report pass/fail

### Fallback behavior
If Ollama is unavailable, heuristic SQL and chart inference keep the pipeline working with explicit logging.

## Verification
```bash
python -m pip install -e ".[dev]"
python -m compileall -q main.py tests
python -m pytest
```

## Further reading
- Architecture: [`docs/solution-architecture.md`](docs/solution-architecture.md)
- Overview: [`docs/executive-one-pager.md`](docs/executive-one-pager.md)
- Discovery notes: [`docs/discovery-guide.md`](docs/discovery-guide.md)
