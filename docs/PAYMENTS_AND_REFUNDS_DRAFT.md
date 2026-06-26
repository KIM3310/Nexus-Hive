# Payments and Refunds Draft

Generated: 2026-06-26

This document prepares payment operations for `KIM3310/Nexus-Hive` without creating a live checkout. It is not legal, tax, accounting, or financial advice.

## Payment activation status

No live payment link, Stripe secret key, webhook secret, tax setting, KYC setting, or bank account configuration is stored in this repository.

## Before accepting money

- Define the exact offer, deliverables, buyer eligibility, delivery timeline, and support window.
- Finalize refund/cancellation terms and jurisdiction-specific consumer disclosures.
- Complete payment-account KYC, tax, payout, and fraud settings in the provider dashboard.
- Use hosted checkout/payment links or server-side environment variables; never commit payment secrets.
- Keep customer/order/payment details out of public GitHub issues.

## Draft refund stance

- Free/demo/community use: no payment collected.
- Paid discovery/pilot: refund terms must be agreed in writing before payment.
- Digital product/template: refund eligibility, delivery method, license, and support window must be shown before checkout.

## Provider references

- Stripe Payment Links: https://docs.stripe.com/payment-links
- Stripe create a payment link: https://docs.stripe.com/payment-links/create
