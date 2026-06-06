# Review Guide - With live LLM inference via Ollama:

Updated: 2026-05-30

Use this page as the short path through the repository. It keeps the review grounded in the code, docs, commands, and boundaries that are already present.

## Summary

| Field | Notes |
|---|---|
| Lane | B2B governed analytics |
| Core idea | Governed NL-to-SQL with policy checks, audit trail, and warehouse adapter path. |
| Primary reader | Data platform teams, BI owners, and operations leaders who need self-service questions without uncontrolled SQL. |
| Stack | Python, Terraform, Helm, Docker |

## Open First

1. Start with the README fast path and architecture section.
2. Open `docs/service-launch-playbook.md` only when reviewing the product or service angle.
3. Check the commands below before making claims about quality.
4. Skim the CI workflows and fixture data before deeper implementation review.
5. Read the boundaries section before presenting the project externally.

## Checks

| Purpose | Command |
|---|---|
| Full local gate | `make verify` |
| Test suite | `make test` |

## CI

- .github/workflows/architecture-blueprint.yml
- .github/workflows/ci.yml
- .github/workflows/dependency-review.yml
- .github/workflows/repository-health.yml
- .github/workflows/repository-surface.yml
- .github/workflows/secret-scan.yml

## Evidence

- pytest/ruff-style local verification path
- infrastructure-as-code review surface
- Kubernetes packaging surface
- containerized delivery path
- make verify passes
- Seeded question-to-SQL trace is inspectable
- Policy rejection examples are visible

## Commercial Notes

| Possible offer | Working scope assumption |
|---|---|
| Governed analytics cockpit pilot | $5k-$12k discovery + demo |
| Warehouse adapter setup | $15k-$40k implementation |
| Policy template and audit-readiness pack | $2k-$8k/month governance support |

## Boundaries

- Do not run write queries by default
- Live warehouses require scoped credentials
- Human review required for high-risk metrics

## Useful Metrics

- Policy pass/reject clarity
- Analyst time saved
- Audited query coverage
