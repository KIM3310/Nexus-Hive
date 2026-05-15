# ADR 007: Maintain Customer Stories In-Repo

## Status

Accepted

## Date

2026-04-16

## Context

Nexus-Hive is a product that sells on governance and operational maturity,
not pure feature velocity. The engineers who build it and the solutions
engineers who demo it need a shared narrative about *how customers
actually use it*, beyond what the API reference can convey.

Historically we kept this material in three disparate places:

1. **Google Docs per customer**, owned by the SE team.
2. **Internal Confluence** pages summarizing completed engagements.
3. **Slack threads** in customer-specific channels, essentially
   ephemeral.

Three problems emerged:

- **Engineering isolation.** The product team rarely read the customer
  narratives. Design decisions drifted from the patterns SEs were
  actually fielding questions about.
- **Inconsistent voice and framing.** Each SE wrote their case study in
  their own style. Hand-offs to new SEs required reading 8 different
  templates to absorb the playbook.
- **Out of date material.** Customer stories that referenced `phi3:3.8b`
  stayed in that state long after customers had migrated to Claude; new
  SEs cited stale numbers in live demos.

Meanwhile, SEs joining the team needed a place to learn the *tacit
knowledge* of the sales engineering practice: who the privacy officer
is in a regulated-healthcare deal, how to tune the policy profile in
week 4, which numbers to lead with. None of that was in the code or the
API docs.

We evaluated whether to formalize customer stories as a product artifact
maintained in-repo.

## Options considered

### Option A: Keep customer stories out of the repo

The status quo. Each story lives wherever the SE writes it.

Pros:

- Zero change required.
- Keeps engineering-facing docs focused.
- Allows raw, unvarnished customer detail that would be uncomfortable in
  a public repo.

Cons:

- Engineering never reads them. Design feedback loop is broken.
- SE onboarding is an apprenticeship, not a documented process.
- When a customer story is cited externally (in a conference talk, a
  blog post, a partner conversation), there is no single version of the
  truth.

### Option B: Keep stories in a separate private repo

A `nexus-hive-customer-stories` repo, engineering-access only.

Pros:

- Separation of concerns: product-facing repo stays lean.
- Private-by-default, so real customer details can be included.

Cons:

- Two repos to stay in sync.
- Engineers still have to context-switch to another repo to see the
  customer view.
- Contributors who are not on the engineering team (SEs, product
  marketing) need separate access governance.
- Doubles the surface area for merge conflicts when a design change
  affects both code and narrative.

### Option C: Maintain sanitized customer stories in the main repo

Fictional composites derived from real engagements. Numbers, names,
schemas fabricated but reflecting real patterns. Stored at
`docs/customer-stories/`.

Pros:

- Engineering and SE teams read the same narratives.
- Narratives travel with the code: a schema change in
  `policy/engine.py` can be accompanied by a story update.
- New SEs and new engineers onboard against the same artifacts.
- Stories are safe to share externally (conference talks, public
  presentations) without redaction.
- Narratives serve as **product requirements documents in disguise**:
  when we describe what Acme needed, we are also describing the product
  specification for that feature.

Cons:

- "Composite customer" risks are real: if stories feel fabricated, they
  lose credibility with prospective customers.
- Maintenance burden: stories go stale as the product evolves.
- Fabricated numbers must be plausible and labeled as illustrative.
- Committing to a public narrative format creates an expectation of
  quality we have to sustain.

### Option D: Link the customer stories from product docs but host them elsewhere

Hybrid: repo points at a published case-study website.

Pros:

- Marketing owns the "production-quality" version.
- Engineering doesn't have to maintain prose.

Cons:

- Stories drift further from the code than Option C because the
  publication toolchain is different.
- Marketing-team-owned content has a different review tempo than the
  engineering release cycle.

## Decision

We chose **Option C: maintain composite customer stories in the main
repo at `docs/customer-stories/`.**

Guardrails:

1. **Explicitly label as composites.** Every story opens with a
   disclaimer that it is a fictional composite drawing on common
   patterns.

2. **Realistic but illustrative numbers.** Numbers are plausible for the
   described deployment shape but clearly "round" rather than
   spuriously precise.

3. **Two story slots at launch.** `acme-finance-narrative.md` covers a
   standard financial-services deployment. `regulated-healthcare-
   narrative.md` covers airgap + HIPAA. Additional stories added only
   when an engagement shape is meaningfully new.

4. **SE + engineering review before merge.** Every update goes through
   both an SE-owner review (for narrative accuracy) and an engineering
   review (for technical accuracy).

5. **Ownership sits with the SE owner.** Engineering can suggest
   changes but the SE owner approves.

## Consequences

### Benefits

- **Engineering reads the customer view.** Weekly triage now routinely
  references story-level statements like "Acme's FinOps team will want
  `QUERY_TAG` preserved here." Design feedback loop is tighter.

- **SE onboarding is a real docset.** A new SE can read the two
  narratives, the discovery guide, and the runbooks, and walk into
  their first discovery call with 80% of the playbook already absorbed.

- **Product and narrative evolve together.** When we shipped
  `state_restricted` as a sensitivity tier, the update landed in the
  Northstar narrative in the same PR. Readers can see the product
  change and the narrative justification in one place.

- **External use is safe.** Because the stories are already
  composites, we can share them at conferences or in blog posts without
  a legal review cycle per story.

- **Shared vocabulary with prospective customers.** Prospects reading
  the repo during pre-purchase due diligence get a consistent message
  about deployment realism. Several early prospects have cited the
  stories as "the first thing that convinced us you know what you're
  doing."

### Tradeoffs

- **Composite credibility risk.** If a reader decides the stories are
  too polished to be real, we lose trust. We mitigate by keeping
  numbers plausible, citing the disclaimer, and letting SEs share
  redacted real data in 1:1 conversations when asked.

- **Maintenance burden.** Stories will go stale if not updated with
  product changes. We address this by:
  - Adding a checklist item to the release template: "Does this
    change invalidate anything in `docs/customer-stories/`?"
  - Reviewing the stories quarterly with the SE lead.

- **Narrative voice divergence.** Different contributors will write in
  different styles. A shared template and tone guide minimizes this;
  the SE lead harmonizes during review.

- **Length cost.** Each story is 500-800 lines. The repo grows. We
  accept this because the stories are load-bearing artifacts for the
  SE team and earn their keep.

### Boundaries

Customer stories:

- **Are not** marketing copy. No sales hyperbole. No unqualified
  superlatives. No screenshots.
- **Are not** private customer data. Even if based on a real
  engagement, all identifiable information is removed.
- **Are not** a replacement for runbooks. They narrate the engagement
  arc, but operational detail lives in `docs/runbooks/`.
- **Are not** a replacement for ADRs. Why-decisions live in ADRs. The
  stories illustrate consequences.

## Alternatives reconsidered post-decision

- **Per-vertical story series:** e.g., healthcare 1, healthcare 2,
  healthcare 3. Rejected for now. Adds maintenance cost without
  proportional benefit until we have multiple live customers in a
  vertical.

- **Video walkthroughs alongside the prose:** rejected. Video goes
  stale even faster than prose and is harder to diff.

- **Publish the stories to a standalone static site:** attractive if we
  want SEO and marketing polish, but rejected for now because it splits
  the maintenance target. Revisit when we hire dedicated docs staff.

## References

- `docs/customer-stories/acme-finance-narrative.md`
- `docs/customer-stories/regulated-healthcare-narrative.md`
- `docs/discovery-guide.md` - the discovery script the stories
  illustrate
- `docs/executive-one-pager.md` - the five-bullet version of the
  narratives for time-constrained readers
- ADR-001 (multi-agent pipeline) - the design decision that makes the
  policy-engine demo in these stories possible
