.PHONY: help doctor setup reindex reindex-products seed-taxonomy demo-reset test lint format-fix clean run stop teardown dev dev-api dev-web install-web ci ci-format ci-test ci-frontend ci-tools benchmark-esci benchmark-esci-fast smoke check clean-db

# Virtual environment — all Python/pip commands use this
VENV := .venv/bin

help:
	@echo "Agentic Hybrid Search - Development Commands"
	@echo ""
	@echo "Setup & Initialization:"
	@echo "  make doctor             - Check prerequisites and system health"
	@echo "  make setup              - Run complete system setup (Docker + database, models, data)"
	@echo "  make install-web        - Install web UI dependencies (npm install)"
	@echo ""
	@echo "Data (Lucille ETL):"
	@echo "  make reindex            - Full local reindex: products + judgments (bash scripts/lucille_ingest.sh)"
	@echo "  make reindex-products   - Products only (--skip-judgments), what the enrichment flywheel runs"
	@echo "  make seed-taxonomy      - Rediscover color/material taxonomy + products pass (DESTRUCTIVE: wipes agent-learned mappings)"
	@echo "  make demo-reset         - Re-arm the taxonomy demo (restore tan->yellow + reindex). Run BETWEEN rehearsals."
	@echo ""
	@echo "Testing & Pre-push Gate (local only -- no GitHub Actions, issue #113):"
	@echo "  make check              - Run this before every push or PR merge: ci + smoke"
	@echo "  make ci                 - Fast static gate, no live services needed (format, lint, unit, frontend)"
	@echo "  make test               - Run the unit suite only (tests/unit/, no services needed)"
	@echo "  make lint               - Run the lint gate (flake8 + mypy), same as ci"
	@echo "  make format-fix         - Auto-fix black + isort formatting"
	@echo "  make smoke        - Focused search-intent smoke test (~13-20s, needs Docker + backend)"
	@echo ""
	@echo "Benchmarking & Performance:"
	@echo "  make benchmark-esci     - ESCI relevancy benchmark (full, with adaptive intent)"
	@echo "  make benchmark-esci-fast- ESCI benchmark (fast, deterministic, no LLM alpha)"
	@echo ""
	@echo "Running:"
	@echo "  make run                - Start the CLI agent"
	@echo "  make dev                - Start full dev environment (Docker + API + Web UI)"
	@echo "  make dev-api            - Start FastAPI backend only (port 8000; Docker must already be up)"
	@echo "  make dev-web            - Start React frontend only (port 5173)"
	@echo "  make stop               - Stop all running services (processes + Docker, containers persist for a fast restart)"
	@echo ""
	@echo "Cleanup:"
	@echo "  make teardown           - Full destructive cleanup (delegates to scripts/teardown.sh: removes .venv, node_modules, Docker volumes)"
	@echo "  make clean              - Remove generated files and caches"
	@echo "  make clean-db           - Reset PostgreSQL database (WARNING: removes all data)"
	@echo ""

doctor:
	@bash scripts/doctor.sh

reindex:
	@bash scripts/lucille_ingest.sh

reindex-products:
	@bash scripts/lucille_ingest.sh --skip-judgments

setup:
	@bash scripts/setup.sh

demo-reset:
	@bash scripts/reset_demo_taxonomy.sh

seed-taxonomy:
	@echo "Rediscovering color/material taxonomy from scratch (wipes agent-learned mappings), then re-running products..."
	bash scripts/lucille_ingest.sh --seed-taxonomy --skip-judgments

test:
	@echo "Running unit tests (no services required)..."
	PYTHONPATH=. $(VENV)/pytest tests/unit/ -q

lint: ci-tools
	@echo "[lint] flake8 . --count"
	$(VENV)/flake8 . --count
	@echo "[lint] mypy main.py"
	$(VENV)/mypy main.py

# ----------------------------------------------------------------------------
# `make check` (below) is the pre-push gate -- there is no GitHub Actions CI
# (issue #113), so it's the only check that runs. `ci`'s ci-test step is not
# full coverage: unit tests run for real, but integration/e2e only get
# --collect-only here (import + signature check) -- running them against
# real services needs `docker compose up -d` + `make dev-api` first (see
# tests/integration/README.md). A green `make ci` means lint/types/unit are
# safe; it does NOT guarantee integration/e2e pass -- run those manually.
# ----------------------------------------------------------------------------

ci-tools:
	@echo "Installing CI lint toolchain into .venv..."
	@$(VENV)/pip install -q --upgrade pip
	@$(VENV)/pip install -q flake8 black isort mypy types-requests pytest pytest-asyncio pytest-cov pytest-timeout pytest-xdist psutil

ci-format: ci-tools
	@echo "[CI] black --check ."
	@$(VENV)/black --check .
	@echo "[CI] isort --check-only ."
	@$(VENV)/isort --check-only .

ci-test: ci-tools
	@echo "[CI] pytest tests/unit/"
	@PYTHONPATH=. $(VENV)/pytest tests/unit/ -q
	@echo "[CI] pytest --collect-only tests/integration/ tests/e2e/ (import + signature check)"
	@PYTHONPATH=. $(VENV)/pytest --collect-only -q tests/integration/ tests/e2e/ > /dev/null

ci-frontend:
	@echo "[CI] npm test (vitest)"
	@cd web && npm install --silent && npm run test
	@echo "[CI] npm run lint (eslint)"
	@cd web && npm run lint
	@echo "[CI] tsc --noEmit"
	@cd web && npx tsc --noEmit
	@echo "[CI] npm run build (production build)"
	@cd web && npm run build

# Fast static gate (no GitHub Actions CI to mirror -- issue #113): format,
# lint, unit tests, frontend tests/lint/build. Needs no live services --
# integration/e2e only get --collect-only here (import + signature check).
# `make check` below is the full pre-push gate; use `make ci` on its own for
# quick iterative feedback while coding.
ci: ci-format lint ci-test ci-frontend
	@echo ""
	@echo "✅ ci passed (no live services) — run 'make check' before pushing."

# THE single command to run before every push or PR merge: the full `ci`
# gate (format, lint, unit tests via ci-test, frontend tests/lint/build)
# plus a real request/response round-trip against a running backend via
# smoke. Requires Docker services up (`docker compose up -d` from
# repo root); smoke_local.sh starts its own uvicorn if one isn't already
# running on :8000.
check: ci smoke
	@echo ""
	@echo "✅ check passed — CI gate + smoke test, safe to push."

# Focused smoke test against the local backend (~13-20s). Catches the
# search-intent WebSocket regression class (deadlocks, agent_complete never
# emitted) -- the one check `ci` can't cover (a real running backend). This
# is what `make check` runs; there is no separate "full" Make target for the
# broader regression suite -- run it manually when you want it:
#   bash scripts/smoke_local.sh
smoke:
	@bash scripts/smoke_local.sh -k test_search_intent_returns_results -q --tb=short

benchmark-esci-fast:
	@echo "Running ESCI relevancy benchmark (fast mode, deterministic)..."
	PYTHONPATH=. $(VENV)/python benchmarks/benchmark_esci.py --limit 5000 --fast

benchmark-esci:
	@echo "Running ESCI relevancy benchmark (full mode, with Gemini intent classification)..."
	PYTHONPATH=. $(VENV)/python benchmarks/benchmark_esci.py --limit 5000 --hard-only

format-fix:
	@echo "Auto-fixing formatting (black + isort) across the whole package..."
	@$(VENV)/black .
	@$(VENV)/isort .
	@echo "✓ Formatted. Re-run 'make ci' to verify, or 'make check' before pushing."

run:
	@echo "Starting Agentic Hybrid Search agent..."
	PYTHONPATH=. $(VENV)/python main.py

stop:
	@echo "Stopping all services..."
	@echo "  Stopping Python processes (graceful)..."
	pkill -15 -f "python.*main.py" || true
	pkill -15 -f "uvicorn" || true
	@sleep 2
	@echo "  Force stopping any remaining processes..."
	pkill -9 -f "python.*main.py" || true
	pkill -9 -f "uvicorn" || true
	@echo "  Stopping npm/Node processes..."
	pkill -f "npm.*dev" || true
	pkill -f "vite" || true
	@echo "  Stopping Docker services (PostgreSQL + OpenSearch)..."
	@cd .. && docker compose stop
	@echo "✓ All services stopped"

teardown:
	@echo "Delegating to scripts/teardown.sh (removes .venv, node_modules, Docker volumes — destructive)..."
	@bash scripts/teardown.sh

clean:
	@echo "Cleaning up generated files..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*~" -delete
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	@echo "✓ Cleanup complete"

clean-db:
	@echo "⚠ WARNING: This will delete ALL data in PostgreSQL database!"
	@echo "Press Ctrl+C to cancel, or continue..."
	@sleep 3
	PYTHONPATH=. $(VENV)/python -c "from setup import drop_all_tables; drop_all_tables()" || echo "Database cleanup failed or database not initialized"
	@echo "✓ Database cleaned"

# Web UI development
install-web:
	@echo "Installing web UI dependencies..."
	cd web && npm install

dev-api:
	@echo "Starting FastAPI backend on http://localhost:8000..."
	@echo "API docs available at http://localhost:8000/docs"
	PYTHONPATH=. $(VENV)/uvicorn api.main:app --reload --port 8000

dev-web:
	@echo "Starting React frontend on http://localhost:5173..."
	cd web && npm run dev

dev:
	@echo "Ensuring Docker services (PostgreSQL + OpenSearch) are up..."
	@cd .. && docker compose up -d --wait
	@echo ""
	@echo "Starting full development environment..."
	@echo "  Backend:  http://localhost:8000"
	@echo "  Frontend: http://localhost:5173"
	@echo ""
	@echo "Run in separate terminals:"
	@echo "  Terminal 1: make dev-api"
	@echo "  Terminal 2: make dev-web"
	@echo ""
	@echo "Or start both now (backend in background):"
	@( PYTHONPATH=. $(VENV)/uvicorn api.main:app --reload --port 8000 & ) && cd web && npm run dev

.SILENT: help
