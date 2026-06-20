# OpenRouter Routing Profile

This repository is prepared for OpenRouter as the hosted LLM gateway. OpenRouter is OpenAI-compatible, so server-side integrations should call `https://openrouter.ai/api/v1/chat/completions` or use an OpenAI-compatible SDK with `base_url=https://openrouter.ai/api/v1`.

## Model Profile

| Lane | Model | Purpose |
|---|---|---|
| Primary | `google/gemini-3.5-flash` | Governed analytics explanations, NL2SQL guardrail summaries, and audit exports. |
| Fallback | `openai/gpt-5.4-mini` | Higher reliability or alternate-provider path when the primary model is unavailable. |
| Economy / demo | `openrouter/free` | Low-cost smoke tests, demos, and free-tier exploration with strict quotas. |

## Environment Contract

```bash
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=google/gemini-3.5-flash
OPENROUTER_FALLBACK_MODEL=openai/gpt-5.4-mini
OPENROUTER_ECONOMY_MODEL=openrouter/free
OPENROUTER_HTTP_REFERER=https://nexus-hive.pages.dev
OPENROUTER_APP_TITLE=Nexus-Hive
```

## Operating Rules

- Keep OpenRouter keys server-side only. Never expose `OPENROUTER_API_KEY` in browser bundles, public docs, Unity assets, mobile clients, or committed files.
- Prefer BYOK for paid workspaces: customers can bring their own OpenRouter key or a bounded workspace key with a credit limit.
- Keep deterministic fixtures and local fallback paths active so demos still work when no key is configured.
- Add request budgets before public launch: per-IP rate limit, daily credit cap, timeout, max tokens, and structured logging of model/cost/latency.
- For sensitive domains, send only synthetic or explicitly approved payloads. Medical, security, and document workflows must keep human review and non-diagnostic/non-authoritative wording.
