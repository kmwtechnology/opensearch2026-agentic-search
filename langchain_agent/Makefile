# Agentic Hybrid Search — run from langchain_agent/. Six targets:
#   doctor    check prerequisites (Docker, Ollama models, .venv, node_modules, LFS data)
#   setup     first-time: Docker services, .venv, Ollama models, precomputed index load (~1-2 min)
#   dev       Postgres+OpenSearch, backend :8000, frontend :5173 in the background (logs/)
#   demo      backend+UI in one container on :8000 (Docker + native Ollama only)
#   ci        THE pre-push gate: format/lint/types, unit tests, collect-only integration+e2e,
#             frontend test/lint/tsc/build, then a live smoke round-trip (brings Docker up)
#   teardown  DESTRUCTIVE: .venv, node_modules, Docker volumes, logs
#
# Not targets, on purpose:
#   stop dev            ./scripts/stop.sh                  (processes + containers; data survives)
#   stop demo           (cd .. && docker compose stop app)
#   re-arm the demo     ./scripts/reset_demo_taxonomy.sh   (or the UI's Restart button)
#   unit tests only     PYTHONPATH=. .venv/bin/pytest tests/unit/
#   auto-format         .venv/bin/black . && .venv/bin/isort .
#   full e2e suite      bash scripts/smoke_local.sh
#   benchmark           PYTHONPATH=. .venv/bin/python benchmarks/benchmark_esci.py --limit 5000 --fast
#                       (--hard-only instead of --fast for LLM intent classification)

.DEFAULT_GOAL := doctor
.PHONY: doctor setup dev demo ci teardown

VENV := .venv/bin
PY   := PYTHONPATH=. $(VENV)

doctor:
	@bash scripts/doctor.sh

setup:
	@bash scripts/setup.sh

dev:
	@bash scripts/start.sh

# The "app" compose profile bundles backend + built UI in one container. Needs
# one prior `make setup` (Postgres tables, OpenSearch data) and a native Ollama.
# Stop a native `make dev` backend first — both want :8000.
demo:
	@cd .. && docker compose --profile app up -d --build
	@echo "Visit http://localhost:8000"

# No CI service exists; this is the only gate before a push. Static steps
# first (fail fast, no services), then Docker comes up and smoke_local.sh runs
# one search-intent WebSocket round-trip — it reuses a healthy backend on
# :8000 or starts and stops its own. Integration/e2e are import-checked only;
# `bash scripts/smoke_local.sh` runs the full e2e suite.
ci:
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
	@echo "[ci] smoke: search-intent round-trip against a live backend"
	@docker info >/dev/null 2>&1 || { echo "Docker isn't running — open -a Docker, wait for it, re-run make ci"; exit 1; }
	@cd .. && docker compose up -d --wait
	@bash scripts/smoke_local.sh -k test_search_intent_returns_results -q --tb=short
	@echo "ci passed — safe to push."

teardown:
	@bash scripts/teardown.sh
