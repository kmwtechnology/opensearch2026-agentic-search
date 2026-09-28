# Local Development Setup

Get the project running on your machine for development.

**Parent:** [Contributing Guide](README.md)

---

## What You're Setting Up

- **Backend**: FastAPI server on `localhost:8000` (Python 3.14+, .venv)
- **Frontend**: React + Vite dev server on `localhost:5173` (Node.js 24+)
- **Services**: PostgreSQL (checkpoints) + OpenSearch (search index) in Docker
- **Data**: full ESCI product corpus (158,637 products), bulk-loaded from a committed precomputed export — no live ingest pipeline (see `data/README.md`)

**One-time setup:** first-time setup, including bulk-loading the precomputed corpus, takes roughly 1-2 minutes (plus Ollama model pulls)  
**Daily workflow:** `./scripts/start.sh` or `make dev`

---

## Prerequisites

Verify each tool is installed. The **Why** column explains what it's used for.

| Tool | Min Version | Why | Verify |
|------|-------------|-----|--------|
| **Docker Desktop** | 4.x | Runs PostgreSQL + OpenSearch containers locally | `docker --version` |
| **Python** | 3.14+ | Backend venv (setup.sh creates it) | `python3 --version` |
| **Node.js** | 24+ | React frontend and Vite dev server | `node --version` |
| **Ollama** | — | Local LLM (`qwen3.6:35b-a3b-q4_K_M`) and embeddings (`nomic-embed-text`); no cloud API key | Get from [ollama.com](https://ollama.com/) |

### Installing Prerequisites

**macOS (via Homebrew):**
```bash
brew install docker
brew install python@3.14
brew install node
brew install ollama
```

**Ubuntu/Debian:**
```bash
# Docker: https://docs.docker.com/engine/install/ubuntu/
sudo apt-get install docker.io
sudo usermod -aG docker $USER

python3 --version  # Should be 3.14+ (may need deadsnakes PPA)
sudo apt-get install npm nodejs  # Node 24+ may require NodeSource repo

sudo apt-get install openjdk-21-jdk
sudo apt-get install maven
```

**Windows:**
- Docker Desktop: https://www.docker.com/products/docker-desktop
- Python 3.14+: https://www.python.org/downloads/
- Node.js 24+: https://nodejs.org/ (use LTS)
- Java 21+: https://www.oracle.com/java/technologies/downloads/
- Maven: https://maven.apache.org/download.cgi

---

## One-Time Setup (~35-40 min + Ollama model download)

### Step 1: Clone the Repository

```bash
git clone https://github.com/kmwtechnology/opensearch2026-agentic-search.git
cd opensearch2026-agentic-search/langchain_agent
```

### Step 2: Configure Environment

```bash
cp .env.example .env
```

No API key is needed — everything runs against a local Ollama server.
`setup.sh` checks that Ollama is installed and running, and pulls any
missing models automatically.

### Step 3: Run One-Time Setup

```bash
./scripts/setup.sh
```

This script handles all initialization in 6 phases:

| Phase | What Happens | Time |
|-------|--------------|------|
| 1: Preq Checks | Verifies Docker, Python, Node, Ollama (installed + running) | instant |
| 2: Ollama models | Pulls any missing Ollama models (~23 GB) | varies |
| 3: Python venv | Creates `.venv`, installs dependencies (pip install) | 3–5 min |
| 4: Node deps | Installs frontend packages (npm install) | 1–2 min |
| 5: Docker up | Starts Postgres, OpenSearch containers | ~30s |
| 6: Load corpus | Initializes DB + bulk-loads the full ESCI product corpus (158,637 products) from a committed precomputed export | ~1-2 min |

**At the end**, the script prints the app URLs. There is no login gate — the app is open to any same-origin caller, so you'll go straight from setup to using the app with no login step.

### Step 4: Verify the Setup

```bash
make doctor
```

This checks that all services are healthy. You should see: "All checks passed ✓"

---

## Your First Run

After setup completes, start the development servers:

```bash
./scripts/start.sh
```

You'll see output like:
```
✓ Backend running on http://localhost:8000
✓ Frontend running on http://localhost:5173
```

Then:
1. **Visit the app:** Open http://localhost:5173 in your browser
2. **Try a search:** "Find wireless headphones under $100" — there is no login gate, so you go straight to the app

---

## Daily Development Workflow

```bash
make dev        # same as ./scripts/start.sh
```

Starts the Docker containers (Postgres, OpenSearch) if they aren't up, waits for their healthchecks, then starts the backend and frontend in the background with output in `logs/backend.log` and `logs/frontend.log`. Need just the backend? `PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload --port 8000`.

---

## Stopping Servers

**Which command should I use?**

| Scenario | Command | Result | What Stays |
|----------|---------|--------|-----------|
| "I'm done for the day" | `./scripts/stop.sh` | Kills backend + frontend, stops the Docker containers | PostgreSQL data, OpenSearch index, .venv, node_modules |
| "I'm switching projects" | `./scripts/stop.sh` | Same as above | Everything — quick to resume with `make dev` |
| "I want a clean slate" | `make teardown` | 🚨 **REMOVES everything below** | Nothing — you'll need to run `make setup` again |
| | | Database deleted, index deleted, .venv deleted, node_modules deleted | |

**Pause development (keep all data):**
```bash
./scripts/stop.sh
```

Kills the backend and frontend processes and stops the Docker containers; the volumes stay, so your Postgres data and OpenSearch index persist. Use this when you're done for the day but want to resume tomorrow with `make dev`.

**Full teardown (DESTRUCTIVE — removes all data):**
```bash
make teardown
```

⚠️  **This is destructive.** Removes Docker containers + volumes, deletes `.venv`, deletes `node_modules`. Your PostgreSQL database and OpenSearch index are deleted permanently. Use this only if you want a clean slate. You'll need to run `./scripts/setup.sh` again (~1-2 min to reload the precomputed index, plus the Ollama model download on a first install).

---

## Services and State Machine

Understanding when services are running helps you reason about what commands to use:

| State | Services | Docker | How You Got Here | PostgreSQL | OpenSearch | What to Do Next |
|-------|----------|--------|------------------|------------|-----------|-----------------|
| **Fresh install** | None | ⚠️ Off | Just cloned repo | ❌ None | ❌ None | Run `make setup` |
| **Dev session** | Backend + Frontend | ✅ On | After `make dev` | ✅ Active | ✅ Active | Edit code, run tests |
| **Paused** | None | ⏸ Stopped | After `./scripts/stop.sh` | ✅ Data kept | ✅ Index kept | Run `make dev` to resume |
| **Torn down** 🚨 | None | ❌ Removed | After `make teardown` | ❌ **Deleted** | ❌ **Deleted** | Run `make setup` to rebuild |

**Critical distinction:**
- **`./scripts/stop.sh`** = "pause" — kill processes and stop containers. Volumes and all data stay. Resumable with `make dev`.
- **`make teardown`** = "destroy" — delete Docker containers + volumes. All data is **permanently deleted**. Requires `make setup` to rebuild.

---

## PYTHONPATH — The Most Common Gotcha

All backend Python commands from the `langchain_agent/` directory need `PYTHONPATH=.` prefix:

```bash
# ✅ Correct
PYTHONPATH=. pytest tests/unit/
PYTHONPATH=. python main.py

# ❌ Wrong — causes ModuleNotFoundError: No module named 'config'
pytest tests/unit/
python main.py
```

**Why?** The backend imports relative to `langchain_agent/` (e.g., `from config import ...`). Without `PYTHONPATH=.`, Python doesn't know where to find `config`.

**Good news:** the Makefile sets it for you:
```bash
make ci          # the pre-push gate: format, flake8, mypy, unit tests, frontend, then a live smoke test
```

**For ad-hoc commands**, remember to set PYTHONPATH.

---

## Running Tests

| Task | Command | How Long |
|------|---------|----------|
| Unit tests (no services needed) | `PYTHONPATH=. pytest tests/unit/` | ~5s |
| The pre-push gate (everything, incl. a live smoke test) | `make ci` | ~1-2 min |
| Frontend tests | `npm run test` (from `web/`) | ~5s |
| Full e2e suite | `bash scripts/smoke_local.sh` | ~90s |

`make ci` ends with one focused search-intent smoke test against your local backend (it brings Docker up itself). Run `bash scripts/smoke_local.sh` directly for the full e2e suite when you want deeper coverage (no Make target for it, on purpose).

---

## Makefile Quick Reference

The Makefile has exactly six targets (bare `make` runs `doctor`):

| Target | What It Does | When to Use |
|--------|--------------|-------------|
| `make doctor` | Verify setup health (Docker, Ollama models, .venv, node_modules, LFS data) | After setup, or when something's off |
| `make setup` | First-time setup: Docker services, .venv, models, precomputed index load | Fresh clone |
| `make dev` | Start Docker services, then backend + frontend in the background | Daily development |
| `make demo` | Backend + UI in one Docker container on :8000 | Presenting |
| `make ci` | **The pre-push gate**: lint, unit tests, frontend build, live smoke test | Before every push |
| `make teardown` | DESTRUCTIVE: remove .venv, node_modules, Docker volumes | Clean slate |

Everything else is a direct command, listed in the Makefile header: `./scripts/stop.sh`, `docker compose stop app`, `./scripts/reset_demo_taxonomy.sh`, `PYTHONPATH=. pytest tests/unit/`, `black . && isort .`, `bash scripts/smoke_local.sh`, and the benchmark. See [Testing.md](testing.md) for the test pyramid.

---

## Common First-Run Issues

### ModuleNotFoundError: No module named 'config'

**Cause:** Missing `PYTHONPATH=.` when running Python directly.

**Fix:**
```bash
export PYTHONPATH=.
# Or prefix each command:
PYTHONPATH=. pytest tests/unit/
```

---

### Docker daemon is not running

**Cause:** Docker Desktop is installed but not started.

**Fix:** Open Docker Desktop and wait for the whale icon to appear in your menu bar. Then retry `./scripts/start.sh`.

---

### Port 8000 already in use

**Cause:** Leftover backend process from a previous run.

**Fix:**
```bash
./scripts/stop.sh
# Then retry:
./scripts/start.sh
```

Or manually kill:
```bash
lsof -i :8000  # Find the process ID
kill -9 <PID>
```

---

### Port 5432 already in use (PostgreSQL)

**Cause:** You have a local PostgreSQL running (not in Docker).

**Fix:** Either stop the local Postgres or change the port in `.env`:
```bash
# Stop local Postgres (macOS)
brew services stop postgresql

# Or use a different port in .env
POSTGRES_PORT=5433
```

---

### setup.sh fails at the corpus load step

**Cause:** `data/precomputed/` is missing (Git LFS objects not pulled).

**Fix:**
```bash
git lfs pull
# Then re-run:
./scripts/setup.sh
```

---

### OpenSearch returns 0 results

**Cause:** the precomputed corpus load failed or was skipped.

**Fix:** Re-run the load:
```bash
cd langchain_agent
PYTHONPATH=. python scripts/load_precomputed_indices.py --reset-index
```

Wait 5–10 seconds, then try a search again.

---

### Port 5173 already in use (frontend)

**Cause:** Leftover frontend dev server from a previous run.

**Fix:**
```bash
./scripts/stop.sh
./scripts/start.sh
```

---

## Next Steps

- **Write code:** Use `make dev` to start the servers. Changes auto-reload in both backend (uvicorn --reload) and frontend (Vite HMR).
- **Test locally:** Run `make ci` before pushing.
- **Read more:** See [Testing.md](testing.md) for test strategies, [Code Patterns](code-patterns.md) for backend/frontend conventions, and [PR Process](pr-process.md) for commit and PR guidance.

---

**Questions?** Check [ARCHITECTURE.md](../../langchain_agent/ARCHITECTURE.md) for system design, or [docs/integration/](../integration/) for API reference.
