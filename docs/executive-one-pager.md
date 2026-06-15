# Nexus-Hive Executive One-Pager

## Problem

Executives want self-service analytics, but most NL2SQL demos skip the audit, policy, and governance steps that matter in real environments.

## What Nexus-Hive changes

- adds policy preview before execution
- keeps query audit and evals first-class
- gives technical readers a governed path from question to SQL to chart

## Technical reader value

- faster analyst iteration with lower governance risk
- clearer proof that self-service analytics is controllable
- auditability for technical readers and data owners

## Key metrics

- eval pass rate on gold questions
- deny/architecture ratio for policy checks
- fallback rate
- time from question to governed answer

## Rollout

1. architecture-only governed demo
2. pilot with one warehouse and one analyst group
3. broader rollout with role-aware policies and warehouse adapters

## Best walkthrough path

- `/api/runtime/warehouse-brief`
- `/api/query-audit/summary`
- `/api/evals/nl2sql-gold/run`
- `/api/policy/check`
- `docs/solution-architecture.md`
