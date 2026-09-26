# Local Development Setup

Get the project running on your machine for development.

**Parent:** [Contributing Guide](README.md)

---

## What You're Setting Up

- **Backend**: FastAPI server on `localhost:8000` (Python 3.14+, .venv)
- **Frontend**: React + Vite dev server on `localhost:5173` (Node.js 24+)
- **Services**: PostgreSQL (checkpoints) + OpenSearch (search index) in Docker
- **Data**: full ESCI product corpus (158,637 products), embedded at ingest time via Lucille + Ollama

**One-time setup:** first-time setup, including the full ~158K-product ingest, takes roughly 35-40 minutes on an M4 Max  
**Daily workflow:** `./scripts/start.sh` or `make dev`

---

## Prerequisites

Verify each tool is installed. The **Why** column explains what it's used for.

| Tool | Min Version | Why | Verify |
|------|-------------|-----|--------|
| **Docker Desktop** | 4.x | Runs PostgreSQL + OpenSearch containers locally | `docker --version` |
| **Python** | 3.14+ | Backend venv (setup.sh creates it) | `python3 --version` |
| **Node.js** | 24+ | React frontend and Vite dev server | `node --version` |
| **Java** | 21+ | Lucille ETL for product ingestion (only needed if `LUCILLE_USE_DOCKER=false`) | `java -version` |
| **Maven** | 3.8+ | Build tool for Lucille ETL (only needed if `LUCILLE_USE_DOCKER=false`) | `mvn --version` |
| **Ollama** | — | Local LLM (`qwen3.6:35b-a3b-q4_K_M`) and embeddings (`nomic-embed-text`); no cloud API key | Get from [ollama.com](https://ollama.com/) |

### Installing Prerequisites

**macOS (via Homebrew):**
```bash
brew install docker
brew install python@3.14
brew install node
brew install ollama
brew install openjdk@21  # only needed for LUCILLE_USE_DOCKER=false
brew install maven       # only needed for LUCILLE_USE_DOCKER=false
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
| 6: Ingest | Initializes DB + indexes the full ESCI product corpus (158,637 products), embedded via Lucille + Ollama | ~35-40 min |

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

You have three ways to start the development servers, depending on whether Docker is already running:

### Option A: Everything Fresh (Most Common)

```bash
./scripts/start.sh
```

Starts Docker containers (Postgres, OpenSearch), backend server, and frontend dev server. All in one command.

### Option B: Docker Already Running

```bash
make dev
```

Faster — assumes Docker is up. Starts just the backend and frontend. (Same as `./scripts/start.sh` but skips Docker startup.)

### Option C: One Server at a Time

```bash
make dev-api     # Backend only (:8000)
make dev-web     # Frontend only (:5173, in a separate terminal)
```

---

## Stopping Servers

**Which command should I use?**

| Scenario | Command | Result | What Stays |
|----------|---------|--------|-----------|
| "I'm done for the day" | `./scripts/stop.sh` | Kills backend + frontend, Docker stays up | PostgreSQL data, OpenSearch index, .venv, node_modules |
| "I'm switching projects" | `./scripts/stop.sh` | Same as above | Everything — quick to resume with `./scripts/start.sh` |
| "I want a clean slate" | `./scripts/teardown.sh` | 🚨 **REMOVES everything below** | Nothing — you'll need to run `./scripts/setup.sh` again |
| | | Database deleted, index deleted, .venv deleted, node_modules deleted | |

**Pause development (keep all data):**
```bash
./scripts/stop.sh
```

Kills the backend and frontend processes. Docker containers stay running, so your Postgres data and OpenSearch index persist. Use this when you're done for the day but want to resume tomorrow with `./scripts/start.sh`.

**Full teardown (DESTRUCTIVE — removes all data):**
```bash
./scripts/teardown.sh
```

⚠️  **This is destructive.** Removes Docker containers + volumes, deletes `.venv`, deletes `node_modules`. Your PostgreSQL database and OpenSearch index are deleted permanently. Use this only if you want a clean slate. You'll need to run `./scripts/setup.sh` again (takes ~35-40 min plus the Ollama model download).

---

## Services and State Machine

Understanding when services are running helps you reason about what commands to use:

| State | Services | Docker | How You Got Here | PostgreSQL | OpenSearch | What to Do Next |
|-------|----------|--------|------------------|------------|-----------|-----------------|
| **Fresh install** | None | ⚠️ Off | Just cloned repo | ❌ None | ❌ None | Run `./scripts/setup.sh` |
| **Dev session** | Backend + Frontend | ✅ On | After `start.sh` or `make dev` | ✅ Active | ✅ Active | Edit code, run tests |
| **Paused** | None | ✅ On | After `stop.sh` | ✅ Data kept | ✅ Index kept | Run `./scripts/start.sh` to resume |
| **Torn down** 🚨 | None | ❌ Off | After `teardown.sh` | ❌ **Deleted** | ❌ **Deleted** | Run `./scripts/setup.sh` to rebuild |

**Critical distinction:**
- **`stop.sh`** = "pause" — kill processes only. Docker + all data stays. Resumable with `start.sh`.
- **`teardown.sh`** = "destroy" — delete Docker containers + volumes. All data is **permanently deleted**. Requires full `setup.sh` to rebuild.

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

**Good news:** The Makefile sets this automatically. So these work fine:
```bash
make lint        # flake8 + mypy (black/isort check-only live in `make ci`; use `make format-fix` to auto-fix)
make ci          # fast static gate, no live services needed
make check       # the pre-push gate: ci + smoke test
make test        # unit tests
make smoke # smoke test
```

**For ad-hoc commands**, remember to set PYTHONPATH.

---

## Running Tests

| Task | Command | How Long |
|------|---------|----------|
| Unit tests (no services needed) | `PYTHONPATH=. pytest tests/unit/` | ~5s |
| Smoke test | `make smoke` | ~13-20s |
| Fast static gate (no live services) | `make ci` | ~40-45s |
| Full pre-push gate | `make check` | `ci` + smoke test |
| Frontend tests | `npm run test` (from `web/`) | ~5s |
| Linting only | `make lint` | ~15s |

The **smoke test** (`make smoke`) runs a focused search-intent regression test against your local backend. Use `make check` before pushing a change to catch any integration bugs; run `bash scripts/smoke_local.sh` directly for the full 21-test suite when you want deeper coverage (no dedicated Make target for it).

---

## Makefile Quick Reference

Common targets for daily development:

| Target | What It Does | When to Use |
|--------|--------------|-------------|
| `make doctor` | Verify setup health (checks Docker, services, deps) | After setup.sh completes |
| `make dev` | Start backend + frontend (Docker must be up) | Daily development |
| `make dev-api` | Start backend only | Testing backend in isolation |
| `make dev-web` | Start frontend only | Testing frontend in isolation |
| `make lint` | Run flake8 + mypy (same checks as `ci`'s lint step) | Before committing |
| `make test` | Run unit tests | Before pushing |
| `make format-fix` | Auto-format code (black + isort) | Fix linting errors |
| `make ci` | Fast static gate (lint + tests + frontend build), no live services | Iterative coding |
| `make smoke` | Smoke test (search intent only) | Part of `make check` |
| `make check` | **The pre-push gate**: `ci` + smoke test | Before every push or PR merge |

See `Makefile` for all targets. See [Testing.md](testing.md) for the test pyramid.

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

### setup.sh fails at Lucille ETL step

**Cause:** Java or Maven not installed.

**Fix:**
```bash
brew install openjdk@21
brew install maven
# Then re-run:
./scripts/setup.sh
```

---

### OpenSearch returns 0 results

**Cause:** Lucille ETL ingest failed or was skipped.

**Fix:** Re-run the ingest:
```bash
cd langchain_agent
bash scripts/lucille_ingest.sh --reset-index
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
- **Test locally:** Run `make check` before pushing.
- **Read more:** See [Testing.md](testing.md) for test strategies, [Code Patterns](code-patterns.md) for backend/frontend conventions, and [PR Process](pr-process.md) for commit and PR guidance.

---

**Questions?** Check [ARCHITECTURE.md](../../langchain_agent/ARCHITECTURE.md) for system design, or [docs/integration/](../integration/) for API reference.
