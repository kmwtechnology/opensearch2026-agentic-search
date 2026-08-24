# Monitoring Runbook

Observability setup and queries for production health checks.

**Parent:** [Operations Guide](README.md)

---

## Health Endpoint

Primary health check — always available, requires no auth:

```bash
curl https://agentic-hybrid-search-xxxx.run.app/api/health
```

Response (200 OK):
```json
{
  "status": "healthy",
  "postgres": "ok",
  "opensearch": "ok",
  "google_api": "ok",
  "document_count": 9618,
  "timestamp": "2026-06-04T16:30:45Z"
}
```

Probes check:
- **PostgreSQL:** reachable and responding (used for conversation state)
- **OpenSearch:** cluster health + document count
- **Google API:** Gemini and embedding models accessible

All three must be "ok" for the service to be considered healthy. Any probe failure returns 503.

---

## GCP Cloud Logs Queries

Access via [Google Cloud Console](https://console.cloud.google.com/logs) or CLI.

### Errors (Last Hour)

```
resource.type=cloud_run_revision
resource.labels.service_name=agentic-hybrid-search
severity=ERROR
```

Look for:
- `AgenticHybridSearchError` exceptions
- `ConnectionError` to PostgreSQL or OpenSearch
- `401 Unauthorized` (auth failures)

### Slow Requests (>30s)

```
resource.type=cloud_run_revision
resource.labels.service_name=agentic-hybrid-search
httpRequest.latency>"30s"
httpRequest.requestUrl=~"^.*\/api\/conversations\/.*\/messages.*"
```

Expected: <5% of requests exceed 30s (P95 is typically 16–25s).

### WebSocket Connection Errors

```
resource.type=cloud_run_revision
resource.labels.service_name=agentic-hybrid-search
jsonPayload.event_type="connection_error"
OR
textPayload=~".*websocket.*error.*"
```

A few `4401 Unauthorized` close codes are normal (cookie expiry). Many suggests auth configuration issue.

### Startup Failures

```
resource.type=cloud_run_revision
resource.labels.service_name=agentic-hybrid-search
severity=CRITICAL
OR
textPayload=~".*Traceback.*"
```

Common startup failures:
- Missing environment variable (e.g., `GOOGLE_API_KEY`)
- Database unreachable
- Secret Manager read error

---

## Key Metrics to Watch

| Metric | Normal Range | Alert Threshold |
|--------|--------------|-----------------|
| P95 search latency | 16–25s | >35s |
| Error rate | <1% | >5% |
| WebSocket conn failures | <0.1% | >1% |
| Pod restart rate | 0/hour | >2/hour |
| PostgreSQL connections | 5–15 | >25 |

### Export Metrics to Cloud Monitoring

Create a Cloud Monitoring dashboard to track these KPIs:

1. **Search latency (P95):**
   ```
   resource.type="cloud_run_revision"
   resource.labels.service_name="agentic-hybrid-search"
   httpRequest.requestUrl=~"^.*\/api\/conversations\/.*\/messages.*"
   metric: httpRequest.latencies
   ```

2. **Error rate:**
   ```
   resource.type="cloud_run_revision"
   resource.labels.service_name="agentic-hybrid-search"
   severity>=ERROR
   ```

3. **Pod restarts (Cloud Run revision age):**
   - Cloud Run automatically tracks revision age; check via `gcloud run services describe`

---

## GitHub Actions Monitoring

All deployments and re-indexing runs are visible on GitHub:

- **Build & Deploy workflow:** https://github.com/kmwtechnology/agentic-hybrid-search/actions/workflows/build-deploy.yml
- **Re-index workflow:** https://github.com/kmwtechnology/agentic-hybrid-search/actions/workflows/reindex.yml

View recent runs:
```bash
gh run list --workflow build-deploy.yml --limit 5
gh run view <RUN_ID>
```

Expected behavior:
- Every merge to `main` triggers `build-deploy.yml`
- All jobs should complete green (~12–15 min)
- Smoke tests are the final gate before traffic promotion

---

## Alert Setup (Cloud Monitoring)

To create an alert for high error rate:

1. Open [Cloud Monitoring](https://console.cloud.google.com/monitoring)
2. **Alerting** → **Create Policy**
3. **Condition:**
   - Resource type: `Cloud Run Revision`
   - Metric: `logging.googleapis.com/log_entry_count` (severity=ERROR)
   - Threshold: >100 errors in 5 minutes
4. **Notification:** Slack / email
5. **Save & Enable**

---

For troubleshooting, see [Troubleshooting](troubleshooting.md). For deployment procedures, see [Deployment](deployment.md).
