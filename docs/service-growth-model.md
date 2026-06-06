# Service Growth Model - Nexus-Hive

Updated: 2026-06-06

This note translates the repository into a practical service-growth path. It intentionally avoids public financial assumptions. Use it to improve clarity, trust, activation, and repeatable delivery.

## Model

| Field | Decision |
|---|---|
| Service type | Governed analytics and NL-to-query |
| Primary reader or buyer | Analytics teams needing self-service insight under data-permission controls. |
| Wedge | Warehouse safety review and query approval workflow. |
| Operating note | Keep the first engagement scoped around one workflow, one data boundary, and one acceptance checklist. |

## Service Path

- Proof-first demo or review artifact.
- Discovery around one concrete workflow and its operating boundary.
- Scoped diagnostic or pilot plan with acceptance criteria.
- Implementation support only after the required resources are approved in [service architecture](service-architecture.md).

## Behavioral Design

| Principle | Application |
|---|---|
| Attention and memory | Reduce working-memory load, repeat one primary action, and give immediate feedback after the first user action. |
| Cognitive fluency | Make the first screen answer who it helps, what happens next, and what proof exists. |
| Salience | Show the current workflow pain with one concrete metric, example, or before/after artifact. |
| Trust before persuasion | Expose boundaries, failure modes, and data handling before conversion prompts. |
| Choice architecture | Offer three clear next steps: inspect demo, run locally, or discuss a narrow pilot. |
| Risk reversal | Make the first step time-boxed and tied to acceptance criteria. |
| Authority and proof | Use benchmarks, CI, runbooks, screenshots, and review artifacts. Do not invent logos, users, or traction. |
| Commitment | End demos with a written checklist so the buyer can review the decision internally. |

## Activation Loop

- Traffic source: portfolio, GitHub, direct outreach, or design-partner conversation.
- First action: inspect the proof surface and confirm the workflow is relevant.
- Conversion step: discuss a bounded diagnostic or pilot tied to that lane.
- Expansion: convert the strongest artifact into a repeatable implementation checklist.

## Scope Logic

- Keep financial assumptions private until buyer scope exists.
- Tie the first paid step to acceptance criteria, not broad feature promises.
- Tie delivery scope to one buyer metric that can be verified with approved data.
- Buy backend resources only when the [service architecture](service-architecture.md) says state, storage, jobs, auth, or integrations are needed.

## Experiments

- Replace broad landing copy with one buyer-specific pain statement and measure demo starts.
- Compare a diagnostic CTA with a pilot-readiness CTA while keeping the same success criteria.
- Add a downloadable one-page review artifact and track qualified replies.
- Run targeted outreach that references a specific workflow, not only the repository name.

## Metrics

- Demo starts
- Qualified workflow conversations
- CTA clicks
- Activation completion
- Error rate, latency, and support burden

## Ethical Boundary

- No fake users, fake logos, fake traction, or unverifiable social proof.
- No urgency timers, hidden opt-outs, forced continuity, or confusing terms.
- Conversion prompts must come after value is demonstrated.
- Data collection should be minimal, visible, and tied to product value.
