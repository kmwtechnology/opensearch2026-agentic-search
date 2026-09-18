# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Agentic Hybrid Search** — a production-grade LangGraph RAG agent for Amazon ESCI e-commerce product search. Hybrid BM25 + vector retrieval fused via RRF, dynamic alpha per intent, cross-encoder reranking with a quality gate, real-time WebSocket streaming, and an agentic taxonomy self-correction loop. Runs **local-only** via Docker Compose + Google Gemini — see "Deploy & CI reality" below.

## New Session Checklist

**Cowboy mode (2026-09-15):** commit directly to `main`, no feature branch or PR required by default. `main` has no branch protection — this is a private repo without GitHub Pro, so classic branch protection and rulesets both 403; `gh api .../branches/main` confirms `"protected": false`. Confirm `git status` is clean and `main` is up to date before starting. Run `make check` before pushing — that local run is the only gate that exists, for anything. A feature branch + PR is still fine when you explicitly want something reviewed before it lands, but it's opt-in now, not the default.

## Workflow skills

This repo has project-level skills at `.claude/skills/` (`workflow-start`, `workflow-check`, `workflow-deploy`), rewritten 2026-09-15 for the direct-to-main flow — use them instead of generic process assumptions:

- **`workflow-start`**: get issue context, plan, then code straight on `main` — no branch, no draft PR.
- **`workflow-check`**: pre-push checklist (tests, `make check`, self-review, docs/memory update) — this is the review gate, since there's no PR/reviewer.
- **`workflow-deploy`**: push, verify locally (`make dev`), close the issue.

Load-bearing facts:

- **Issue tracking**: GitHub Issues (`kmwtechnology/opensearch2026-agentic-search`); `gh issue view <N>`; done = `state == CLOSED`. `Closes #N` in a commit message auto-closes the issue on push to `main` (closing keywords work on direct pushes to the default branch, not just PR merges).
- **Never force-push `main`** — even in cowboy mode, fix a bad push with `git revert`, not history rewriting, unless the user explicitly asks for that.
- CI/deploy facts (no CI gate, no deploy step) are in "Deploy & CI reality" below — don't restate them per-skill.

## Commands

All backend commands run from `langchain_agent/` — there is no root-level `Makefile` or `scripts/` dir, only `langchain_agent/Makefile`, so `make ...` from the repo root fails with "No rule to make target". Bare imports (`from config import ...`-style) require `PYTHONPATH=.` for every Python invocation (pytest, scripts).

```bash
cd langchain_agent   # required first — commands below assume this cwd

# First-time setup / every-session startup (brings up Postgres + OpenSearch via
# Docker, backend on :8000, frontend on :5173 — no manual `docker compose up` needed)
./scripts/setup.sh          # or: make setup   (10-20 min, first time only)
./scripts/start.sh          # or: make dev     (every session)
./scripts/stop.sh           # or: make stop    (stops processes + containers, keeps volumes)
./scripts/teardown.sh       # or: make teardown (DESTRUCTIVE: removes .venv, node_modules, all Docker volumes)

# ESCI ingestion via Lucille ETL
bash scripts/lucille_ingest.sh    # products + judgments, Docker-based by default
make seed-taxonomy                # rediscover color taxonomy — DESTRUCTIVE, needed once per fresh cluster (waterproof grows separately, live)
make reindex / make reindex-products

# Tests (PYTHONPATH=. required)
PYTHONPATH=. pytest tests/unit/                  # ~0.5s, no services required
PYTHONPATH=. pytest tests/integration/           # needs Postgres + OpenSearch running
PYTHONPATH=. pytest tests/e2e/                   # full system
PYTHONPATH=. pytest tests/ -m phase1             # by marker (see pytest.ini for the full marker list:
                                                  #  phase1, phase3, unit, integration, e2e, slow, websocket,
                                                  #  asyncio, agent, edge_cases, pipeline, quality_gate_retry,
                                                  #  retriever_reranker, requires_real_api, evaluator, intent,
                                                  #  quality_gate)
PYTHONPATH=. pytest tests/unit/test_foo.py::test_bar -v   # single test

make check             # THE pre-push gate — run before every push/PR merge: ci + smoke
make ci                # fast static sub-check (no live services): black/isort --check + flake8
                        # + mypy main.py + pytest unit + collect-only integration/e2e + frontend
make format-fix        # black + isort, fixes in place

# Benchmarks (requires docker compose up -d)
make benchmark-esci-fast   # ~5 min, deterministic (no LLM)
make benchmark-esci        # ~10 min, full adaptive (requires GOOGLE_API_KEY)

# Smoke test (run standalone, or via `make check` above — no git hook triggers this)
make smoke           # ~13-20s, search-intent smoke, needs Docker + backend
# Full regression suite (no dedicated Make target — run directly when wanted):
bash scripts/smoke_local.sh   # ~90s, all e2e+slow scenarios

# Frontend (from langchain_agent/web/)
npm install && npm run dev   # :5173, proxies API to :8000
npm run lint                 # eslint, --max-warnings 0
npm run test                 # vitest run
```

**Local git hooks**: `.git/hooks/pre-commit` (installed by `scripts/setup.sh` from `scripts/pre-commit.sh`) runs black/isort/flake8 on *staged* `.py` files only — mirrors `ci-format`/`lint`. `.git/hooks/pre-push` is Git LFS's own hook only; nothing there runs tests. Run `make check` by hand before pushing.

### Local dev lifecycle

Spoken triggers "start local dev" / "stop local dev" / "teardown local dev" map 1:1 to these (all from `langchain_agent/`):

- **start local dev** → `make dev`. Blocks forever (backend + frontend run in the foreground) — always launch it backgrounded and watch the log, never wait on it synchronously. Two-stage readiness: `Uvicorn running on http://127.0.0.1:8000` binds the port, but `Application startup complete` (after LLM/embeddings/reranker/vector-store init) is the real "ready for requests" signal; frontend readiness is `VITE vX ready in Yms`. Failure signatures: `Address already in use`, `EADDRINUSE`, `Connection refused`, `Traceback`.
- **stop local dev** → `make stop`. Non-destructive — kills backend/frontend processes and stops the Docker containers, but keeps volumes (Postgres + OpenSearch data survive).
- **teardown local dev** → `make teardown` (→ `scripts/teardown.sh`). DESTRUCTIVE and runs non-interactively (no prompt of its own) — deletes `.venv`, `web/node_modules`, all Docker volumes (Postgres + OpenSearch data), and logs. Confirm with the user before running this even though the script won't ask.

## Architecture

### Pipeline graph

The agent is a LangGraph `StateGraph(CustomAgentState)` built in `main.py::create_agent_graph()`:

```
intent_classifier ─┬─(summary)──► summary ─┬─(continue)──► retriever
                    ├─(clarify)──► agent    └─(done)──────► agent
                    └─(other)────► query_evaluator ──► retriever ──► reranker ──► quality_gate ─┬─(retry)───► retriever
                                                                                                  └─(continue)► agent ──► llm_judge ──► END
```

Six intent classes (`search`, `comparison`, `attribute_filter`, `refinement`, `follow_up`, `summary`) come from a single structured-output LLM call in `intent_classifier_node` — no keyword fast-path. Confidence < 0.7 routes to `agent` for clarification instead of retrieving. Conversational query rewriting (resolving pronouns/comparatives against history) happens *inside* `retriever_node` (via `_expand_vague_query`), not as a separate graph node. `quality_gate_node` can loop back to `retriever` exactly once with an adjusted alpha and a 4x wider candidate pool (`RETRY_FETCH_MULTIPLIER`; intent-specific thresholds: comparison=0.55, search/follow_up=0.50, attribute_filter/refinement=0.45); `quality_gate_status` must be explicitly set to `"pass"`/`"retry"` on every return path or a prior turn's `"retry"` can leak forward through checkpointed state. The `agent` node is registered with both a sync and async callable (`RunnableCallable(self.agent_node, self.aagent_node, name="agent")`) — `cli.py` drives the graph synchronously via `app.invoke()`, the API drives it via `astream_events()` and needs the async path or a taxonomy reindex blocks every WebSocket frame for ~20s. `llm_judge_node` (post-agent, optional) flags hallucinations and auto-retries generation for `fabrication`/`cross_product_bleed` categories only; `hallucination_retry_used` must be reset to `False` at the top of every new user turn.

### Module layout (post issue #91 reorg)

`main.py` defines `EcommerceSearchAgent(PipelineNodesMixin, ConversationManagementMixin)`; the mixins live in `pipeline/pipeline_nodes.py` (all node implementations) and `pipeline/conversation_management.py`. `cli.py`, `setup.py`, and `config_generator.py` stay at root (invoked by path from shell scripts). Everything else is grouped by concern:

- `core/` — `agent_state.py` (the `CustomAgentState` TypedDict), `config.py`, `exceptions.py`, `logging_config.py`
- `pipeline/` — node implementations, conversation management, enrichment events, `reindex_trigger.py`
- `retrieval/` — vector store, reranker, attribute discovery/mapping store, doc replacer, link verifier
- `quality/` — LLM judge, enrichment service + value judge, demo reset
- `observability/` — embedding cache, relevancy metrics, LLM content helpers
- `checkpoints/` — Postgres checkpoint maintenance/optimization
- `benchmarks/` — ESCI benchmark harness
- `api/` — FastAPI app (`main.py`, `routes/`, `schemas/`, `services/`, `middleware/`)

### State access pattern

`CustomAgentState` (`core/agent_state.py`) is `total=False` — only `messages` is guaranteed. Always `state.get("field", default)`, never `state["field"]`. Each node reads/writes a documented subset of fields (see the docstring in that file for the full field lifetime table); adding a new node means adding its fields there too, since LangGraph filters node output down to declared state channels — an undeclared key silently never reaches `astream_events`.

### Error hierarchy

All custom exceptions (`core/exceptions.py`) inherit from `AgenticHybridSearchError` (message, optional `details`, `recoverable` flag) — catch that one type to handle any agent-related error uniformly. Subclasses: `ConfigurationError`, `DatabaseError`, `OpenSearchError`, `LLMError`, `RetrievalError`, `LinkVerificationError`, `StreamingError`, `StateError`, `RerankerLLMError`, `RerankerValidationError`, `SearchValidationError`, `SearchFailureError`, `EmbeddingError`, `SearchTimeoutError`, `AgentError`, `AgentTimeoutError`, `RerankerError`.

### Auth model

Same-origin checking (`api/middleware/origin_auth.py`, `verify_same_origin`) is the **sole** auth layer — an allow-list of localhost ports; a disallowed `Origin` always 403s. There is no login gate (removed entirely, issue #135) and no `api/middleware/auth.py` module — don't import a `verify_api_key` or similar; it doesn't exist. `api/middleware/admin_auth.py` (`verify_admin_token`, constant-time `hmac.compare_digest` against `ADMIN_TOKEN`) is preserved as a standalone utility for future automation but is **not** wired into any route today — `/api/admin/*` relies on same-origin checking only. (The root `README.md`'s "setup.sh creates a local login password" line is stale doc drift predating #135 — don't trust it; `langchain_agent/README.md` has the current story.)

### Attribute detection & agentic taxonomy growth/correction

Color/waterproof attribute detection runs in the Lucille ETL via `AttributeDetectorStage` (one generic Java stage, `langchain_agent/lucille-esci/src/main/java`, parameterized per attribute type), writing `product_<type>_primary`/`_secondary` keyword fields. The taxonomy itself lives in OpenSearch (not a committed file) — rules-based, auditable, no AI at ingest time. A fresh cluster's taxonomy store is empty; `scripts/setup.sh` seeds color unconditionally on first-time setup, but `make seed-taxonomy` is the manual re-seed entry point later (destructive to any agent-learned color mappings). `waterproof` (issue #142) is deliberately NOT seeded either way — `WATERPROOF_CANONICALS` ships with zero variant terms on purpose, so it starts as a genuine gap and grows entirely from the live flywheel below. The stage hard-fails the ingest if the taxonomy lookup can't load — never soft-fail a store lookup in a custom Lucille stage.

Beyond ingest-time detection, the agent can grow *or fix* the live taxonomy at runtime via one tool, `trigger_enrichment(attribute_type, variant, canonical)` (gated by `ENABLE_ENRICHMENT_TOOL`, default off in code but `true` in this repo's local `.env`), which writes the mapping to OpenSearch and triggers a real Lucille reindex through `pipeline/reindex_trigger.py` (~19-20s, runs `scripts/lucille_ingest.sh` as a subprocess). Both color's and waterproof's unresolved-term filter are hard exact-match filters, so both reliably trigger the growth path live through chat (this used to differ — `material` had a soft fallback + was subject to filter relaxation, so it only ever triggered via `/api/admin/enrich`; `material` was removed in favor of `waterproof` for exactly this reason). The correction case — a shopper disputes an existing wrong tag — is caught by `_detect_correction_signal`/`_try_correction_tool` in `agent_node` on `refinement`/`follow_up` turns; this matters architecturally because a wrong-but-mapped result still **passes** the quality gate, so it's invisible to any automated check. Full detail in `langchain_agent/ARCHITECTURE.md`'s "Taxonomy Growth & Correction" section.

### Event sync

`api/schemas/events.py` must stay in sync with `web/src/types/events.ts` — each event's `node` field pins it to a pipeline step. Every return path in `agent_node` must include a `"citations"` key (empty list if none). ESCI products cite via `https://www.amazon.com/s?k={title}` (robust against delisted ASINs).

## Tech stack

| Layer | Tech |
|---|---|
| LLM (generation) | Gemini 2.5 Flash |
| LLM (classify/eval/judge) | Gemini 2.5 Flash-Lite |
| Reranker | Local cross-encoder (`ms-marco-MiniLM-L-12-v2`), `RERANKER_TYPE=cross-encoder` default; a Gemini-based reranker exists but isn't shipped default |
| Embeddings | `models/gemini-embedding-001` (768-dim) |
| Agent framework | LangGraph + LangChain |
| Vector DB | OpenSearch (HNSW knn + BM25) |
| Checkpoints | PostgreSQL, via `langgraph-checkpoint-postgres` |
| API | FastAPI + WebSocket |
| Frontend | React 19 + TypeScript + Vite + Zustand, Vitest + ESLint |
| Deployment | Local only (Docker Compose) |

## Deploy & CI reality

No GitHub Actions CI exists — `.github/workflows/` was deleted entirely (issue #113); every `.github` Actions run was failing before that with 0 steps assigned, so removing it didn't lose real coverage. No deploy mechanism exists either (issue #110) — the demo runs entirely from local Docker + `make dev`. `make check` run locally is the only gate on this repo, full stop — run it before every push to `main` (see "New Session Checklist" — there's no PR to gate it either). `make ci` alone is a faster no-live-services sub-check for iterative coding; `make check` = `ci` + `smoke` and is the actual thing to run before pushing.

## Reference Docs

Project memory (ongoing decisions, known gotchas, architecture context beyond what's here) lives at:

```
~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md
```

This memory index was just reset (2026-09-15) — expect it to be sparse until it rebuilds over future sessions.
