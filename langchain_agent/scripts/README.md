# Scripts

> **Parent**: [../README.md](../README.md)

Run from `langchain_agent/`. The Makefile targets wrap the first five; the
rest are direct commands.

| Script | Does | Use it when |
|---|---|---|
| `doctor.sh` | Checks Docker, Python 3.14, Node, Ollama and pulled models, `.venv`, `node_modules`, and that `data/precomputed/` is real (not an LFS pointer) | `make doctor` (bare `make`) — after setup or when something is off |
| `setup.sh` | Creates `.venv` and `web/node_modules`, pulls Ollama models, starts PostgreSQL + OpenSearch, runs `setup.py` (tables, index, search pipeline, precomputed load), installs the pre-commit hook | `make setup` — first clone; safe to re-run (~1-2 min) |
| `start.sh` | `docker compose up -d --wait`, native backend on :8080 and Vite on :5173 in the background (`logs/`), then rebuilds and starts the demo container on :8000 (`logs/demo-build.log`) | `make dev` — every session; re-run to refresh the demo image |
| `stop.sh` | Kills the native backend and Vite by port, then `docker compose --profile app stop` (PostgreSQL, OpenSearch, demo). Volumes survive | End of session |
| `teardown.sh` | `stop.sh`, then removes Docker volumes, `.venv`, `web/node_modules`, `logs/`. Destructive, no prompt | `make teardown` — clean slate |
| `smoke_local.sh [pytest-args]` | Runs the e2e suite against :8080 — reuses a healthy backend or starts/stops its own. Exit 2 means PostgreSQL/OpenSearch aren't up | `make ci` runs it narrowed to one test; run it bare for the full suite (~90 s) |
| `load_precomputed_indices.py` | Bulk-loads `data/precomputed/*.parquet` into OpenSearch; refuses a dump whose mapping hash doesn't match `INDEX_MAPPING` | Called by `setup.py`; takes no arguments |
| `reset_demo_taxonomy.sh` | Re-arms the taxonomy demos (same code path as the UI's Restart button and `POST /api/admin/demo-reset`) | Between rehearsals |
| `pre-commit.sh` | black + isort + flake8 on staged `.py` files | Installed as `.git/hooks/pre-commit` by `setup.sh`; runs on every commit |

## The hook

`setup.sh` installs `pre-commit.sh` as `.git/hooks/pre-commit`, overwriting
only a hook it recognizes as its own. It blocks a commit whose staged Python
fails black, isort, or flake8 — fix with `.venv/bin/black . && .venv/bin/isort .`
and re-stage. There is no pre-push hook; `make ci` by hand is the gate.
