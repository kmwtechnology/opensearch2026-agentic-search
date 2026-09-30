# Agentic Hybrid Search — run from langchain_agent/. Five targets:
#   doctor    check prerequisites (Docker, Ollama models, .venv, node_modules, LFS data)
#   setup     first-time: Docker services, .venv, Ollama models, precomputed index load (~1-2 min)
#   dev       everything, side by side: Postgres+OpenSearch, the native backend :8080 with the
#             live-reloading Vite UI :5173, and the demo container :8000 (backend + built UI,
#             rebuilt from the current tree on each start — later edits show on :5173 only)
#   ci        THE pre-push gate: format/lint/types, unit tests, collect-only e2e, frontend
#             test/lint/build, then the integration suite and a live smoke round-trip
#             (brings Docker up)
#   teardown  DESTRUCTIVE: .venv, node_modules, Docker volumes, logs
#
# Not targets, on purpose:
#   stop everything     ./scripts/stop.sh                  (processes + containers; data survives)
#   re-arm the demo     ./scripts/reset_demo_taxonomy.sh   (or the UI's Restart button)
#   unit tests only     PYTHONPATH=. .venv/bin/pytest tests/unit/
#   auto-format         .venv/bin/black . && .venv/bin/isort .
#   full e2e suite      bash scripts/smoke_local.sh

.DEFAULT_GOAL := doctor
.PHONY: doctor setup dev ci teardown

VENV := .venv/bin
PY   := PYTHONPATH=. $(VENV)

doctor:
	@bash scripts/doctor.sh

setup:
	@bash scripts/setup.sh

dev:
	@bash scripts/start.sh

# No CI service exists; this is the only gate before a push. Static steps
# first (fail fast, no services), then Docker comes up for the integration
# tests (live Postgres/OpenSearch, throwaway index names) and smoke_local.sh
# runs one search-intent WebSocket round-trip against the native backend on
# :8080 — it reuses a healthy one (make dev) or starts and stops its own; it
# never touches the demo container on :8000. The rest of e2e is import-checked
# only; `bash scripts/smoke_local.sh` runs the full e2e suite.
ci:
	@echo "[ci] black --check / isort --check-only"
	@$(VENV)/black --check .
	@$(VENV)/isort --check-only .
	@echo "[ci] flake8 / mypy"
	@$(VENV)/flake8 . --count
	@$(VENV)/mypy main.py
	@echo "[ci] pytest tests/unit/"
	@$(PY)/pytest tests/unit/ -q
	@echo "[ci] pytest --collect-only tests/e2e/"
	@$(PY)/pytest --collect-only -q tests/e2e/ > /dev/null
	@echo "[ci] frontend: vitest, eslint, build (tsc + vite)"
	@cd web && npm install --silent && npm run test && npm run lint && npm run build
	@echo "[ci] docker services"
	@docker info >/dev/null 2>&1 || { echo "Docker isn't running — open -a Docker, wait for it, re-run make ci"; exit 1; }
	@cd .. && docker compose up -d --wait
	@echo "[ci] pytest tests/integration/ (live Postgres/OpenSearch)"
	@$(PY)/pytest tests/integration/ -q
	@echo "[ci] smoke: search-intent round-trip against a live backend"
	@bash scripts/smoke_local.sh -k test_search_intent_returns_results -q --tb=short
	@echo "ci passed — safe to push."

teardown:
	@bash scripts/teardown.sh
