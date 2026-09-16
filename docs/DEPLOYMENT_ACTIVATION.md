# Deploy the static recorded demo

Cloudflare Pages project `nexus-hive` publishes the `frontend/` directory. It does not run FastAPI, SQLite queries, Ollama, or warehouse adapters. The public primary action opens an existing recorded audit fixture, not a new query result.

## Verify before upload

```bash
make verify
make browser-install
make browser-test
```

`make verify` seeds only the local synthetic SQLite database. The browser suite starts a separate disposable SQLite runtime with paid model and warehouse credentials absent. Use `NEXUS_HIVE_BROWSER_CHANNEL=chrome make browser-test` when Google Chrome is already installed.

The static page still fetches Chart.js and fonts from their public CDNs. Verify the page in the deployment environment as well as locally.

## Publish the right artifact

The checked-in `wrangler.jsonc` and `.github/workflows/pages-auto-deploy.yml` both name project `nexus-hive` and output `frontend`.

After an authorized operator verifies the account and project, the workflow-equivalent direct upload is:

```bash
npx wrangler@4 pages deploy frontend --project-name=nexus-hive --branch=main
```

The GitHub workflow skips upload when `CLOUDFLARE_API_TOKEN` or `CLOUDFLARE_ACCOUNT_ID` is missing. A green workflow in that case is not a completed deployment. Inspect the upload step and the resulting public page. Do not infer deployment from the workflow conclusion alone.

Keep privacy, terms, support links, and the recorded-mode notice in the artifact. Verify the primary recorded action, keyboard focus, and mobile layout after publication. Production traffic, custom domains, DNS, analytics, and any remote backend need separate approval.

## Keep the API separate

Run `make run` for the local API on port 8000. Hosting that API elsewhere requires its own database permissions, operator identity, network controls, and deployment plan. Setting a static API base does not supply those controls.

Never put API keys, payment secrets, database credentials, customer data, or private logs in the static bundle. Configure credentials only through the backend or provider's supported secret store.

- [Cloudflare Pages](https://developers.cloudflare.com/pages/)
- [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)
