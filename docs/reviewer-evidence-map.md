# Reviewer Evidence Map - With live LLM inference via Ollama:

Updated: 2026-05-29

This document is the short path for a technical reviewer, engineering leader, product evaluator, or buyer who wants to understand what this repository proves without wandering through every file.

## One-Line Proof

**B2B governed analytics.** Governed NL-to-SQL with policy checks, audit trail, and warehouse adapter path.

## Audience and Commercial Angle

| Lens | Answer |
|---|---|
| Primary reviewer | Data platform teams, BI owners, and operations leaders who need self-service questions without uncontrolled SQL. |
| Technical signal | Can the project be explained, verified, bounded, and extended like a real product surface? |
| Buyer signal | Is there a narrow operational pain, a runnable proof path, and a risk-aware pilot shape? |
| Stack signal | Python, Terraform, Helm, Docker |

## Seven-Minute Review Route

1. Read the README `Product and Review Surface` and `Reviewer Fast Path` sections.
2. Open `docs/monetization-playbook.md` to understand the buyer, offer ladder, and GTM hypothesis.
3. Run or inspect the strongest local quality gate below.
4. Inspect CI workflow definitions and test fixtures before deeper implementation review.
5. Check the risk boundaries so claims stay credible and not overextended.

## Verification Commands

| Purpose | Command |
|---|---|
| Full local gate | `make verify` |
| Test suite | `make test` |

## CI and Automation Surface

- .github/workflows/architecture-blueprint.yml
- .github/workflows/ci.yml
- .github/workflows/dependency-review.yml
- .github/workflows/repository-health.yml
- .github/workflows/repository-surface.yml
- .github/workflows/secret-scan.yml

## Evidence Inventory

- pytest/ruff-style local verification path
- infrastructure-as-code review surface
- Kubernetes packaging surface
- containerized delivery path
- make verify passes
- Seeded question-to-SQL trace is inspectable
- Policy rejection examples are visible

## Commercialization Snapshot

| Offer | Pricing hypothesis |
|---|---|
| Governed analytics cockpit pilot | $5k-$12k discovery + demo |
| Warehouse adapter setup | $15k-$40k implementation |
| Policy template and audit-readiness pack | $2k-$8k/month governance support |

## Risk Boundaries

- Do not run write queries by default
- Live warehouses require scoped credentials
- Human review required for high-risk metrics

## Metrics That Matter

- Policy pass/reject clarity
- Analyst time saved
- Audited query coverage

## Review Verdict

This repository should be evaluated as part of the broader KIM3310 portfolio: it is strongest when the reviewer sees the link between a concrete implementation, a documented verification path, and an externally credible operating story.
