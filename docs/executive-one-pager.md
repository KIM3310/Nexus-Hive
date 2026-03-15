# Nexus-Hive Executive One-Pager

## Problem

Executives want self-service analytics, but most NL2SQL demos skip the audit, policy, and governance steps that matter in real environments.

## What Nexus-Hive changes

- adds policy preview before execution
- keeps query audit and evals first-class
- gives reviewers a governed path from question to SQL to chart

## Buyer value

- faster analyst iteration with lower governance risk
- clearer proof that self-service analytics is controllable
- auditability for reviewers and data owners

## Key metrics

- eval pass rate on gold questions
- deny/review ratio for policy checks
- fallback rate
- time from question to reviewed answer

## Rollout

1. review-only governed demo
2. pilot with one warehouse and one analyst group
3. broader rollout with role-aware policies and warehouse adapters

## Best proof path

- `/api/runtime/warehouse-brief`
- `/api/query-audit/summary`
- `/api/evals/nl2sql-gold/run`
- `/api/policy/check`
- `docs/solution-architecture.md`
