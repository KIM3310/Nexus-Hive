# Big-Tech Elevation Plan

## Hiring Thesis

Turn `Nexus-Hive` into a canonical `governed analytics runtime` proof. The hiring story should be: this repo does not just generate SQL, it makes warehouse-adjacent AI safe to review, approve, and operate.

## 30 / 60 / 90

### 30 days
- Add a semantic metric layer that separates business definitions from generated SQL.
- Add a warehouse adapter boundary so SQLite demo mode and warehouse-backed mode share one review contract.
- Add a request-level approval queue that isolates review-required SQL before execution.

### 60 days
- Add a lineage browser for facts, dimensions, and policy-sensitive fields.
- Add a gold eval pack with semantic-equivalence checks, not just literal SQL comparisons.
- Add role-aware denial and approval cases with explicit query-policy explanations.

### 90 days
- Add a warehouse scorecard that compares local demo, adapter-backed warehouse, and fallback modes.
- Add a case study showing a rejected query, a revised approved query, and the resulting audited answer.
- Add operational drill flows for stale data, policy breach, and adapter failure.

## Proof Surfaces To Add

- `GET /api/schema/metrics`
- `GET /api/query-approval-board`
- `GET /api/lineage-browser`
- `GET /api/evals/semantic-sql`

## Success Bar

- A reviewer can explain why the answer is trustworthy before discussing chart polish.
- Approval-safe analytics is visible as a system, not a prompt trick.
- The repo maps cleanly to Snowflake, Databricks, and governed BI interviews.
