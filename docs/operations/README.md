# Operations Guide

Runbooks and operational guidance for running Agentic Hybrid Search in production.

**Parent:** [Root README](../../README.md)

## Quick Links

| Runbook | Purpose | When to use |
|---------|---------|-----------|
| [GCP First-Timer Guide](gcp-quickstart.md) | Project creation, WIF, deploy.sh, gcp-init.sh, CI/CD setup | First-time GCP deployment from scratch |
| [Deployment](deployment.md) | Pre-deploy checklist, blue-green rollback, re-indexing | Before pushing to production; incident recovery |
| [Monitoring](monitoring.md) | GCP Logs Explorer queries, metrics, alert setup | During/after deployment; proactive health checks |
| [Troubleshooting](troubleshooting.md) | Common failure patterns and fixes | When something breaks; startup errors |
| [Scaling](scaling.md) | Cloud Run concurrency, instance sizing, cost tuning | Load planning; cost optimization reviews |

---

## Key Concepts

**Cloud Run blue-green deployment** — new revisions receive 0% traffic initially. Traffic is promoted to 100% only after smoke tests pass. Rollback is instant via `gcloud run services update-traffic`.

**Session authentication** — users log in via `POST /api/auth/login` and receive a signed HttpOnly cookie. Admin tasks (reindexing) use a long-lived `ADMIN_TOKEN` header.

**Re-indexing** — triggered manually via GitHub Actions workflow `reindex.yml` or via `scripts/lucille_ingest.sh` (requires Java 17+ and a local Lucille checkout). Always use `--reset-index` to avoid race conditions.

**Smoke tests** — run post-deployment against the live Cloud Run service. All 20 tests must pass before traffic is promoted. Covers auth, WebSocket, search pipeline, citations, and latency SLOs.

---

## Healthy Production State

- `/api/health` endpoint returns 200 with all probes green (PostgreSQL, OpenSearch, Google API)
- P95 search latency < 30 seconds (typical 16–25s)
- No sustained error rate spikes in Cloud Logs
- All WebSocket connections close gracefully; no 4401 auth rejections (unless intentional login expiry)

---

For detailed procedures, see the runbooks above. For integrator or developer docs, see [root README](../../README.md).
