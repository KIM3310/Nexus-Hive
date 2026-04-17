# Customer Story: Acme Finance

> **Customer**: Acme Finance (fictional composite)
> **Industry**: Financial services - wealth management and advisory
> **Size**: 500-person analytics and data organization, 4,200-person firm
> **Stack**: Snowflake on AWS, dbt, Looker, Airflow, OKTA SSO
> **Engagement**: 90-day adoption, self-serve analytics enablement
> **Disclaimer**: Composite narrative drawn from common patterns in the
> financial services analytics space. Numbers are illustrative, not tied
> to any specific customer.

---

## The problem Acme came to us with

Acme Finance's analytics organization had reached a familiar breaking
point. By the end of 2025, their centralized analytics team - 40 SQL-
writing analysts, 12 analytics engineers, and 8 BI developers - was the
bottleneck for a 500-person consumer of dashboards across the firm.

Every new metric, every slicing, every "can we see this by advisor tier"
request fed into a queue. The queue grew faster than the team.

The numbers as they first described them to us:

- Average dashboard creation time: **3 business days** from intake to
  delivery.
- Backlog at any given moment: **220+ open requests**.
- Analyst time spent on self-serve support questions: **35%** of their
  week, per anonymous survey.
- BI developer turnover: **22% annually**, versus 11% for the rest of
  engineering.
- Unique SQL files in the internal dbt repo: **7,400**, with 38% flagged
  as stale or duplicated by their dbt metrics layer audit.
- Customer-facing sales team's top complaint: "I asked a question in
  February and got an answer in April."

Their VP of Analytics, Marta Ruiz, described the situation in our
discovery call: "We've hired our way out of this twice. It works for six
months, then the backlog catches back up. We need a different shape of
solution, not a bigger team."

Acme had already tried two SaaS NL-to-SQL tools before us. The first
generated confident-but-wrong SQL that an auditor caught in a compliance
review. The second required all queries to run through a single shared
Snowflake warehouse, spiking their costs and producing `QUERY_TAG` noise
their cost-attribution team could not unscramble. Both were shelved
within 90 days.

## What made Nexus-Hive land where others failed

Two features closed the conversation during our first technical deep-dive:

1. **Policy engine between generation and execution.** The auditor who
   had killed their previous tool was invited to the second demo. When
   she saw the `deny` / `review` / `allow` decision surfacing before
   execution, with the reason spelled out and the rule ID logged, she
   moved from skeptical to supportive inside 20 minutes.

2. **Query tagging that preserved their cost-attribution model.** Acme
   tags every Snowflake query with `team`, `cost_center`, `data_domain`.
   Nexus-Hive's query-tag generator slotted cleanly into their existing
   tag schema, without forcing them to add a new dimension.

These two features matter because they meant the existing governance
and FinOps investments Acme had made over three years did not have to
be renegotiated.

## The 90-day adoption timeline

### Days 0 to 15: Kick-off and environment prep

**Week 1: Discovery and technical alignment.**

- Four working sessions with Acme engineering covering: policy profiles,
  query-tag mappings, warehouse role model, audit-trail retention, and
  operator handoff to their on-call rotation.
- Signed a scoped pilot: two business domains (`retail_wealth` and
  `advisor_productivity`), 25 designated pilot users, 6 weeks of
  read-only usage, success defined as >=50 sessions by end of pilot.

**Week 2: Environment provisioning.**

- Stood up Nexus-Hive 0.2.0 on Acme's GKE cluster using the Helm chart
  with `values-prod.yaml` overrides. Actual deployment wall time: 74
  minutes for one of their SREs, using the `production-deploy.md`
  runbook.
- Provisioned a dedicated Snowflake role (`NEXUS_HIVE_APP`) with
  SELECT-only grants on the two pilot domains.
- Integrated with Acme's OKTA IdP for SSO; RBAC roles mapped to their
  existing `analyst`, `senior_analyst`, and `operator` groups.
- Wired up their Prometheus + Grafana for metrics, Loki for logs.

### Days 16 to 35: Pilot launch and first feedback loop

**Week 3: Soft launch.**

- 25 pilot users onboarded with a 45-minute enablement session. A 6-page
  cheat sheet covered the question-asking idioms that worked well and
  the ones that routed to `review` (write ops, cross-joins, wildcard
  selects).
- First week saw 118 questions asked, with a 71% `allow` rate, 19%
  `review`, 10% `deny`. The `deny` bucket was dominated by users
  attempting `SELECT *` on `advisor_clients` - a table with PII columns.

**Week 4: First policy tuning.**

- The `review` rate was higher than Acme wanted for a smooth user
  experience, and the data governance officer wanted to relax a few
  over-strict rules without compromising the PII protection that
  motivated them.
- Three rule adjustments:
  - Non-aggregated queries on `transactions` were flagged for review by
    default. Changed to `allow` when the query included a date filter
    narrower than 90 days.
  - `advisor_clients` wildcard selects stayed at `deny`, but a new
    policy-suggested rewrite offered the user a curated column list.
  - Queries with `JOIN` on 3+ tables were auto-flagged for review. The
    threshold moved to 5+ after 72 hours of data showed the 3-4 range
    was overwhelmingly benign.
- `review` rate dropped from 19% to 6% in 48 hours; `allow` rose to 85%.

**Week 5: First real story of value.**

- A senior financial advisor who had waited 11 days for a custom report
  on client-tier retention produced the same answer in 40 minutes of
  self-service use. The advisor had never written SQL. The policy
  engine flagged two of her attempts for review and suggested
  correctives; the eventual accepted query was within 3% of the
  hand-written version the analytics team later audited against.

### Days 36 to 60: Expansion and trust building

**Weeks 6 and 7: Scale-out.**

- Pilot expanded from 25 users to 90, covering three more business
  domains: `sales_operations`, `finance`, `product_analytics`.
- Deployed the `ServiceMonitor` and `PrometheusRule` manifests from
  `infra/k8s/observability/`. Acme's SREs hooked the alerts into
  PagerDuty under a new tier-2 schedule.
- First SEV-3 incident: the circuit breaker opened for 22 minutes on a
  Tuesday morning when an internal LLM gateway upgrade degraded. The
  heuristic fallback kept users productive at ~60% accuracy during that
  window. Acme's on-call followed `docs/runbooks/incident-response.md`
  end-to-end and later wrote a one-page postmortem as internal training
  material.

**Week 8: Governance review.**

- Acme's governance board reviewed 4 weeks of audit-trail data. Key
  findings they reported back to us:
  - **Zero unauthorized PII exposure incidents** across 4,800 questions.
  - **100% of queries** tagged with the expected cost center and
    business domain.
  - **18 queries** were flagged as "suspicious" by their internal SIEM
    rules; all 18 were legitimate and documented.
  - **6 queries** routed to `review` turned into training examples for a
    new user cohort the following week.
- Governance board approved expansion to full production readiness.

### Days 61 to 90: Production rollout and self-service takeoff

**Weeks 9 and 10: Production hardening.**

- Raised HPA ceiling from 4 to 20 replicas. Peak usage during a quarterly
  close hit 14 replicas for 2 hours; autoscaler behaved as expected with
  no user-visible degradation.
- Migrated from Ollama + phi3 to Claude Sonnet 4 as the production
  provider, following `docs/runbooks/model-swap.md`. Shadow-eval showed
  a 9-point gold-eval accuracy improvement (from 82% to 91%) before the
  cutover. Latency p99 improved slightly (1.9s -> 1.7s) thanks to
  Anthropic's faster inference path.
- Deployed Nexus-Hive into their DR region following the same Helm chart
  with `--set replicaCount=2 --set image.tag=0.2.0` across the two
  regions.

**Weeks 11 and 12: Full rollout.**

- All 500 analytics consumers enabled.
- New-dashboard intake volume to the central analytics team: **down
  62%** in the final two weeks of the pilot vs the pre-Nexus-Hive
  four-week baseline.
- Analyst time spent on self-serve support: **down from 35% to 11%**
  per their anonymous monthly survey.
- Dashboard-creation lead time for bespoke requests: **down from 3
  business days to 6 hours** average for the requests that still
  require the central team.

## Before-and-after metrics

| Metric | Before Nexus-Hive | After 90 days | Change |
|---|---|---|---|
| Dashboard lead time (bespoke) | 3 business days | 6 hours | -94% |
| Ad-hoc analyst request queue | 220+ open | 35-50 open | -77% |
| Analyst time on self-serve support | 35% of week | 11% of week | -24pp |
| Data questions answered per week (firm-wide) | ~400 (by central team) | ~2,800 (mixed) | +7x |
| PII exposure incidents | 2 in last 12 months | 0 in 90 days | -100% |
| BI developer vacancy rate | 22% annually | N/A (too early) | Tracking |
| Snowflake cost per answered question | $1.82 | $0.64 | -65% |
| Percentage of queries self-served | <5% | 85% | +80pp |
| Audit coverage of ad-hoc queries | ~40% (manual) | 100% (automated) | +60pp |

The Snowflake cost improvement was a surprise to Acme. Early hypothesis:
the policy engine denies `SELECT *` and forces aggregations, which
reduces compute-heavy full-table scans.

## Lessons we learned with Acme

**1. The governance demo is the sales call.**

Acme's auditor was the decision-maker nobody was budgeting for. The
moment we put her in front of the policy-engine response, the
conversation flipped from "does this work?" to "how do we deploy this?".

**For future engagements**: In discovery, always ask "who in your
organization has the authority to kill this tool?" and then make sure
that person sees the audit trail in the second demo.

**2. Tune the `review` queue in week 4, not week 1.**

Early `review` rates of 15-20% feel too high to analysts, but the data
from the first two weeks is exactly what lets governance and analytics
teams collaboratively relax rules that turn out to be overreach. Trying
to tune preemptively leaves real governance gaps.

**3. Heuristic fallback earns trust when it rarely has to.**

The 22-minute circuit-breaker incident was scary in the moment, but the
product team at Acme reported it _increased_ user trust because the
product degraded gracefully instead of going down. If we had relied on
the LLM with no fallback, that would have been a SEV-2 outage.

**4. Self-service is a user-research problem, not just a model problem.**

The best analyst on the Acme team spent two days in week 7 with the
product team refining the in-product "suggested questions" that populate
when a user lands on the page. That work bumped the weekly active user
rate from 52% to 78% in two weeks. No model swap produced a comparable
jump.

**5. Cost-attribution beats cost-reduction as a selling point.**

Acme's FinOps team was the hardest internal stakeholder to convince. The
$1.82 -> $0.64 cost-per-question win was a pleasant surprise, but the
actual closer was the `QUERY_TAG` faithfulness - we did not disrupt their
chargeback model.

## What we shipped back into the product

Acme's pilot produced three upstream changes to Nexus-Hive:

1. **Configurable `review` threshold for JOIN count** (was hardcoded to
   3, now exposed in the policy profile).
2. **"Suggested rewrite" surface** on `deny` responses - users get a
   clean column list when they try `SELECT *`.
3. **Cost-attribution dashboard** example in `docs/solution-architecture.md`
   showing how `QUERY_TAG` maps into Snowflake chargeback reports.

## 12-month outlook

Acme's year-two plan is:

- Expand to their European operations, which requires the airgap overlay
  for data residency.
- Add a second analytics agent focused on chart narrative generation.
- Use the audit trail as a training dataset for a domain-tuned LLM.
- Publish an internal "Nexus-Hive hit rate" dashboard available to every
  leader so the gains are visible without our help.

## References and handoff material

- **Pilot retrospective deck** (internal to Acme, summary shared with us)
- **Configuration files used**: `helm/nexus-hive/values-prod.yaml` with
  3 overrides (HPA max 20, Claude Sonnet 4, GKE workload identity)
- **Policy profile**: extended from `strict` with 3 relaxations detailed
  in week 4 above
- **Follow-up engagements**: quarterly governance review, airgap
  rollout planning kickoff in Q3, architecture review for the chart
  narrative agent

## Notes for a solutions engineer using this story

When telling this narrative to a prospective customer:

1. **Lead with the auditor moment.** Decision-makers respond to risk
   reduction more than productivity gains.
2. **Quote the 94% lead-time reduction** as the headline number; it is
   the one executives will repeat.
3. **Use the 4-week policy tuning anecdote** to answer the inevitable
   "how do we know this won't be too strict?" question.
4. **Use the 22-minute circuit-breaker incident** as proof of
   operational maturity.
5. **Do NOT promise the 65% Snowflake cost reduction**; treat it as a
   bonus. It depends on the customer's starting `SELECT *` habit.

For the full technical deployment story, see
`docs/runbooks/production-deploy.md`. For the governance demo script,
see `docs/discovery-guide.md`.
