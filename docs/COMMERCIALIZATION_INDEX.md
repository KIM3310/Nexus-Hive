# Commercialization Index

This index keeps the revenue, deployment, payments, privacy, and support surface aligned for `KIM3310/Nexus-Hive`. It is operational planning and launch governance, not legal, tax, financial, medical, security, or revenue-guarantee advice.

## Commercial position

- Commercial role: **supporting capability**
- Monetization path: **B2B lead-gen / consulting demo**
- Secondary path: **public product demonstration**
- Repository visibility: **public**

## Aligned document map

| Surface | File | Purpose |
| --- | --- | --- |
| Revenue strategy | [`REVENUE_READINESS.md`](REVENUE_READINESS.md) | Positioning, monetization path, resource needs, and next revenue action. |
| Business operations | [`BUSINESS_OPERATIONS.md`](BUSINESS_OPERATIONS.md) | Deployment, payment, privacy, and support lanes. |
| Deployment activation | [`DEPLOYMENT_ACTIVATION.md`](DEPLOYMENT_ACTIVATION.md) | Preview/production sequencing, hosting references, and secret rules. |
| Privacy draft | [`PRIVACY_POLICY_DRAFT.md`](PRIVACY_POLICY_DRAFT.md) | Owner-input privacy policy draft and pre-launch data commitments. |
| Payments/refunds draft | [`PAYMENTS_AND_REFUNDS_DRAFT.md`](PAYMENTS_AND_REFUNDS_DRAFT.md) | Payment activation checklist, refund stance, and provider references. |
| Support policy | [`../SUPPORT.md`](../SUPPORT.md) | Public/private support boundaries and response expectations. |

## Launch sequence

1. **Review** — confirm `REVENUE_READINESS.md` and `BUSINESS_OPERATIONS.md` still match the current repo state.
2. **Sanitize** — run a redacted secret scan and address any findings before publishing or deploying.
3. **Package** — make the buyer/user promise explicit without unsupported revenue, legal, medical, financial, or security claims.
4. **Operate** — define support owner, privacy contact path, refund/support terms, and deployment rollback owner.
5. **Activate** — only after owner approval, enable payment, analytics, contact capture, custom domain/DNS, and production traffic.

## Required gates

- [ ] Use the repository's documented verification command before release.
- [ ] Commercialization docs contain no secrets, credentials, customer data, payment details, or private logs.
- [ ] Privacy/contact path is owner-approved before collecting personal data.
- [ ] Payment/KYC/tax/refund/support terms are approved before accepting money.
- [ ] Production deployment/custom domain/DNS/analytics/contact capture are approved before launch.
- [ ] Customer-support routing avoids public exposure of personal, customer, regulated, or payment data.

## Current resource needs

- demo hosting or screenshots
- product case study
- contact/booking CTA
- optional CRM/email capture
- analytics

## Support posture

See `../SUPPORT.md` for public intake and private-channel rules.

## Maintenance rule

Keep commercialization docs consistent with this order: **positioning → operations → privacy/payment/support → deployment → customer activation**. Update this index whenever the product scope or operating assumptions change.
