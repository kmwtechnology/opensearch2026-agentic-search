# Troubleshooting Runbook

Common failure patterns and recovery steps.

**Parent:** [Operations Guide](README.md)

---

## Service Won't Start

**Symptom:** Cloud Run revision fails immediately (crash loop).

**Check startup logs:**
```bash
gcloud run services logs read agentic-hybrid-search --region=us-central1 --project=gen-lang-client-0250737934 --limit=50
```

### Missing Environment Variable

**Symptom:** ConfigurationError: GOOGLE_API_KEY not set or similar.

**Fix:** Add the variable to Secret Manager and update build-deploy.yml:
```bash
gcloud secrets create google-api-key --data-file=- << EOF
<API_KEY_VALUE>
EOF

# Then update build-deploy.yml --set-secrets to include this secret
```

Restart:
```bash
gcloud run services update-traffic agentic-hybrid-search --to-revisions=LATEST=100 --region=us-central1 --project=gen-lang-client-0250737934
```

### PostgreSQL Unreachable

**Symptom:** ConnectionError: Error connecting to database at postgres://...

**Check Cloud SQL:**
```bash
gcloud sql instances list --project=gen-lang-client-0250737934
gcloud sql operations list --instance=<INSTANCE_NAME> --limit=10
```

**Verify Cloud Run to Cloud SQL networking:**
- Cloud Run service must be in the same VPC as Cloud SQL, or Cloud SQL must have Public IP
- Check `gcloud sql instances describe <INSTANCE_NAME>` → `settings.ipConfiguration.requireSsl`

**Restart Cloud SQL:**
```bash
gcloud sql instances restart <INSTANCE_NAME> --project=gen-lang-client-0250737934
```

### OpenSearch Unreachable

**Symptom:** ConnectionError: Error connecting to OpenSearch at https://opensearch-prod.example.com:443

**Check OpenSearch VM:**
```bash
gcloud compute instances describe opensearch --project=gen-lang-client-0250737934 --zone=us-east1-b
```

**Check network connectivity:**
```bash
gcloud compute ssh opensearch --project=gen-lang-client-0250737934 --zone=us-east1-b -- sudo systemctl status opensearch
```

**Verify firewall rules allow Cloud Run to OpenSearch:**
```bash
gcloud compute firewall-rules list --filter="sourceRanges:10.0.0.0/8" --project=gen-lang-client-0250737934
```

---

## High Latency (>35s)

**Symptom:** Search requests regularly exceed 30 seconds.

**Check:**
1. **Is it a cold-start issue?** Cloud Run warms up the first request after a deploy. Expected: first request 20-30s, subsequent 16-25s.
2. **Is OpenSearch CPU-bound?** Check OS metrics:
   ```bash
   gcloud compute instances describe opensearch --project=gen-lang-client-0250737934 --zone=us-east1-b | grep machineType
   ```
   If small instance, consider upgrading.

3. **Is the retriever fetching too many documents?** Check RETRIEVER_FETCH_K (default 30):
   ```bash
   gcloud run services describe agentic-hybrid-search --project=gen-lang-client-0250737934 | grep RETRIEVER_FETCH_K
   ```
   If >40, consider reducing.

4. **Are Gemini API calls slow?** Monitor Gemini API quota usage (Google Cloud Console → Gemini API).

---

## High Error Rate (>5%)

**Symptom:** Many 5xx responses in logs.

**Check error pattern:**
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=agentic-hybrid-search AND severity>=ERROR" --limit=100 --project=gen-lang-client-0250737934 | head -20
```

### 401 Unauthorized (Auth Failures)

**Symptom:** Many 401 Unauthorized responses.

**Check:** Is the session cookie being set correctly?
```bash
curl -i -X POST https://agentic-hybrid-search-xxxx.run.app/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: https://agentic-hybrid-search-xxxx.run.app" \
  -d '{"password": "'"$(grep '^LOGIN_PASSWORD=' ~/.env | cut -d= -f2)"'"}'
```

Expected: 200 OK with Set-Cookie: ahs_session=....

If 403, the Origin header is being rejected. Check get_allowed_origins() in api/main.py.

### 503 Service Unavailable

**Symptom:** Health endpoint returning non-ok probes.

**Check:**
```bash
curl https://agentic-hybrid-search-xxxx.run.app/api/health
```

Response will indicate which probe failed (postgres, opensearch, or google_api). See Service Won't Start above for remediation.

---

## WebSocket Disconnections (4401)

**Symptom:** Clients seeing WebSocket close code 4401 (auth failed).

**Expected behavior:** 4401 is normal when a session cookie expires (default 24 hours). Clients should re-authenticate.

**If rate is high:**
1. Check SESSION_MAX_AGE_SECONDS is reasonable (default 86400 = 24h).
2. Verify SESSION_COOKIE_SECURE=true on Cloud Run (false on localhost).
3. Check if there's a clock skew: date on local machine vs GCP clock.

**Fix cookie signing issues:**
```bash
# Regenerate a new SESSION_SECRET
openssl rand -hex 32

# Update Secret Manager
gcloud secrets versions add session-secret --data-file=- << EOF
<NEW_SECRET>
EOF

# Redeploy
./scripts/deploy.sh --project gen-lang-client-0250737934
```

---

## Database Corruption or Lock

**Symptom:** Queries to PostgreSQL hang or timeout.

**Check active connections:**
```bash
gcloud sql connect <INSTANCE_NAME> --project=gen-lang-client-0250737934 << EOF
SELECT count(*), state FROM pg_stat_activity GROUP BY state;
EOF
```

If many idle in transaction connections, a transaction is holding a lock.

**Kill stuck transactions:**
```bash
gcloud sql connect <INSTANCE_NAME> --project=gen-lang-client-0250737934 << EOF
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND query_start < now() - interval '10 minutes';
EOF
```

**Restart Cloud SQL (nuclear option):**
```bash
gcloud sql instances restart <INSTANCE_NAME> --project=gen-lang-client-0250737934
```

---

## Document Index Empty or Stale

**Symptom:** Searches return no results, or very old results.

**Check document count:**
```bash
curl https://agentic-hybrid-search-xxxx.run.app/api/health | jq .document_count
```

Expected: 9618 (for the shipped 10k ESCI sample).

**Re-index:**
```bash
gh workflow run reindex.yml -r main
```

Monitor:
```bash
gh run list --workflow reindex.yml --limit 1
```

Expected time: ~5-10 minutes. You can search while re-indexing is in progress (no downtime).

---

## Deployment Stuck or Timeout

**Symptom:** build-deploy.yml job running for >20 minutes or timing out.

**Check workflow:**
```bash
gh run view <RUN_ID> --log
```

**Most common cause:** Docker build layer caching miss (large pip dependencies). Takes 1-2 min on first build, then 30-60s cached.

**Force rebuild (clears cache):**
```bash
gcloud run deploy agentic-hybrid-search --image=us-central1-docker.pkg.dev/gen-lang-client-0250737934/agentic-hybrid-search/agentic-hybrid-search:latest --region=us-central1 --project=gen-lang-client-0250737934 --no-cache
```

---

## Smoke Tests Fail Post-Deploy

**Symptom:** All CI gates pass, but post-deployment smoke tests fail.

**Check what failed:**
```bash
gh run view <RUN_ID> --log | grep -A 20 "Post-Deployment Smoke Tests"
```

**Common failures:**
1. **Auth smoke test fails:** Origin header is being rejected. Check get_allowed_origins() includes Cloud Run URL.
2. **WebSocket smoke test fails:** Check if WebSocket proxy is broken (usually firewall/networking). Verify wss://... is reachable.
3. **Latency SLO fails:** Check P95 latency; if legitimately >45s, increase pytest --timeout in build-deploy.yml.

**Rollback:** If smoke tests fail, traffic stays at 0% on the new revision. Manually rollback:
```bash
gcloud run services update-traffic agentic-hybrid-search --to-revisions=PREVIOUS=100 --region=us-central1 --project=gen-lang-client-0250737934
```

Then investigate and redeploy.

---

For deployment procedures, see [Deployment](deployment.md). For monitoring, see [Monitoring](monitoring.md).
