# Technical Launch Playbook - Nexus-Hive

This playbook keeps launch review focused on evidence, deployment ownership, and operational readiness.

## Review Lane

- **Lane:** Repository-specific product and engineering proof
- **Primary reader:** Technical reviewers, operators, maintainers, and partners
- **First motion:** Inspect the live demo or static proof, README, architecture notes, and quality gate.

## Evidence Gates

1. Public demo route or static proof surface is reachable.
2. Local checks or CI pass for the current repository state.
3. Architecture notes explain runtime, data, and integration boundaries.
4. Security and privacy boundaries are visible before external data is used.
5. Known limitations are documented plainly.

## Launch Sequence

1. Confirm the README fast path and demo route.
2. Run the repository quality gate and keep the output current.
3. Review [service architecture](service-architecture.md) before adding runtime resources.
4. Add only the minimum accounts, secrets, and integrations needed for the next workflow.
5. Record screenshots or evidence artifacts after each deployment update.

## Operating Boundaries

- No private data unless storage, retention, deletion, and access controls are defined.
- No committed credentials or tenant-specific configuration.
- No external integration without a rollback or disable path.
- No unsupported claims beyond what the demo, tests, and docs can verify.

## Useful Metrics

- Demo availability
- Quality gate pass rate
- Build and deployment duration
- Error rate and latency where runtime telemetry exists
- Review completion for documented workflows

## Maintenance Rhythm

- Refresh README and architecture notes after meaningful changes.
- Re-run the quality gate before pushing.
- Keep demo screenshots and evidence artifacts aligned with the deployed UI.
- Remove stale generated files when they no longer support technical review.
