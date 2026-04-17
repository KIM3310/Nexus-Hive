# Runbook: Schema Evolution Without Breaking Queries

> **Audience**: Data engineers and platform operators updating the governed
> analytics schema that Nexus-Hive reads from.
>
> **Goal**: Add columns, rename tables, deprecate fields, and tighten
> sensitivity labels without breaking the Translator agent or introducing
> policy-engine regressions. Target wall time per change: 30-90 minutes,
> plus a 7-day deprecation window for breaking changes.

## Why this is tricky

Nexus-Hive caches a schema snapshot at startup that the Translator agent
uses to seed LLM prompts. The policy engine reads the same snapshot to
enforce sensitive-column rules. Three things can break:

1. **Translator regresses**: the LLM references a column name that no
   longer exists.
2. **Policy engine misclassifies**: a newly added column containing PII is
   not recognized, so the default `allow` rule leaks data.
3. **Gold eval drops**: evals written against the old schema fail against
   the new one, masking real accuracy regressions.

This runbook is designed to prevent all three.

## The three kinds of schema change

| Change type | Example | Risk | Procedure |
|---|---|---|---|
| **Additive** | Add `customer_segment VARCHAR` | Low | Section A (5 steps, no downtime) |
| **Breaking** | Rename `region` to `region_name` | High | Section B (7 steps, 7-day window) |
| **Sensitivity tightening** | Reclassify `email` from `PII_L2` to `PII_L1` | Medium | Section C (5 steps, no downtime) |

## Section A: Additive change

Adding columns or tables never breaks existing queries; old SELECTs just
ignore the new columns. The only work is making sure the new field is
**visible** to the Translator and **classified** for the policy engine.

### A.1. Stage the warehouse change

In a non-production environment:

```sql
ALTER TABLE sales ADD COLUMN customer_segment VARCHAR(64);
```

Verify the column appears in `information_schema.columns`.

### A.2. Update the governed schema registry

Nexus-Hive reads from `policy/schema_registry.yaml` (or the equivalent DB
table in `seed_db.py`). Add the new column with its sensitivity label:

```yaml
tables:
  sales:
    columns:
      customer_segment:
        type: varchar
        description: "Business segment classification (SMB, Mid, Enterprise)"
        sensitivity: public
        aggregatable: true
```

### A.3. Refresh the in-memory cache

Nexus-Hive refreshes its schema snapshot every 5 minutes by default. To
force an immediate refresh:

```bash
curl -X POST http://localhost:8000/api/schema/refresh \
  -H "Authorization: Bearer $NEXUS_OPERATOR_TOKEN"
```

Expected response:

```json
{"status": "refreshed", "table_count": 4, "column_count": 38}
```

### A.4. Add a gold eval case

In `tests/test_gold_evals.py`, add a case that exercises the new column:

```python
{
  "id": "gold-042-customer-segment",
  "question": "Show net revenue by customer segment in Q4 2025",
  "expected_features": ["customer_segment", "SUM(net_revenue)", "GROUP BY"],
  "policy_verdict_expected": "allow",
},
```

### A.5. Run the gold eval

```bash
curl http://localhost:8000/api/evals/nl2sql-gold/run | jq '.summary'
```

Expected: the new case passes; existing cases unchanged.

Apply in production after the non-prod run is green.

## Section B: Breaking change (rename or drop)

Nexus-Hive follows the **expand-contract** pattern with a **7-day
deprecation window** visible in the audit trail.

### B.1. Expand: add the new name alongside the old

```sql
-- Day 0
ALTER TABLE sales ADD COLUMN region_name VARCHAR(64);
UPDATE sales SET region_name = region;
```

Keep both columns populated for the window. Add a trigger or scheduled
job that copies writes from `region` to `region_name`.

### B.2. Update the governed schema registry (both names)

```yaml
tables:
  sales:
    columns:
      region:
        type: varchar
        sensitivity: public
        deprecated: true
        deprecated_at: "2026-04-16"
        deprecated_use_instead: region_name
      region_name:
        type: varchar
        sensitivity: public
```

### B.3. Update the Translator's preferred hint list

In `graph/nodes.py` the Translator renders a "preferred columns" hint from
the schema registry. Entries marked `deprecated: true` are included with
a `(deprecated, use <new>)` suffix, biasing the LLM toward the new name
without breaking existing queries that still use the old name.

### B.4. Add a policy-engine rewrite (optional)

For very critical renames, the policy engine can automatically rewrite the
SQL before execution. Add a rule in `policy/engine.py`:

```python
SCHEMA_REWRITES = {
    ("sales", "region"): ("sales", "region_name"),
}
```

Queries that use `region` will be rewritten and annotated in the audit
trail as `rewrite_applied`.

### B.5. Broadcast to users

Publish a notice in the operator surface (`GET /api/query-session-board`)
flagging the deprecation. Users and downstream systems have 7 days to
migrate.

### B.6. Contract: drop the old column

After the 7-day window and once the audit trail shows zero queries using
the old name for 72 hours:

```sql
-- Day 7+
ALTER TABLE sales DROP COLUMN region;
```

Remove the deprecated entry from `schema_registry.yaml`.

### B.7. Run the regression suite

```bash
pytest tests/test_policy_engine.py tests/test_agents.py tests/test_gold_evals.py
curl http://localhost:8000/api/evals/nl2sql-gold/run | jq '.summary'
```

Expected: all pre-existing cases still pass with the new column name.

## Section C: Sensitivity tightening

Reclassify a column as more sensitive (e.g., `PII_L2` to `PII_L1`) when
privacy requirements change.

### C.1. Update the registry

```yaml
tables:
  users:
    columns:
      email:
        type: varchar
        sensitivity: pii_l1         # was pii_l2
        mask_default: true
        row_access_policy: by_account
```

### C.2. Refresh

```bash
curl -X POST http://localhost:8000/api/schema/refresh
```

### C.3. Run a dry-run audit

```bash
curl "http://localhost:8000/api/query-audit/recent?limit=500" | \
  jq '.rows[] | select(.sql | contains("email"))' | head
```

Review any recent queries that referenced the newly tightened column.
If those users should no longer see that column, notify them now.

### C.4. Update gold eval expected verdicts

Any gold case that previously asserted `allow` for a query referencing the
tightened column must be updated to `review` or `deny` as appropriate.

### C.5. Test the new sensitivity

```bash
curl -X POST http://localhost:8000/api/policy/check \
  -H 'Content-Type: application/json' \
  -d '{"sql": "SELECT email FROM users WHERE account_id=42", "role": "analyst"}' | jq
```

Expected now: `verdict: "deny"` or `review` with a reason referencing
`pii_l1`.

## Validation after any schema change

Regardless of change type, run:

```bash
# 1. Schema refresh worked
curl http://localhost:8000/api/meta | jq '.schema_version, .schema_updated_at'

# 2. No elevated error rate in last 15 min
curl -s "http://prometheus:9090/api/v1/query?query=nexus_hive:error_rate:5m" | jq

# 3. No degradation in gold eval
curl http://localhost:8000/api/evals/nl2sql-gold/run | jq '.summary.score'

# 4. Audit trail records rewrite_applied events (for renames with rewrite rule)
curl "http://localhost:8000/api/query-audit/recent?limit=20" | jq '.rows[] | select(.rewrite_applied)'
```

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Translator still suggests old column name after rename | Cache not refreshed on all pods | `kubectl -n analytics rollout restart deploy/nexus-hive` |
| Policy engine allows PII query on tightened column | `schema_registry.yaml` update not committed | Verify ConfigMap has the updated content and pod restart captured it |
| Gold eval score drops 10%+ after change | Gold cases reference the dropped column | Update `tests/test_gold_evals.py` to use the new column |
| Audit trail shows `rewrite_applied: false` for renamed column | No rewrite rule defined | Add to `SCHEMA_REWRITES` or accept that users must migrate their queries |

## What NOT to do

- Do not drop a column on the same day you add its replacement. Always use
  the 7-day expand-contract window.
- Do not mass-rewrite historical queries in the audit trail. The audit
  trail is immutable for compliance reasons.
- Do not use `SELECT *` in governed queries; it hides schema drift.
- Do not skip the gold eval after a schema change. The eval is the only
  signal that the Translator still understands the schema.

## Schema change proposal template

When proposing a schema change, fill this template and circulate in
`#analytics-governance` at least 48 hours in advance:

```
Change type: [additive | breaking | sensitivity]
Affected table(s): 
Affected column(s): 
Motivation: 
Expand start: YYYY-MM-DD
Contract target: YYYY-MM-DD (breaking changes only)
Gold-eval cases added: #42, #43
Policy rewrite rule: yes/no
Runbook link: docs/runbooks/schema-evolution.md
```

## See also

- ADR-002 (`docs/adr/002-warehouse-adapter-abstraction.md`) on why the
  adapter interface is stable even as the underlying schema changes.
- `policy/engine.py` for the policy rule definitions.
- `graph/nodes.py` for the Translator prompt rendering.
