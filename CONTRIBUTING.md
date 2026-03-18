# Contributing to Nexus-Hive

Thank you for considering a contribution to Nexus-Hive. This guide covers the setup, development workflow, and pull request process.

## Prerequisites

- **Python 3.11+** (check with `python3 --version`)
- **pip** (bundled with Python 3.11+)
- **Git**
- **Docker** (optional, for containerized runs)

## Local Setup

```bash
# Clone the repo
git clone https://github.com/KIM3310/Nexus-Hive.git
cd Nexus-Hive

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Seed the demo database (SQLite, 10k rows)
python3 seed_db.py

# Start the dev server
uvicorn main:app --reload --port 8000
```

## Project Structure

```
Nexus-Hive/
  graph/nodes.py         # LangGraph agent pipeline (Translator, Executor, Visualizer)
  policy/engine.py       # Policy engine: deny/review/allow decisions
  policy/audit.py        # Audit trail writer
  warehouse_adapter.py   # Base adapter + SQLite adapter
  snowflake_adapter.py   # Snowflake live adapter
  databricks_adapter.py  # Databricks live adapter
  config.py              # Shared configuration and constants
  main.py                # FastAPI application entry point
  tests/                 # pytest test suite
```

## Running Tests

```bash
# Run the full test suite
pytest

# Run with coverage
pytest --cov=. --cov-report=term-missing

# Run a specific test file
pytest tests/test_sql_generation.py -v

# Run a specific test class or method
pytest tests/test_sql_generation.py::TestPolicyEvaluation::test_allow_safe_aggregated_query -v
```

All new code should include tests. Aim for coverage of both the happy path and meaningful edge cases.

## Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check for lint errors
ruff check .

# Auto-fix lint errors
ruff check --fix .

# Format code
ruff format .
```

The CI pipeline runs `ruff check .` on every push. PRs with lint failures will not be merged.

Configuration is in `pyproject.toml` under `[tool.ruff]`.

## Type Checking

Optional but encouraged:

```bash
mypy --ignore-missing-imports .
```

## Branching and PR Process

1. **Fork** the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** in small, focused commits. Each commit should pass `pytest` and `ruff check .` independently.

3. **Write or update tests** for any changed logic. The test suite lives in `tests/` and uses pytest with `monkeypatch` for mocking.

4. **Open a pull request** against `main` with:
   - A clear title describing the change
   - A summary of what was changed and why
   - Links to related issues (if any)

5. **CI checks** must pass before merge:
   - `ruff check .` (lint)
   - `pytest` (all tests green)

## Adapter Development

If you are adding a new warehouse adapter:

1. Subclass `WarehouseAdapter` in `warehouse_adapter.py`
2. Implement all abstract methods: `get_schema`, `run_scalar_query`, `fetch_date_window`, `build_table_profiles`, `execute_sql_preview`
3. Register the adapter in `_build_contracts()`
4. Add corresponding tests with mocked connections
5. Document setup instructions in the README

## Code Style

- Use type annotations on all function signatures
- Write docstrings for public functions (Google style)
- Keep functions focused: one responsibility per function
- Prefer explicit over implicit (no `*args` / `**kwargs` in public APIs)

## Reporting Issues

Use the GitHub issue templates for [bug reports](.github/ISSUE_TEMPLATE/bug_report.yml) and [feature requests](.github/ISSUE_TEMPLATE/feature_request.yml).

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
