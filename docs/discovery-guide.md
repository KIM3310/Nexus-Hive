# Nexus-Hive Discovery Guide

## Best-fit signals

- teams want self-service analytics but do not trust free-form SQL generation
- data owners need audit and policy controls before rollout
- buyers want measurable proof instead of a chart-only demo

## Discovery questions

1. Which analyst workflows are blocked by governance, not by dashboards?
2. What must be reviewed before a generated query can be trusted?
3. Which roles need policy preview versus full execution access?
4. What fallback behavior is acceptable when the live model path degrades?
5. Which questions belong in the first gold eval set?

## Demo path

1. show `/api/runtime/warehouse-brief`
2. run `/api/policy/check`
3. run `/api/evals/nl2sql-gold/run`
4. ask one governed question
5. inspect `/api/query-audit/{request_id}`

## Success criteria

- buyer sees audit and policy before chart output
- eval path is deterministic
- fallback behavior is explicit
- rollout story is clear for both analysts and reviewers

## Follow-up artifacts

- `docs/solution-architecture.md`
- `docs/executive-one-pager.md`
