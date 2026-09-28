# Agentic Hybrid Search — run every target from langchain_agent/.
# `make` lists the targets; the `##` comment on a target line is its help text.

.DEFAULT_GOAL := help
.PHONY: help doctor setup dev stop teardown demo demo-down demo-reset test ci check smoke format-fix benchmark

VENV := .venv/bin
PY   := PYTHONPATH=. $(VENV)

help: ## List targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

# ---- Lifecycle ---------------------------------------------------------------

doctor: ## Check prerequisites (Docker, Ollama models, .venv, node_modules, LFS data)
	@bash scripts/doctor.sh

setup: ## First-time setup: Docker services, .venv, Ollama models, precomputed index load (~1-2 min)
	@bash scripts/setup.sh

dev: ## Start Postgres+OpenSearch, backend :8000, frontend :5173 in the background (logs/ has the output)
	@bash scripts/start.sh

stop: ## Stop backend/frontend/Docker; data volumes survive
	@bash scripts/stop.sh

teardown: ## DESTRUCTIVE: remove .venv, node_modules, Docker volumes, logs (no prompt)
	@bash scripts/teardown.sh

# ---- Demo --------------------------------------------------------------------

# The "app" compose profile bundles backend + built UI in one container. Needs
# one prior `make setup` (Postgres tables, OpenSearch data) and a native Ollama.
demo: ## Run backend+UI fully Dockerized on :8000 (Docker + native Ollama only)
	@cd .. && docker compose --profile app up -d --build
	@echo "Visit http://localhost:8000"

# `docker compose down` tears down every service in the project even with
# --profile, so scope to the one service with stop + rm.
demo-down: ## Stop the Dockerized app (leaves Postgres/OpenSearch running)
	@cd .. && docker compose stop app && docker compose rm -f app

demo-reset: ## Re-arm the taxonomy demo (tan->yellow) between rehearsals
	@bash scripts/reset_demo_taxonomy.sh

# ---- Gate --------------------------------------------------------------------
# There is no CI service; `make check` run locally is the only gate before a
# push. `ci` needs no live services (integration/e2e are import-checked with
# --collect-only only); `smoke` needs Docker up and starts a backend if none
# is on :8000.

test: ## Unit tests only (~30s, no services)
	@$(PY)/pytest tests/unit/ -q

ci: ## Static gate: black/isort/flake8/mypy, unit tests, integration+e2e collect, frontend test/lint/tsc/build
	@echo "[ci] black --check / isort --check-only"
	@$(VENV)/black --check .
	@$(VENV)/isort --check-only .
	@echo "[ci] flake8 / mypy"
	@$(VENV)/flake8 . --count
	@$(VENV)/mypy main.py
	@echo "[ci] pytest tests/unit/"
	@$(PY)/pytest tests/unit/ -q
	@echo "[ci] pytest --collect-only tests/integration/ tests/e2e/"
	@$(PY)/pytest --collect-only -q tests/integration/ tests/e2e/ > /dev/null
	@echo "[ci] frontend: vitest, eslint, tsc, build"
	@cd web && npm install --silent && npm run test && npm run lint && npx tsc --noEmit && npm run build
	@echo "ci passed — run 'make check' before pushing."

smoke: ## Search-intent WebSocket round-trip against a live backend (~15s)
	@bash scripts/smoke_local.sh -k test_search_intent_returns_results -q --tb=short

check: ci smoke ## THE pre-push gate: ci + smoke
	@echo "check passed — safe to push."

format-fix: ## Auto-format with black + isort
	@$(VENV)/black .
	@$(VENV)/isort .

# ---- Benchmark ---------------------------------------------------------------

benchmark: ## ESCI relevancy benchmark, 5000 queries; deterministic (~35 min) unless FULL=1 (LLM intent via Ollama)
	@$(PY)/python benchmarks/benchmark_esci.py --limit 5000 $(if $(FULL),--hard-only,--fast)
