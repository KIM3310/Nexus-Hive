# Nexus-Hive

**Natural-language analytics with an explicit SQL execution gate.**

The workflow translates a question, checks the resulting SQL, executes an allowed query, and returns chart-ready results with a trace. SQLite and deterministic fallback queries make the core flow inspectable locally.

[Demo](https://nexus-hive.pages.dev/) · [CI](https://github.com/KIM3310/Nexus-Hive/actions/workflows/ci.yml) · [MIT](LICENSE)

## Inspect the implementation

| Engineering problem | Design decision | Code / evidence |
|---|---|---|
| Formatting and comments can bypass string-based SQL checks | Parse the statement structure, inspect column references, and require one read query. | [Policy engine](policy/engine.py) · [Boundary tests](tests/test_sql_policy_boundaries.py) |
| A review warning must affect execution | Stop denied and review-required queries before the warehouse call; do not route them into automatic retries. | [Executor and routing](graph/nodes.py) |
| Multiple warehouses need a consistent interface | Keep warehouse behavior behind adapters and expose the active execution mode. | [Adapter contract](warehouse_adapter.py) |

```text
Question → translator → SQL policy → allow → warehouse → chart
                            └─────→ review / deny → stop
```

## Run it

Requires Python 3.11+.

```bash
make install
make verify
make run
```

Open `http://127.0.0.1:8000`. `make verify` checks formatting, lint, tests, coverage, and the running API. See the reference for Ollama and optional warehouse configuration.

## Scope

The demo uses synthetic data and can fall back to predefined SQL; it is not a model-accuracy benchmark. The SQL gate is a conservative application policy, not a substitute for database grants, authenticated identities, or a complete SQL sandbox. Unknown roles fail closed. Review-required queries remain stopped; this change does not create an approval authority or a live approval workflow. Snowflake and Databricks integrations require their own accounts and validation.

## Further reading

- [Detailed reference](REFERENCE.md)
- [Engineering changes and regression cases](docs/engineering-notes.md)
- [Cloud architecture](docs/cloud-ai-architecture.md) · [Machine-readable blueprint](docs/architecture/blueprint.json) · [Blueprint validator](scripts/validate_architecture_blueprint.py)
