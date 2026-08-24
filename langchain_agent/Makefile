.PHONY: help doctor setup test lint format clean run stop test-reranker test-hybrid test-query dev dev-api dev-web install-web ci ci-format ci-lint ci-test ci-tools benchmark-esci benchmark-esci-fast smoke-local smoke-local-quick

# Virtual environment — all Python/pip commands use this
VENV := .venv/bin

help:
	@echo "Agentic Hybrid Search - Development Commands"
	@echo ""
	@echo "Setup & Initialization:"
	@echo "  make doctor             - Check prerequisites and system health"
	@echo "  make setup              - Run complete system setup (database, models, data)"
	@echo "  make install-web        - Install web UI dependencies (npm install)"
	@echo ""
	@echo "Testing:"
	@echo "  make test               - Run all test suites"
	@echo "  make test-reranker      - Run reranker tests only"
	@echo "  make test-hybrid        - Run hybrid search tests only"
	@echo "  make test-query         - Run query evaluator tests only"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint               - Run code quality checks (pylint)"
	@echo "  make format             - Format code with black"
	@echo "  make type-check         - Check types with mypy (if installed)"
	@echo ""
	@echo "Benchmarking & Performance:"
	@echo "  make benchmark-esci     - ESCI relevancy benchmark (full, with adaptive intent)"
	@echo "  make benchmark-esci-fast- ESCI benchmark (fast, deterministic, no LLM alpha)"
	@echo "  make smoke-local        - Local smoke test suite (~90s)"
	@echo "  make smoke-local-quick  - Focused search-intent smoke test (~13s, pre-commit gate)"
	@echo ""
	@echo "Pre-push CI gate (mirrors GitHub Actions build-deploy.yml):"
	@echo "  make ci                 - Run all CI checks locally before push"
	@echo "  make ci-frontend        - Frontend tests, lint, and type-check only"
	@echo "  make ci-docker          - Validate Dockerfile builds (no push)"
	@echo "  make format-fix         - Auto-fix black + isort formatting"
	@echo ""
	@echo "Running:"
	@echo "  make run                - Start the CLI agent"
	@echo "  make dev                - Start full dev environment (API + Web UI)"
	@echo "  make dev-api            - Start FastAPI backend only (port 8000)"
	@echo "  make dev-web            - Start React frontend only (port 5173)"
	@echo "  make stop               - Stop all running services"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              - Remove generated files and caches"
	@echo "  make clean-db           - Reset PostgreSQL database (WARNING: removes all data)"
	@echo ""

doctor:
	@bash scripts/doctor.sh

setup:
	@echo "[1/1] Running complete setup..."
	PYTHONPATH=. $(VENV)/python setup.py

test:
	@echo "[1/3] Running reranker tests..."
	PYTHONPATH=. $(VENV)/python test_reranker.py || exit 1
	@echo ""
	@echo "[2/3] Running hybrid search tests..."
	PYTHONPATH=. $(VENV)/python test_hybrid_search.py || exit 1
	@echo ""
	@echo "[3/3] Running query evaluator tests..."
	PYTHONPATH=. $(VENV)/python test_query_evaluator.py || exit 1
	@echo ""
	@echo "✓ All tests passed!"

test-reranker:
	@echo "Running reranker tests..."
	PYTHONPATH=. $(VENV)/python test_reranker.py

test-hybrid:
	@echo "Running hybrid search tests..."
	PYTHONPATH=. $(VENV)/python test_hybrid_search.py

test-query:
	@echo "Running query evaluator tests..."
	PYTHONPATH=. $(VENV)/python test_query_evaluator.py

lint:
	@echo "Running code quality checks..."
	$(VENV)/pylint main.py config.py setup.py --disable=missing-docstring || true

format:
	@echo "Formatting code with black..."
	$(VENV)/black main.py config.py setup.py test_*.py

type-check:
	@echo "Checking types with mypy..."
	$(VENV)/mypy main.py config.py --ignore-missing-imports --check-untyped-defs || true

# ----------------------------------------------------------------------------
# CI parity: run *exactly* what build-deploy.yml runs in GitHub Actions.
# `make ci` is the pre-push gate — if this passes, the GCP build/deploy
# pipeline will too.
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

ci-lint: ci-tools
	@echo "[CI] flake8 . --count"
	@$(VENV)/flake8 . --count
	@echo "[CI] mypy main.py"
	@$(VENV)/mypy main.py --ignore-missing-imports --check-untyped-defs || true

ci-test: ci-tools
	@echo "[CI] pytest tests/unit/"
	@PYTHONPATH=. $(VENV)/pytest tests/unit/ -q
	@echo "[CI] pytest --collect-only tests/integration/ tests/e2e/ (import + signature check)"
	@PYTHONPATH=. $(VENV)/pytest --collect-only -q tests/integration/ tests/e2e/ > /dev/null

ci-frontend:
	@echo "[CI] npm test (vitest)"
	@cd web && npm ci --silent && npm run test
	@echo "[CI] npm run lint (eslint)"
	@cd web && npm run lint
	@echo "[CI] tsc --noEmit"
	@cd web && npx tsc --noEmit
	@echo "[CI] npm run build (production build)"
	@cd web && npm run build

ci-docker:
	@echo "[CI] docker build (no push)"
	@docker build -f Dockerfile -t agentic-hybrid-search:ci-check .. --quiet
	@echo "✓ Docker build succeeded"

# Integration test gate — actually executes tests/integration/, not just
# collect-only. Requires PostgreSQL + OpenSearch already running locally:
#     docker compose up -d   (from repo root)
# Slower (~30–120 s) so kept out of `make ci` and PR gating; runs in the
# nightly GitHub Actions cron (.github/workflows/integration-nightly.yml).
ci-integration: ci-tools
	@echo "[CI] pytest tests/integration/ -m 'not slow'"
	@PYTHONPATH=. $(VENV)/pytest tests/integration/ -m 'not slow' -q --timeout=120

# Full pre-push gate. Mirrors GitHub Actions build-deploy.yml jobs:
#   lint-backend   → ci-format + ci-lint
#   unit-tests     → ci-test
#   frontend-tests → ci-frontend
# Integration tests and docker build are intentionally omitted from the
# default gate (they need live services / are slow). Run individually:
#   make ci-docker    — validate the Dockerfile builds cleanly
# Integration tests require: docker compose up -d (PG + OpenSearch)
ci: ci-format ci-lint ci-test ci-frontend
	@echo ""
	@echo "✅ Local CI gate passed — safe to push."

# Run a focused smoke test against the local backend. Catches the search-intent
# WebSocket regression class (deadlocks, agent_complete never emitted) without
# needing a full Cloud Run deployment.
# Usage:
#   make smoke-local         — full smoke suite (~90s)
#   make smoke-local-quick   — search intent only (~20s; pre-commit gate)
smoke-local:
	@bash scripts/smoke_local.sh

smoke-local-quick:
	@bash scripts/smoke_local.sh -k test_search_intent_returns_results -q --tb=short

benchmark-esci-fast:
	@echo "Running ESCI relevancy benchmark (fast mode, deterministic)..."
	PYTHONPATH=. $(VENV)/python benchmark_esci.py --limit 5000 --hard-only --fast

benchmark-esci:
	@echo "Running ESCI relevancy benchmark (full mode, with Gemini intent classification)..."
	PYTHONPATH=. $(VENV)/python benchmark_esci.py --limit 5000 --hard-only

format-fix:
	@echo "Auto-fixing formatting (black + isort) across the whole package..."
	@$(VENV)/black .
	@$(VENV)/isort .
	@echo "✓ Formatted. Re-run 'make ci' to verify."

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
	@echo "✓ All services stopped"

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
