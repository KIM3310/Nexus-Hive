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

## Public recording and local queries

The [Cloudflare Pages demo](https://nexus-hive.pages.dev/) serves only `frontend/`. **View recorded example** opens the existing `req-recorded-1042` fixture. Its question, SQL, and REVIEW decision are recorded metadata. The action does not run a new query, approve SQL, or generate a chart.

The local FastAPI app is a separate runtime. At `http://127.0.0.1:8000`, the input accepts new questions against synthetic SQLite data. Ollama is optional; deterministic SQL fallback is not a model-accuracy result. Cloudflare Pages does not host this Python API or a warehouse.

For an explicitly configured API host, set `data-api-base` on the body or `window.NEXUS_API_BASE` before `app.js` loads. Do not put credentials in the static page. The existing backend access controls and CORS policy still apply.

### Check browser behavior

```bash
make browser-install
make browser-test
```

These checks cover narrow layouts, recorded request identity, keyboard disclosure, and a real local POST/SSE query over disposable synthetic data. The test runtime has no model or warehouse credentials. The browser still loads the page's public Chart.js and font resources.

If Google Chrome is already installed, use `NEXUS_HIVE_BROWSER_CHANNEL=chrome make browser-test` instead of downloading Chromium. CI runs these browser checks in addition to the existing Python and Docker checks.

See [deployment activation](docs/DEPLOYMENT_ACTIVATION.md) for the static artifact and release limits.

## Scope

The demo uses synthetic data and can fall back to predefined SQL; it is not a model-accuracy benchmark. The SQL gate is a conservative application policy, not a substitute for database grants, authenticated identities, or a complete SQL sandbox. Unknown roles fail closed. Review-required queries remain stopped; this change does not create an approval authority or a live approval workflow. Snowflake and Databricks integrations require their own accounts and validation.

## Further reading

- [Detailed reference](REFERENCE.md)
- [Engineering changes and regression cases](docs/engineering-notes.md)
- [Cloud architecture](docs/cloud-ai-architecture.md) · [Machine-readable blueprint](docs/architecture/blueprint.json) · [Blueprint validator](scripts/validate_architecture_blueprint.py)

[Design decisions and implementation evidence](docs/IMPLEMENTATION_NOTES.md)
