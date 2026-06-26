# Deployment Activation

Generated: 2026-06-26

This document records the approved deployment path for `KIM3310/Nexus-Hive` without storing secrets or forcing a production launch.

## Safe deployment order

1. Run the repository verification command from README/package/CI docs.
2. Review redacted secret-pattern audit findings before publishing.
3. Confirm privacy policy, terms/refund language, and support channel are ready.
4. Deploy a preview or staging build first.
5. Approve production traffic, custom domain/DNS, analytics, email capture, and rollback owner.

## Static hosting references

- Cloudflare Pages docs: https://developers.cloudflare.com/pages/
- Cloudflare Pages Direct Upload: https://developers.cloudflare.com/pages/get-started/direct-upload/
- GitHub Pages publishing source: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

## Secrets rule

Do not put API keys, payment secrets, database credentials, customer data, or private logs in static bundles or public repositories. Use environment variables and provider dashboards.
