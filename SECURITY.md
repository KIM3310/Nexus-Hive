# Security Policy

## Reporting a Vulnerability

Please report suspected vulnerabilities privately. Do not open a public issue for security-sensitive findings.

Use GitHub private vulnerability reporting or contact the repository owner through the maintainer profile. Include:

- A concise description of the issue
- Reproduction steps or proof of concept
- Affected versions, commits, services, or deployment modes
- Potential impact and suggested remediation, if known

We aim to acknowledge valid reports promptly and coordinate a fix before public disclosure.

## Supported Scope

Security support applies to the default branch and the latest released or documented deployment path for Nexus-Hive. Experimental examples, local-only scripts, and archived demos are best-effort unless the README states otherwise.

## Handling Secrets

- Never commit API keys, tokens, certificates, private keys, cookies, or `.env` files.
- Prefer environment variables, platform secret stores, or CI secret managers.
- Rotate any secret that may have been exposed in logs, screenshots, commits, or artifacts.
