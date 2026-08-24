# Deployment Runbook

Blue-green deployment to GCP Cloud Run, with pre-flight checklist and rollback procedures.

**Parent:** [Operations Guide](README.md)

---

## Pre-Deployment Checklist

Before pushing code to `main` or triggering a manual deploy:

- [ ] All CI gates pass locally: `make ci` (lint + unit tests + frontend)
- [ ] Smoke tests pass locally: `make smoke-local` (~90s)
- [ ] Environment variables are set in **both** places:
  - `langchain_agent/.env` (for local testing)
  - `build-deploy.yml` `--set-secrets` (for Cloud Run startup)
  - Checklist: `GOOGLE_API_KEY`, `LOGIN_PASSWORD`, `SESSION_SECRET`, `SESSION_COOKIE_SECURE=true`
- [ ] PR is merged to `main` and GitHub Actions workflow has started
- [ ] Manual deploy (optional): `./scripts/deploy.sh --project <GCP_PROJECT_ID>`

---

## Deployment Process (Automatic)

When code is merged to `main`, `.github/workflows/build-deploy.yml` automatically:

1. **Phase 1 Unit Tests** (~3s) — Python unit tests
2. **Phase 2 Integration Tests** (~30s) — PostgreSQL + OpenSearch live tests
3. **Frontend Tests & Lint** (~5s) — Vitest, ESLint, TypeScript
4. **ShellCheck** (~2s) — bash script validation
5. **Linting & Type Checks** (~5s) — flake8, mypy
6. **Build Docker Image** (~1–2 min) — push to Artifact Registry
7. **Deploy to Cloud Run** (~2 min) — blue-green deploy, 0% traffic initially
8. **Post-Deployment Smoke Tests** (~5 min) — 20 live tests against the new revision

**Total time:** ~12–15 minutes.

---

## Traffic Promotion

After deployment completes successfully:

- The new revision receives **0% traffic** (blue-green safety)
- Smoke tests run against the new revision
- On smoke test success: traffic is promoted to **100%** (green becomes blue)
- Old revision remains running but receives no traffic (for instant rollback if needed)

Monitor the promotion:
```bash
gcloud run services describe agentic-hybrid-search --region=us-central1 --project=gen-lang-client-0250737934 --format='value(status.traffic[].percent)'
```

Expected output after successful deploy: `100` (new revision) or `100,0` (split during transition).

---

## Rollback (Instant)

If the deployment is broken and needs immediate rollback:

```bash
gcloud run services update-traffic agentic-hybrid-search \
  --to-revisions PREVIOUS=100 \
  --region us-central1 \
  --project gen-lang-client-0250737934
```

This sends 100% traffic back to the previous (blue) revision. Takes ~10 seconds.

Verify:
```bash
gcloud run services describe agentic-hybrid-search --region=us-central1 --project=gen-lang-client-0250737934
```

---

## Re-Indexing ESCI Data

To refresh the product and judgment indexes (e.g., after code changes to mappings):

### Option A: Via GitHub Actions (Recommended)

```bash
gh workflow run reindex.yml -r main
```

This triggers the `reindex.yml` workflow on the GitHub Actions runner. Runs Lucille ETL against the hosted OpenSearch instance. Takes ~5–10 minutes.

Monitor:
```bash
gh run list --workflow reindex.yml --limit 1
```

### Option B: Manual (Workstation)

Requires: Java 17+, Maven, local Lucille checkout at `~/github/kmwtechnology/lucille`.

From `langchain_agent/`:
```bash
bash scripts/lucille_ingest.sh --reset-index
```

This atomically deletes + recreates the index, then ingests precomputed parquets from `data/`.

### Always Use `--reset-index`

The `--reset-index` flag is **critical**. It prevents the race condition where Lucille's auto-created default-mapped index becomes stale between a curl DELETE and the first write.

---

## Deployment Environment Variables

**Required in both `langchain_agent/.env` and `build-deploy.yml --set-secrets`:**

| Variable | Purpose | Example |
|----------|---------|---------|
| `GOOGLE_API_KEY` | Gemini LLM + embeddings | `AIza...` |
| `LOGIN_PASSWORD` | User login credential | `abc123def456` |
| `SESSION_SECRET` | Cookie signature key, ≥32 chars | `a1b2c3d4...` |
| `SESSION_COOKIE_SECURE` | HTTPS-only on prod | `true` |
| `OPENSEARCH_HOST` | Hosted instance (set by gcp-init.sh) | `opensearch-prod.example.com` |
| `OPENSEARCH_PORT` | Hosted instance port | `443` |
| `OPENSEARCH_USE_SSL` | Hosted instance requires TLS | `true` |

**Check Cloud Run secret startup:**
```bash
gcloud run services describe agentic-hybrid-search --region=us-central1 --project=gen-lang-client-0250737934 --format='value(spec.template.spec.containers[0].env[].name)'
```

---

## Post-Deployment Verification

After traffic is promoted to 100%, check:

1. **Service health:**
   ```bash
   curl https://agentic-hybrid-search-xxxx.run.app/api/health
   ```
   Expected: 200 OK, all probes green.

2. **Real request latency (GCP Logs):**
   ```bash
   gcloud run services logs read agentic-hybrid-search --region=us-central1 --project=gen-lang-client-0250737934 --limit=50 | grep "search.*latency"
   ```

3. **Error rate (last 5 min):**
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=agentic-hybrid-search AND severity>=ERROR" --limit=100 --project=gen-lang-client-0250737934
   ```

---

For monitoring procedures, see [Monitoring](monitoring.md). For troubleshooting, see [Troubleshooting](troubleshooting.md).
