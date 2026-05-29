# Quality Gate - With live LLM inference via Ollama:

Updated: 2026-05-29

This gate keeps the repository presentation credible: the project should be easy to review, runnable where possible, explicit about secrets, and honest about production boundaries.

## Runtime Profile

| Field | Value |
|---|---|
| Repository | `Nexus-Hive` |
| Primary stack | Python, Terraform, Helm, Docker |
| Default expectation | Local review should work without customer data or production credentials. |

## Local Checks

| Purpose | Command |
|---|---|
| Full local gate | `make verify` |
| Test suite | `make test` |

## CI Surface

- .github/workflows/architecture-blueprint.yml
- .github/workflows/ci.yml
- .github/workflows/dependency-review.yml
- .github/workflows/repository-health.yml
- .github/workflows/repository-surface.yml
- .github/workflows/secret-scan.yml

## Release Boundary

- Demo, fixture, and synthetic-data modes must stay clearly labeled.
- Provider keys, tenant credentials, warehouse secrets, medical data, financial data, or customer logs must never be committed.
- Production claims require environment-specific validation, monitoring, rollback, and human approval paths.
- Screenshots, videos, and README claims should match the current implementation and documented commands.

## Reviewer Checklist

- README explains the user, the pain, the safety boundary, and the fast proof path.
- `docs/monetization-playbook.md` explains how the repository could become a product, pilot, service, or paid proof-of-value.
- Tests or smoke checks are documented even when optional infrastructure is unavailable.
- Failure modes and unsupported claims are visible before the project is presented externally.

## Final Presentation Standard

Green means more than "the code runs." Green means a serious reviewer can understand the problem, trust the boundaries, reproduce the proof path, and see why this work belongs in a portfolio or sales conversation.
