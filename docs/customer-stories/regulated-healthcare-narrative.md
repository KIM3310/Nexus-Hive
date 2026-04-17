# Customer Story: Regulated Healthcare - "Northstar Health Systems"

> **Customer**: Northstar Health Systems (fictional composite)
> **Industry**: US regional integrated health delivery network (IDN)
> **Size**: 14 hospitals, 210 outpatient clinics, ~28,000 employees
> **Stack**: Databricks on Azure (HIPAA-compliant workspace), dbt,
> Tableau, Epic EHR extracts via nightly batch
> **Engagement**: 180-day HIPAA-ready adoption, airgap deployment,
> analyst and population-health enablement
> **Disclaimer**: Composite narrative drawn from common patterns in
> HIPAA-regulated healthcare analytics. Numbers are illustrative, not
> tied to any specific customer.

---

## Why healthcare is hard

Healthcare analytics is not a "productivity" story; it is a **risk
management** story. At Northstar, the analytics org operates under four
overlapping constraints:

1. **HIPAA Privacy Rule** - 18 categories of identifiers must be masked
   or suppressed for anyone without a documented minimum-necessary basis
   to see them.
2. **Minimum Necessary Rule** - access is scoped to exactly the data
   required for the user's stated purpose.
3. **BAA obligations** - every vendor touching PHI signs a Business
   Associate Agreement. Tools that cannot sign one are non-starters.
4. **State law overlays** - Northstar operates across three states, each
   with its own breach-notification and sensitive-category rules
   (mental health in State A, substance abuse in State B, etc.).

Their pre-Nexus-Hive analytics workflow reflected these constraints:

- 90% of analytical questions routed to a central analytics team of 24
  people.
- Average turnaround: **9 business days** for bespoke requests, due to a
  mandatory PHI review step performed by the privacy officer on all
  queries touching identifiable data.
- Four full-time analysts did nothing but **manual de-identification**
  of data extracts before those extracts left the warehouse for
  downstream reporting.
- Their previous NL-to-SQL trial (not us) was discontinued after 6
  weeks when it emitted a query containing MRN (medical record number)
  in a chart legend on a meeting display. No actual breach, but the
  incident drove a hard policy: no LLM-generated SQL in any form until
  a defensible privacy-enforcement layer existed.

The VP of Data, Dr. Alan Park, told us in kickoff: "We cannot trade
privacy for speed. But we are drowning. If you can give us both, we
will give you our trust. If you give us one without the other, we
cannot move forward."

## Why Nexus-Hive was a fit

Four features made Nexus-Hive the first tool Northstar's privacy
officer endorsed in writing:

1. **Per-column sensitivity labeling** with enforceable rules. PHI
   columns (MRN, DOB, address, etc.) could be labeled `phi_l1` and
   denied at the policy-engine layer before the SQL ever reached the
   warehouse.

2. **Row access policy integration** with their Databricks workspace.
   The adapter respects Unity Catalog row filters, so a user's LLM-
   generated query is transparently scoped to the records they are
   already entitled to see.

3. **Audit trail suitable for HIPAA accounting of disclosures**. Every
   query - allowed, denied, reviewed - is logged with request ID,
   user, role, tables accessed, columns accessed, policy verdict, and
   timestamp. The privacy officer can export a filtered audit for any
   patient ID and produce a HIPAA-compliant disclosure log.

4. **Air-gapped deployment with local LLM**. Northstar's legal team
   rejected the idea of PHI (even question metadata that might reveal
   a patient) leaving the Azure HIPAA-compliant boundary. Our Ollama
   sidecar option kept all inference inside the BAA-covered workspace.

## The 180-day adoption timeline

### Phase 1: Privacy architecture review (days 1-45)

This phase is unique to regulated healthcare. We did not touch any
infrastructure until the privacy review was complete.

**Days 1-15: Data inventory and labeling.**

- 3 working sessions with Northstar's privacy officer and a clinical
  data steward.
- Classified all 427 columns in the pilot schemas into sensitivity
  tiers: `public` (aggregates only), `internal`, `phi_l2` (indirect
  identifiers), `phi_l1` (direct identifiers), and `state_restricted`
  (mental health, substance abuse, HIV status).
- Populated `policy/schema_registry.yaml` with the classifications.

**Days 16-30: Rule design.**

- Drafted 23 policy rules mapped from Northstar's internal privacy
  handbook. Examples:
  - Any `SELECT *` on a table containing a `phi_l1` column is `deny`.
  - `phi_l2` columns require aggregation of at least 10 records before
    `allow`. Otherwise `review`.
  - `state_restricted` data follows a row-access policy derived from
    the user's state-of-employment attribute in OKTA.
  - Write ops of any kind are `deny` on PHI-containing tables.
- Privacy officer signed off on the rule set after 2 review cycles.

**Days 31-45: HIPAA documentation.**

- Wrote a **Privacy Impact Assessment** (PIA) appendix documenting:
  - Data types touched by Nexus-Hive
  - Workflow for each `deny` / `review` / `allow` case
  - Audit-trail retention policy (7 years per Northstar's HIPAA policy)
  - Incident response path for a suspected breach
- Privacy officer and CISO co-signed the PIA.
- Northstar's legal team signed a BAA with us.

No software had been deployed yet. This is normal for healthcare.

### Phase 2: Airgap deployment (days 46-60)

**Days 46-52: Internal registry mirroring.**

- Followed `docs/runbooks/airgap-deploy.md` exactly.
- Mirrored images into their Azure Container Registry.
- Mirrored Ollama `phi3` weights into an internal blob store.

**Days 53-60: Helm install + wiring.**

- Deployed to a dedicated AKS cluster inside their HIPAA workspace.
- Used `helm/nexus-hive/values-airgap.yaml` with 5 overrides for
  Northstar's specific registry, PKI, and ExternalSecrets configuration.
- Actual deployment wall time: 3 hours 12 minutes for their senior
  SRE, longer than the runbook's 3-hour target due to a one-time
  certificate trust-chain fix in their AKS nodes.
- Ollama sidecar with `phi3:3.8b` ran at p99 ~3100ms on CPU nodes,
  well within their 5-second SLO.

### Phase 3: Pilot with strict audit (days 61-90)

**Days 61-67: Soft launch to 8 users.**

- Users: 4 analysts in population health, 2 finance reviewers, 1
  quality & safety analyst, 1 clinical research associate.
- First 3 days: 42 questions, 43% `allow`, 38% `review`, 19% `deny`.
- The high `review` rate was expected; we had deliberately erred on
  the side of caution during rule design.
- Every `review` was adjudicated by the privacy officer in a
  next-day queue. Her verdicts were logged in the audit trail as
  training signal.

**Days 68-80: Rule refinement and expansion.**

- After 12 days and 380 questions, 7 rules were refined:
  - The "10-record minimum aggregation" rule was too coarse for
    population-health reporting on rare conditions. Relaxed to 5
    records when the query included `diagnosis_group` dimension.
  - The wildcard-on-PHI rule stood without changes.
  - State-restricted row access was working end-to-end: a user in
    State A ran a query that would have surfaced State B substance-
    abuse data and was correctly blocked.
- Pilot expanded to 30 users.

**Days 81-90: Incident drill.**

- On day 84, at the privacy officer's request, we ran a tabletop
  exercise simulating a suspected breach. The question asked:
  "If a user managed to extract a patient list, can we prove it
  within 4 hours?"
- Using the audit trail, we reconstructed the hypothetical user's
  entire query history in 38 minutes, filtered to queries touching
  the tables in question, and produced a report suitable for the
  breach notification team.
- The privacy officer signed off on the pilot as suitable for
  production expansion.

### Phase 4: Production scale-out (days 91-150)

**Days 91-110: Expand to 150 users across 5 departments.**

- Each department had a 90-minute enablement session including a 15-
  minute privacy refresher.
- User cohort now includes finance, population health, quality &
  safety, clinical operations, research (non-IRB), and supply chain.
- Added a second row-access policy: attending physicians can only see
  aggregated data for patients not in their care panel, full detail
  for those in their panel. This feature took 5 days to implement
  end-to-end using the Databricks adapter's row-filter hook.

**Days 111-130: Second incident drill + first real event.**

- On day 117, a real incident: a new user attempted to extract the
  MRN column in a population-health query, despite training. The
  policy engine denied it. The user followed up with the analytics
  team and learned the legitimate way to answer the question using
  `patient_cohort_id` (a de-identified pseudonym).
- No PHI exposure. The episode was written up as a training case
  study and added to onboarding.

**Days 131-150: Full production readiness.**

- HPA tuned to min 4 / max 12 replicas.
- Deployed second Nexus-Hive instance in Northstar's Azure South
  Central region as the DR target.
- Integrated the audit trail export with their existing SIEM.

### Phase 5: Clinical research expansion (days 151-180)

This was a delightful surprise to both teams. A clinical research
coordinator, after seeing Nexus-Hive in action, asked if it could be
used in IRB-approved research cohorts.

- Configured a new policy profile `clinical_research` that enabled
  identified queries for users with documented IRB approval attached
  to their OKTA attributes.
- Deployed as a separate release via `helm upgrade --install
  nexus-hive-research ...` with a distinct namespace and its own
  policy profile.
- By day 180, 4 IRB-approved research groups were using it, cutting
  their cohort-identification query turnaround from **3 weeks to 4
  hours**.

## Before-and-after metrics

| Metric | Before Nexus-Hive | After 180 days | Change |
|---|---|---|---|
| Bespoke analytical request turnaround | 9 business days | 1 business day | -89% |
| Central analytics team backlog | 180+ open | 40-60 open | -70% |
| Analyst FTEs on manual de-identification | 4 | 1 | -75% |
| PHI exposure incidents | 1 near-miss in prior 12mo | 0 | -100% |
| Queries touching identifiable data | 100% (manually reviewed) | 8% (all audited) | -92% |
| Gold-eval score (healthcare schema) | - | 0.87 | baseline |
| Audit-trail completeness for HIPAA disclosures | ~65% (manual) | 100% (automated) | +35pp |
| Databricks cost per answered question | $2.40 | $1.15 | -52% |
| p95 query latency (airgap Ollama) | - | 2.8s | within SLO |
| IRB research cohort turnaround | 3 weeks | 4 hours | -96% |

The 92% reduction in direct-PHI queries is notable: most questions can
be answered with aggregates + pseudonyms, once the tool makes that path
easy. Previously, it was easier to ask for identified data than to
construct an aggregate query by hand.

## Key design decisions specific to healthcare

**1. Policy rules encoded from the privacy handbook, not the other way around.**

We treated Northstar's existing privacy policies as the source of
truth. Our job was to translate them into enforceable rules. This was
slower than showing up with a default rule set, but it produced
buy-in from legal and the privacy officer in a way that no feature
demo could match.

**2. Row-access policy integration at the adapter, not the LLM.**

It would have been easier to have the LLM "remember" which patients a
user could see. We did not. Row access lives in the Databricks
adapter layer and is enforced by Unity Catalog. The LLM never gets to
decide what is visible - it only generates SQL, which is then scoped
by row filters that are immutable from the LLM's perspective. This
was critical for the privacy officer's sign-off.

**3. Airgap from day one.**

No API calls to anything outside the HIPAA workspace. Ollama on CPU
is slower than Claude on the cloud, but the privacy argument was
decisive. The p95 latency of 2.8 seconds was a tradeoff Northstar
was happy to make.

**4. The privacy officer in every major review.**

At each 30-day checkpoint, the privacy officer sat in a 45-minute
review meeting. She had veto authority. This was scary to product
velocity at first but turned out to be the biggest trust-building
asset in the engagement. By day 180, she was one of our
strongest advocates internally.

## What we shipped back into the product

Northstar's engagement produced four upstream changes to Nexus-Hive:

1. **`state_restricted` sensitivity tier** with composite row-access
   policies derived from user attributes.
2. **IRB / research policy profile** as a shipped example in
   `policy/profiles/clinical_research.yaml`.
3. **HIPAA disclosure audit export** CLI that filters the audit trail
   by patient identifier and formats it for HIPAA Rule 45 CFR 164.528.
4. **Pseudonym-first suggested queries** on `deny` responses - when a
   user asks for identified data, Nexus-Hive suggests the equivalent
   query using `patient_cohort_id`.

## Lessons we learned with Northstar

**1. The privacy officer is the product manager.**

We initially viewed the privacy officer as a compliance check. She
turned out to be our best product partner. Her feedback drove 3 of the
4 upstream product changes. Future healthcare engagements should
include the privacy officer in all design reviews from day one.

**2. Deny rates of 15-20% are a sign of health, not failure.**

In SaaS analytics we optimize to reduce `deny` rates. In healthcare
`deny` is the product. The metric we tracked instead was "percentage
of `deny` responses that resulted in the user finding a legitimate
de-identified path to their answer." We hit 94% on that metric.

**3. Airgap is a selling point, not a limitation.**

Competing vendors highlighted cloud-native inference as a feature.
Northstar saw cloud inference as a disqualifier. For regulated
industries, framing airgap as a "feature" rather than a "workaround"
shifted the sales conversation in our favor.

**4. The audit trail sells itself.**

Showing the privacy officer how to reconstruct a 6-month query history
for a specific patient in under 40 seconds was the single most
persuasive moment of the engagement. Sales engineers going into
healthcare should lead with this demo.

**5. 180 days is the right cadence.**

Initial expectations at Northstar were 90 days. The privacy-first
phase (days 1-45) had no flexibility. Compressing it would have
produced a weaker PIA and a less durable rollout. Future engagements
should set the 180-day expectation upfront.

## References and handoff material

- **Privacy Impact Assessment** (Northstar-internal, signed by privacy
  officer + CISO)
- **Business Associate Agreement** (on file)
- **Configuration files**: `helm/nexus-hive/values-airgap.yaml` with 5
  overrides; 23 policy rules in `policy/profiles/northstar_hipaa.yaml`;
  row-access hooks in `databricks_adapter.py` (extension point)
- **HIPAA Audit export CLI**: shipped as `cli/audit_hipaa_export.py`
- **Follow-up engagements**: quarterly governance review, second-year
  expansion planning (clinical operations and revenue cycle), research
  analytics agent for bioinformatics pilots

## Notes for a solutions engineer using this story

When telling this narrative to a prospective healthcare customer:

1. **Lead with the privacy-first phase.** Healthcare customers need to
   hear that you expect 45 days of paperwork before any code ships.
   Trying to accelerate that phase is what kills deals.
2. **Quote the 96% IRB turnaround reduction** as the headline number.
   Clinical research is the department with the most growth potential
   and the most internal pull.
3. **Show the audit reconstruction demo** within the first 15 minutes
   of any technical call. It is the trust moment.
4. **Promise nothing about PHI de-identification**; de-identification
   is the customer's responsibility under HIPAA, and our tool enforces
   *their* rules. Be careful with the phrase "HIPAA-compliant" - tools
   are not HIPAA-compliant, systems of use are.
5. **Do NOT promise cost savings**. They are a bonus. The sale is
   about risk reduction and time-to-answer.

For the full airgap deployment story, see
`docs/runbooks/airgap-deploy.md`. For the sensitivity tiering
decisions, see `docs/adr/002-warehouse-adapter-abstraction.md` and
`docs/runbooks/schema-evolution.md`.
