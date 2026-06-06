# Quality Notes - With live LLM inference via Ollama:

Updated: 2026-05-30

These notes keep the repository easy to review without overstating what is production-ready.

## Profile

| Field | Value |
|---|---|
| Repository | `Nexus-Hive` |
| Primary stack | Python, Terraform, Helm, Docker |
| Review expectation | Local review should not require customer data or production credentials. |

## Commands

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

## Boundaries

- Demo, fixture, and synthetic-data modes must stay clearly labeled.
- Provider keys, tenant credentials, warehouse secrets, medical data, financial data, or customer logs must never be committed.
- Production claims require environment-specific validation, monitoring, rollback, and human approval paths.
- Screenshots, videos, and README claims should match the current implementation and documented commands.

## Before Presenting

- README explains the user, the pain, the safety boundary, and the fast proof path.
- `docs/service-launch-playbook.md` explains the product, pilot, service, or paid proof-of-value angle when relevant.
- Tests or smoke checks are documented even when optional infrastructure is unavailable.
- Failure modes and unsupported claims are visible before the project is presented externally.
