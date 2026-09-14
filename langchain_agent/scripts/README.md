# Agentic Hybrid Search — Scripts

> **Parent**: [langchain_agent/README.md](../README.md)

Lifecycle and deployment scripts. All run from `langchain_agent/` and assume Docker
is running (or can be started automatically).

## Quick Reference

| Script | Purpose | When | Time |
|--------|---------|------|------|
| **Setup & Teardown** |
| `setup.sh` | One-time: venv, Docker, DB init, Lucille ingest | First clone | 10–20 min |
| `teardown.sh` | Clean up: services, volumes, `.venv`, `node_modules`, logs | End of session (optional) | 1–2 min |
| **Local Development** |
| `start.sh` | Start Docker, backend (:8000), frontend (:5173) | Session start | 10–15 s |
| `stop.sh` | Stop backend + frontend; keep Docker up | Before committing | 5 s |
| `logs.sh` | Tail backend/frontend logs | Debugging | — |
| **GCP Deployment** |
| `deploy.sh` | Build Docker, push to Artifact Registry, deploy to Cloud Run | Release to production | 3–5 min |
| `gcp-init.sh` | One-time: Cloud SQL setup, ESCI ingest via Lucille (on runner) | After first deploy | 5–10 min |
| `gcp-teardown.sh` | Remove Cloud Run, Cloud SQL, OpenSearch, secrets | End of project | 2–3 min |
| `smoke_test.sh` | Health check + basic round-trip against a Cloud Run URL | Post-deploy verification | 10 s |
| **CI/Manual Gates** |
| `pre-commit.sh` | Black + isort + flake8 on staged `.py` files | Installed as `.git/hooks/pre-commit` by `setup.sh` — runs automatically on `git commit` | ~2 s |
| `lucille_ingest.sh` | ESCI re-ingestion (builds Lucille on first run, reads `data/*.parquet`) | Manual re-ingest | 30 s–1 min |
| **Utilities** |
| `prepare_judgments_parquet.py` | Pre-aggregate ESCI judgments (one-time or on sample change) | Data ops | 2–3 min |
| `rebuild_attribute_taxonomies.py` | Wipe and rebuild the color/material attribute taxonomies from scratch via discovery against real `chunk_text` (writes to OpenSearch, not a committed file). Also what `lucille_ingest.sh --seed-taxonomy` / `make seed-taxonomy` / `reindex.yml`'s `seed_taxonomy` input run between the two products passes | Data ops (once per cluster whose mapping store is empty — e.g. the hosted one, #71 — or to reset to seed state; the live enrichment flywheel grows the taxonomy incrementally otherwise) | ~1 min |
| `probe_demo_query.py` | Standalone demo query tester; useful for debugging retriever/reranker | Ad hoc testing | — |

`../config_generator.py` (not a standalone script — invoked by `lucille_ingest.sh`) regenerates `lucille-esci/conf/products.generated.conf` from whatever attribute types are currently registered in OpenSearch, immediately before every ingest run. See `ARCHITECTURE.md`'s "Attribute Detection" and "Enrichment Flywheel" sections for the full mechanism — `AttributeNormalizerStage.java`/`enrich_attribute_normalization.py`/`analyze_color_attributes.py`/`color_mappings.json` described in older docs are retired; detection now happens during ingest via the generic `AttributeDetectorStage.java`, sourced from OpenSearch, not a post-ingest Python pass over a committed JSON file.

## Execution Order

### Path A: Local Development

1. **First time:**
   ```bash
   cp .env.example .env          # Fill in GOOGLE_API_KEY
   ./scripts/setup.sh            # Creates .venv, starts Docker, ingests ESCI
   ```

2. **Each session:**
   ```bash
   ./scripts/start.sh            # Restarts services
   # ... code, test, develop ...
   ./scripts/stop.sh             # Stops backend + frontend
   ```

3. **Cleanup (optional):**
   ```bash
   ./scripts/teardown.sh         # Removes everything except .env
   ```

### Path B: GCP Deployment

1. **First deployment:**
   ```bash
   ./scripts/deploy.sh --project <GCP_PROJECT_ID>
   ./scripts/gcp-init.sh --project <GCP_PROJECT_ID>    # Cloud SQL + ingest
   ./scripts/smoke_test.sh <CLOUD_RUN_URL>
   ```

2. **Subsequent deployments:**
   ```bash
   ./scripts/deploy.sh --project <GCP_PROJECT_ID>
   ./scripts/smoke_test.sh <CLOUD_RUN_URL>
   ```

3. **Re-ingest ESCI (manual):**
   ```bash
   # Manually trigger the GitHub Actions reindex.yml workflow instead
   # OR run locally:
   bash ./scripts/lucille_ingest.sh
   ```

## Git Hooks

`setup.sh` installs `pre-commit.sh` as `.git/hooks/pre-commit` (added issue #99) — it runs automatically on every `git commit` and blocks the commit if black/isort/flake8 fail on staged `.py` files. It only ever overwrites a hook it recognizes as its own (matched by a comment marker); a hand-written custom hook at that path is left untouched and setup.sh prints a warning instead. If you cloned before this existed, re-run `./scripts/setup.sh` to install it, or copy it manually: `cp scripts/pre-commit.sh ../.git/hooks/pre-commit && chmod +x ../.git/hooks/pre-commit`.

There is still **no pre-push hook** — `.git/hooks/pre-push` is Git LFS's own hook only. Nothing beyond formatting/lint is gated locally; the checks below must be run by hand.

### Before committing

The pre-commit hook covers black/isort/flake8 automatically. Also run manually if applicable:
- Smoke gate (`make smoke-local-quick`) if `api/services/`, `api/routes/`, `main.py`, `core/agent_state.py` changed AND Docker is up

**If the hook blocks a commit:** Run `make format-fix`, re-stage, retry.

### Before pushing

Run manually before every push:
- `make ci` — full local gate (lint + unit + frontend + collect-only integration/e2e)
- `make smoke-local` if any backend-path file changed AND Docker is up (20-test suite, ~90 s)

Nothing stops a push with failing tests except CI (formatting is caught earlier, at commit time, by the pre-commit hook above).

**If checks fail:** Fix root cause, re-run `make ci` locally, push retry.

## Smoke Test Budget

Local smoke gates expect:
- `setup` — 5 s overhead
- Per `chat_message` — 16–25 s end-to-end
- Pytest `--timeout=120` covers ~2 sequential messages

Cloud Run adds cold-start latency (cross-encoder model load on first request); allow 35–45 s per message.

## Troubleshooting

**Port already in use:**
```bash
lsof -ti :8000 | xargs kill -9
lsof -ti :5173 | xargs kill -9
./scripts/start.sh
```

**Docker won't start:**
```bash
docker compose ps
docker compose up -d
```

**venv broken:**
```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

**Frontend can't reach backend:**
```bash
curl http://localhost:8000/api/health
./scripts/logs.sh frontend
```

## References

- [setup.sh](setup.sh) — inline comments describe each step
- [deploy.sh](deploy.sh) — Cloud Run deployment flow
- [lucille_ingest.sh](lucille_ingest.sh) — ESCI ingest orchestration
