# Nexus-Hive: design and evidence

Updated 2026-09-07.

## Design decision

SQL is parsed before execution so statement type and column access can be checked against policy. A denied or review-required query stops at the execution boundary.

## Inspect the code

- [policy/engine.py](../policy/engine.py): SQL policy evaluation.
- [tests/test_sql_policy_boundaries.py](../tests/test_sql_policy_boundaries.py): Execution boundary regressions.

## Scope of the evidence

The local demonstration uses SQLite. Application policy complements database permissions; it does not replace them or prove arbitrary generated SQL safe.

## Contribution and provenance

These notes describe what can be inspected in the repository. Commit history and pull-request diffs preserve the change trail; they do not independently establish manual versus AI-assisted authorship, team roles or contribution percentages. No such percentages are inferred here.

[Project overview](../README.md)
