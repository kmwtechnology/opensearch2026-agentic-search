# Scaling Runbook

Capacity planning and cost optimization for Cloud Run.

**Parent:** [Operations Guide](README.md)

---

## Cloud Run Instance Configuration

Current production settings:

| Setting | Value | Why |
|---------|-------|-----|
| CPU | 4 cores | LLM inference (Gemini) is CPU-bound; 1 core too slow |
| Memory | 2 GB | Sized for the FastAPI backend + cross-encoder reranker; no large in-memory caches |
| Concurrency | 8 | Up to 8 in-flight requests per instance |
| Min instances | 0 | Scales to zero when idle; no baseline cost |
| Max instances | 4 | Caps spend/spikes; raise if sustained load requires it |
| Timeout | 3600s | 1 hour max request time (search latency is 16-25s, leaves headroom) |

---

## Concurrency Model

**Why concurrency=8?** Each instance can serve up to 8 concurrent requests/WebSocket sessions. This isn't unlimited because the local cross-encoder reranker and per-request LLM calls are CPU/memory-bound; 8 balances instance utilization against resource contention on a 4-CPU/2GB instance.

**Cost implication:**
- With min-instances=0, no instances run (and no cost is incurred) while idle
- 1 request takes ~20s
- 1000 concurrent users at concurrency=8 needs roughly 1000/8 ≈ 125 concurrently-active instances at peak (bounded by max-instances=4 unless raised)

---

## Scaling Scenarios

### Light Load (<10 users)

- Min instances = 0 (scales to zero between bursts)
- Max instances = 4 (default)
- Cost: near $0 when idle; pay only for active request time

### Medium Load (10-100 users)

- Min instances = 1–2 (avoid cold starts if latency-sensitive)
- Max instances = 4–10 (raise from the current default if sustained)
- Expected: several instances running at peak given concurrency=8
- Cost: ~$50–150/month depending on min-instances

### Heavy Load (>100 users)

- Min instances = 2–5
- Max instances = 15+ (raise from the current default of 4)
- Consider provisioning OpenSearch with higher node count (retrieval becomes bottleneck)
- Cost: >$300/month

---

## Cost Breakdown

**Cloud Run pricing** (us-central1, on-demand):
- vCPU: $0.0000417 per vCPU-second
- Memory: $0.0000050 per GB-second
- Requests: $0.40 per 1M requests

**Cost per instance-hour** (4 CPU, 2 GB):
- vCPU: 4 × 3600s × $0.0000417 = ~$0.60
- Memory: 2 × 3600s × $0.0000050 = ~$0.036
- Total: ~$0.64/hour = ~$15/day = ~$460/month (running continuously)

**With min-instances=0 (current production setting), there is no baseline cost** — instances only run (and bill) while serving requests. For a workload with, say, 4 instances active 8 hours/day on peak days:
- Peak instances: 4 × 8h × 20 working days = 640 instance-hours = ~$410/month
- Requests (assume 1M/month): $0.40
- **Total: ~$410/month at that usage level; ~$0/month at true idle**

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
  --min-instances=0 \
  --max-instances=4 \
  --region=us-central1 \
  --project=gen-lang-client-0250737934
```

Old instances shut down gracefully over 5 minutes. Active requests are not interrupted.

---

For monitoring during scaling, see [Monitoring](monitoring.md). For deployment, see [Deployment](deployment.md).
