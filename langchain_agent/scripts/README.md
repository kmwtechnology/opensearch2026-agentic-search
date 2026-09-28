# Agentic Hybrid Search — Scripts

> **Parent**: [langchain_agent/README.md](../README.md)

Lifecycle scripts for local development. All run from `langchain_agent/` and
assume Docker is running (or can be started automatically). There is no
deployment path anymore — the project is local-only as of issue #110/#113.

## Quick Reference

| Script | Purpose | When | Time |
|--------|---------|------|------|
| **Setup & Teardown** |
| `setup.sh` | One-time: venv, Docker, DB init, bulk-load the precomputed corpus dump | First clone | 1–2 min (fails with a `git lfs pull` message if `data/precomputed/` is missing — there is no from-scratch fallback) |
| `teardown.sh` | Clean up: services, volumes, `.venv`, `node_modules`, logs | End of session (optional) | 1–2 min |
| **Local Development** |
| `start.sh` | Start Docker, native backend (:8080) + Vite (:5173), and rebuild/start the demo container (:8000) | Session start | 15 s–2 min (demo image build) |
| `stop.sh` | Stop backend + frontend + Docker containers (volumes kept) | Session end | 5 s |
| **CI/Manual Gates** |
| `pre-commit.sh` | Black + isort + flake8 on staged `.py` files | Installed as `.git/hooks/pre-commit` by `setup.sh` — runs automatically on `git commit` | ~2 s |
| **Utilities** |
| `load_precomputed_indices.py` | Bulk-load `data/precomputed/*.parquet` straight into OpenSearch (no Ollama, no ingest pipeline) — what `setup.sh`/`setup.py` call every time | First clone / re-provisioning a cluster | ~1-2 min |
| `prepare_judgments_parquet.py` | Historical: pre-aggregate ESCI judgments (used to originally build the corpus; not part of any live workflow today) | Reference only | 2–3 min |
| `build_product_sample.py` | Historical: build the ESCI product sample parquet the corpus was originally ingested from (#147); not part of any live workflow today | Reference only | — |
| `reset_demo_taxonomy.sh` | Reset the live attribute-mapping store back to seed state for the demo | Demo reset | — |

There is no local ingest pipeline any more — see `data/README.md`. Attribute detection
(`product_<type>_primary`/`_secondary` keyword fields) is baked into the precomputed
corpus dump; live growth/correction happens entirely through the enrichment flywheel's
scoped re-tag (`pipeline/scoped_retag.py`), not through any script here. See
`ARCHITECTURE.md`'s "Attribute Detection" and "Enrichment Flywheel" sections for the
full mechanism.

## Execution Order

1. **First time:**
   ```bash
   cp .env.example .env          # Ollama must be installed and running
   ./scripts/setup.sh            # Creates .venv, pulls Ollama models, starts Docker,
                                  #   bulk-loads the precomputed corpus dump
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

There is no re-ingest step — the corpus is a permanent, one-time export
(`data/precomputed/`, see `data/README.md`). Re-running `setup.sh`/`make setup`
reloads the same dump.

## Git Hooks

`setup.sh` installs `pre-commit.sh` as `.git/hooks/pre-commit` (added issue #99) — it runs automatically on every `git commit` and blocks the commit if black/isort/flake8 fail on staged `.py` files. It only ever overwrites a hook it recognizes as its own (matched by a comment marker); a hand-written custom hook at that path is left untouched and setup.sh prints a warning instead. If you cloned before this existed, re-run `./scripts/setup.sh` to install it, or copy it manually: `cp scripts/pre-commit.sh ../.git/hooks/pre-commit && chmod +x ../.git/hooks/pre-commit`.

There is still **no pre-push hook** — `.git/hooks/pre-push` is Git LFS's own hook only. Nothing beyond formatting/lint is gated locally; the checks below must be run by hand.

### Before committing

The pre-commit hook covers black/isort/flake8 automatically. Also run manually if applicable:
- `make ci` (ends with the live smoke test) if `api/services/`, `api/routes/`, `main.py`, or `core/agent_state.py` changed

**If the hook blocks a commit:** Run `.venv/bin/black . && .venv/bin/isort .`, re-stage, retry.

### Before pushing

Run `make ci` before every push or PR merge — it's the one command that
combines everything: lint, unit tests, frontend test/lint/build, collect-only
integration/e2e, then a real search-intent round-trip against a running
backend (it brings Docker up itself). For fast iterative feedback while
coding, `PYTHONPATH=. .venv/bin/pytest tests/unit/`. There's no Make target
for the broader regression suite — run it directly when you want it:
`bash scripts/smoke_local.sh` (~90s, all e2e+slow scenarios).

Nothing stops a push with failing tests except this local gate (formatting is caught earlier, at commit time, by the pre-commit hook above).

**If checks fail:** Fix root cause, re-run `make ci` locally, push retry.

## Smoke Test Budget

Local smoke gates expect:
- `setup` — 5 s overhead
- Per `chat_message` — 16–25 s end-to-end
- Pytest `--timeout=120` covers ~2 sequential messages

## Troubleshooting

**Port already in use:**
```bash
lsof -ti :8080 | xargs kill -9
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
curl http://localhost:8080/api/health
tail -f logs/frontend.log
```

## References

- [setup.sh](setup.sh) — inline comments describe each step
- [load_precomputed_indices.py](load_precomputed_indices.py) — corpus load orchestration
- [../data/README.md](../data/README.md) — the precomputed corpus, and why there's no ingest pipeline
