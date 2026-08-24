# Scaling Runbook

Capacity planning and cost optimization for Cloud Run.

**Parent:** [Operations Guide](README.md)

---

## Cloud Run Instance Configuration

Current production settings:

| Setting | Value | Why |
|---------|-------|-----|
| CPU | 4 cores | LLM inference (Gemini) is CPU-bound; 1 core too slow |
| Memory | 8 GB | ~500 MB base + ~4 GB for model caches + ~3 GB working memory |
| Concurrency | 1 | Stateful WebSocket sessions; 1 request at a time per instance |
| Min instances | 1 | Always-on; ~$40/month |
| Max instances | 10 | Auto-scale up to 10 if demand spikes |
| Timeout | 3600s | 1 hour max request time (search latency is 16-25s, leaves headroom) |

---

## Concurrency Model

**Why concurrency=1?** Each request holds a stateful WebSocket session. Concurrent requests on the same instance would share the same session context, leading to message interleaving and race conditions. **Do not increase to >1 without refactoring the session/context model.**

**Cost implication:**
- 1 request takes ~20s
- Concurrency=1 means Cloud Run must spawn a new instance for every concurrent user
- 1000 concurrent users = ~50 instances (1000 users × 20s latency / 60s per instance-minute / ~20 concurrent users per instance)

---

## Scaling Scenarios

### Light Load (<10 users)

- Min instances = 1
- Auto-scale kicks in if requests queue
- Cost: ~$40/month

### Medium Load (10-100 users)

- Min instances = 2–3 (avoid cold starts)
- Max instances = 10
- Expected: 5–10 instances running at peak
- Cost: ~$200–400/month

### Heavy Load (>100 users)

- Min instances = 5–10
- Max instances = 20+
- Consider provisioning OpenSearch with higher node count (retrieval becomes bottleneck)
- Cost: >$1000/month

---

## Cost Breakdown

**Cloud Run pricing** (us-central1, on-demand):
- vCPU: $0.0000417 per vCPU-second
- Memory: $0.0000050 per GB-second
- Requests: $0.40 per 1M requests

**Cost per instance-hour** (4 CPU, 8 GB):
- vCPU: 4 × 3600s × $0.0000417 = ~$0.60
- Memory: 8 × 3600s × $0.0000050 = ~$0.14
- Total: ~$0.74/hour = ~$18/day = ~$540/month (running continuously)

**With 1 min instance running + 5 instances during peak (8 hours):**
- Min instance: 1 × 24h = $17/month
- Peak instances: 5 × 8h × 20 working days = 800 instance-hours = ~$590/month
- Requests (assume 1M/month): $0.40
- **Total: ~$600/month**

---

## PostgreSQL Scaling

Cloud SQL auto-increases storage but requires manual action for CPU/memory upgrades.

**Current instance:** db-custom-4-16384 (4 vCPU, 16 GB RAM)

**Monitor connection pool:**
```bash
gcloud sql connect <INSTANCE_NAME> --project=gen-lang-client-0250737934 << EOF
SELECT count(*) FROM pg_stat_activity WHERE state='active';
EOF
```

**Expected:** <50 active connections (typical 10–20).

**Bottleneck:** If >80 connections, upgrade to db-custom-8-32768 (8 vCPU, 32 GB).

---

## OpenSearch Scaling

The vector index is shared across all Cloud Run instances; it's the bottleneck for high concurrency.

**Current cluster:** 2-node, 2 GB heap each (check via Dashboards or cloud console).

**Scaling triggers:**
- Retrieval latency >5s → add another data node
- High CPU (>70%) → upgrade to larger instance type
- High disk usage (>80%) → add nodes or reduce retention

**Add a node:**
```bash
gcloud compute instances create opensearch-node-2 \
  --image-family=debian-11 \
  --image-project=debian-cloud \
  --machine-type=n2-standard-4 \
  --zone=us-east1-b \
  --project=gen-lang-client-0250737934
```

Then join it to the cluster via Dashboards → Nodes → Add Node.

---

## Metrics to Monitor for Scaling Decisions

| Metric | Check | Action |
|--------|-------|--------|
| Cloud Run instance count | `gcloud run services describe` → `status.traffic[].revisions` | If max-instances hit consistently, upgrade CPU/memory or add min-instances |
| Cloud Run latency P95 | Logs Explorer | If >35s, either improve code or scale horizontally (more instances) |
| PostgreSQL connections | `pg_stat_activity` | If >80, upgrade to larger instance |
| OpenSearch CPU | Cloud Console → VM instances | If >70%, add nodes or upgrade |
| OpenSearch retrieval latency | Logs (look for `retriever_latency_ms`) | If >5s, add OpenSearch nodes |

---

## Cost Optimization Tips

1. **Use min-instances=0 in dev/staging** (cold starts are acceptable)
2. **Set max-instances = 2× expected peak load** (saves on over-provisioning)
3. **Monitor PostgreSQL query logs** (enable slow query log to find bottlenecks)
4. **Schedule batch re-indexing off-peak** (re-indexing is CPU-intensive on OpenSearch)
5. **Compress logs after 30 days** (Cloud Logging charges for storage)

---

## Disaster Recovery: Scaling Back Down

If you over-provisioned and need to scale back:

```bash
gcloud run services update agentic-hybrid-search \
  --min-instances=1 \
  --max-instances=5 \
  --region=us-central1 \
  --project=gen-lang-client-0250737934
```

Old instances shut down gracefully over 5 minutes. Active requests are not interrupted.

---

For monitoring during scaling, see [Monitoring](monitoring.md). For deployment, see [Deployment](deployment.md).
