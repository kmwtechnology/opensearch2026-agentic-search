# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Agentic Hybrid Search** — a production-grade LangGraph RAG agent for Amazon ESCI e-commerce product search. Hybrid BM25 + vector retrieval fused via RRF, dynamic alpha per intent, cross-encoder reranking with a quality gate, real-time WebSocket streaming, and an agentic taxonomy self-correction loop. Runs **fully local** — Docker Compose + native Ollama for every model (chat and embeddings), no cloud API key. `make dev` starts everything side by side: the native backend (:8080) with the live-reloading Vite UI (:5173), and the demo container (:8000, backend + built UI, rebuilt from the tree on each start) — see "Local dev lifecycle" and "Deploy & CI reality" below.

## New Session Checklist

**Cowboy mode (2026-09-15):** commit directly to `main`, no feature branch or PR required by default. `main` has no branch protection — this is a private repo without GitHub Pro, so classic branch protection and rulesets both 403; `gh api .../branches/main` confirms `"protected": false`. Confirm `git status` is clean and `main` is up to date before starting. Run `make ci` before pushing — that local run is the only gate that exists, for anything. A feature branch + PR is still fine when you explicitly want something reviewed before it lands, but it's opt-in now, not the default.

## Workflow skills

This repo has project-level skills at `.claude/skills/` (`workflow-start`, `workflow-check`, `workflow-deploy`), rewritten 2026-09-15 for the direct-to-main flow — use them instead of generic process assumptions:

- **`workflow-start`**: get issue context, plan, then code straight on `main` — no branch, no draft PR.
- **`workflow-check`**: pre-push checklist (`make ci`, self-review, docs/memory update) — this is the review gate, since there's no PR/reviewer.
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
# Docker, native backend on :8080 + Vite UI on :5173, and the demo container on
# :8000 — no manual `docker compose up` needed)
./scripts/setup.sh          # or: make setup   (pulls Ollama models ~23 GB, then bulk-loads the
                             #   permanent precomputed index dump — ~1-2 min, no embedding, no
                             #   ingest pipeline. Fails with a `git lfs pull` message if
                             #   data/precomputed/ is missing. There is no rebuild path.)
./scripts/start.sh          # or: make dev — every session. Dev UI :5173 (live) → native backend :8080,
                             #   plus the demo container :8000 (image rebuilt from the tree on each start;
                             #   edits after that show on :5173 only until the next make dev)
./scripts/stop.sh           # stops both backends, Vite, and the containers; keeps volumes (no make target)
./scripts/teardown.sh       # or: make teardown (DESTRUCTIVE: removes .venv, node_modules, all Docker volumes)

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

make ci                # THE pre-push gate, ~1-2 min: black/isort/flake8/mypy, unit tests, collect-only
                        # integration/e2e, frontend test/lint/tsc/build, then `docker compose up -d --wait`
                        # and one search-intent WebSocket round-trip against the native backend on :8080
                        # (starts one if none is there; never the demo on :8000). No git hook runs this.
# The Makefile has exactly five targets: doctor setup dev ci teardown. Everything else is a
# direct command, documented in the Makefile header:
.venv/bin/black . && .venv/bin/isort .                    # auto-format
PYTHONPATH=. .venv/bin/pytest tests/unit/                  # unit tests only (~30s)
bash scripts/smoke_local.sh                                # full e2e regression suite (~90s)
PYTHONPATH=. .venv/bin/python benchmarks/benchmark_esci.py --limit 5000 --fast   # ~35 min; --hard-only for LLM intent

# Frontend (from langchain_agent/web/)
npm install && npm run dev   # :5173, proxies /api and /ws to the native backend on :8080
npm run lint                 # eslint, --max-warnings 0
npm run test                 # vitest run
```

**Local git hooks**: `.git/hooks/pre-commit` (installed by `scripts/setup.sh` from `scripts/pre-commit.sh`) runs black/isort/flake8 on *staged* `.py` files only — mirrors `make ci`'s format/lint steps. `.git/hooks/pre-push` is Git LFS's own hook only; nothing there runs tests. Run `make ci` by hand before pushing.

### Local dev lifecycle

Spoken triggers "start local dev" / "stop local dev" / "teardown local dev" map 1:1 to these (all from `langchain_agent/`):

- **start local dev** → `make dev` (→ `scripts/start.sh`). Brings up Postgres + OpenSearch with `docker compose up -d --wait`, starts the native backend on **:8080** and the Vite UI on **:5173** in the background (`logs/backend.log` / `logs/frontend.log`), waits for `:8080/api/health`, then rebuilds and starts the **demo container on :8000** (`docker compose --profile app up -d --build`, output in `logs/demo-build.log`; a demo build failure is a warning, not a dev failure). Returns when done — safe to run synchronously. In the backend log, `Uvicorn running on http://127.0.0.1:8080` binds the port but `Application startup complete` (after LLM/embeddings/reranker/vector-store init) is the real "ready" signal; frontend readiness is `VITE vX ready in Yms`. Failure signatures: `Address already in use`, `EADDRINUSE`, `Connection refused`, `Traceback`. Backend-only one-liner: `PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload --port 8080`. **:8000 is always the demo image, frozen as of the last `make dev`** — point tests and curls at :8080 for the working tree.
- **stop local dev** → `./scripts/stop.sh` (deliberately not a make target). Non-destructive — kills the native backend (:8080) and Vite (:5173), then `docker compose --profile app stop` (Postgres, OpenSearch, and the demo container); volumes survive. Never `lsof`-kill :8000 — that's Docker's port proxy, not a backend process.
- **teardown local dev** → `make teardown` (→ `scripts/teardown.sh`). DESTRUCTIVE and runs non-interactively (no prompt of its own) — deletes `.venv`, `web/node_modules`, all Docker volumes (Postgres + OpenSearch data), and logs. Confirm with the user before running this even though the script won't ask.
- **the demo container** is part of `make dev`, not a separate target. To refresh its image after edits, run `make dev` again. To stop only it: `docker compose stop app` from the repo root — **not** `docker compose --profile app down`, which tears down every service in the project (Postgres/OpenSearch too), not just `app`.

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

`main.py` defines `EcommerceSearchAgent(PipelineNodesMixin, ConversationManagementMixin)`; the mixins live in `pipeline/pipeline_nodes.py` (all node implementations) and `pipeline/conversation_management.py`. `cli.py` and `setup.py` stay at root (invoked by path from shell scripts). Everything else is grouped by concern:

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

Color/waterproof attribute detection happened once, historically, when the corpus's source index was originally built, writing `product_<type>_primary`/`_secondary` keyword fields — that result is preserved verbatim in the committed `data/precomputed/` dump and loaded by every `make setup`. There is no ingest-time detection pipeline in this repo any more. The taxonomy itself lives in OpenSearch (not a committed file, though its content is seeded from the precomputed `attribute_mappings_dump.parquet`) — rules-based, auditable, no AI involved. `waterproof` (issue #142) is deliberately NOT seeded — `WATERPROOF_CANONICALS` ships with zero variant terms on purpose, so it starts as a genuine gap and grows entirely from the live flywheel below.

Beyond that one-time historical tagging, the agent can grow *or fix* the live taxonomy at runtime via one tool, `trigger_enrichment(attribute_type, variant, canonical)` (gated by `ENABLE_ENRICHMENT_TOOL`, default off in code but `true` in this repo's local `.env`), which writes the mapping to OpenSearch and applies it through `pipeline/reindex_trigger.py`. This always re-detects the attribute on only the products whose text mentions the changed variant (`pipeline/scoped_retag.py`; seconds, e.g. tan→brown re-tagged 679 of 905 candidates in <1s) — there is no full-reindex mode any more; `pipeline/scoped_retag.py`'s detection logic is the only attribute-detection code in the repo, and it must exactly match how the original corpus was tagged (its docstring documents the algorithm precisely for that reason). Scoped candidates come from the `chunk_text.words` subfield (ASCII-word tokenizer). Both color's and waterproof's unresolved-term filter are hard exact-match filters, so both reliably trigger the growth path live through chat (this used to differ — `material` had a soft fallback + was subject to filter relaxation, so it only ever triggered via `/api/admin/enrich`; `material` was removed in favor of `waterproof` for exactly this reason). The correction case — a shopper disputes an existing wrong tag — is caught by `_detect_correction_signal`/`_try_correction_tool` in `agent_node` on `refinement`/`follow_up` turns; this matters architecturally because a wrong-but-mapped result still **passes** the quality gate, so it's invisible to any automated check. Full detail in `langchain_agent/ARCHITECTURE.md`'s "Taxonomy Growth & Correction" section.

### Event sync

`api/schemas/events.py` must stay in sync with `web/src/types/events.ts` — each event's `node` field pins it to a pipeline step. Every return path in `agent_node` must include a `"citations"` key (empty list if none). ESCI products cite via `https://www.amazon.com/s?k={title}` (robust against delisted ASINs).

### Product images (issues #144, #147)

Every product carries its own photo URL. The corpus is the ESCI US `test` + `small_version` subset (158,637 products). [SQID](https://github.com/Crossing-Minds/shopping-queries-image-dataset) scraped Amazon image URLs for exactly that subset, and `scripts/build_product_sample.py` joins them in as `product_image_url` (95.5% coverage; SQID's `Default_Background_Art` placeholder is treated as no image). The index stores the field as `keyword`, `index: false`: it is displayed, never searched. `_hit_to_document` exposes it as `metadata["image_url"]`, and each citation carries `image_url` next to `asin`. `citations` is typed `List[Dict[str, str]]`, so the event schema needs no change. The strict REST `Citation` model in `api/routes/chat.py` and both frontend types do declare it.

Images are **not** bundled or curated. They load straight from Amazon's CDN (`referrerPolicy="no-referrer"`). The old committed-JPG approach (`web/src/assets/products/`, `fetch_product_images.py`, hand-picked substitute ASINs) was removed in #147. A URL that 404s (a product delisted since the SQID scrape) trips `ProductCard`'s `onError`, and that bullet falls back to plain text.

The photos are **inline, not a strip**: the `li` renderer in `Message.tsx` turns each bullet the answer writes into a `ProductCard` — photo left, name and the model's own blurb right — so the answer reads as a shopping result list. The bullet's first `<strong>` (read from the hast `node`, which makes tight and loose lists behave alike) prefix-matches a citation label via `indexProducts`; the LLM bolds a shortened name while the citation carries the full catalog title, so the match runs in both directions. A bullet that matches nothing, or whose citation has no `image_url`, stays a plain bullet — never a placeholder.

**An answer must render exactly once.** Because the cards are keyed off the citations, and the citations arrive on `agent_complete` — one WebSocket frame *after* `llm_response_chunk(is_complete)` delivers the last token — committing the text on that earlier frame renders the list as plain bullets and then re-renders it as cards. Two things prevent that: `chatStore.completeTurn()` writes the content and the citations in a single `set`, and `MessageList` withholds a still-streaming assistant bubble entirely, leaving the pipeline status card up for the whole turn instead. Don't reintroduce a `finalizeStreaming()` call in the `llm_response_chunk` handler; `agent_error` is the escape hatch for the failure path.

## Tech stack

| Layer | Tech |
|---|---|
| LLM (all calls) | `qwen3.6:35b-a3b-q4_K_M` via local Ollama (`core/llm.py::build_chat_model`; `reasoning=False`, explicit `num_ctx`) |
| Reranker | Local cross-encoder (`ms-marco-MiniLM-L-12-v2`) — the only reranker |
| Embeddings | `nomic-embed-text` via local Ollama (768-dim; `search_document:` when the corpus was originally embedded, `search_query:` at query time via `retrieval/embeddings.py`) |
| Corpus | 158,637 ESCI US test/small products (query-first, every query fully judged), 95.5% with a SQID image URL |
| Agent framework | LangGraph + LangChain |
| Vector DB | OpenSearch (HNSW knn + BM25) |
| Checkpoints | PostgreSQL, via `langgraph-checkpoint-postgres` |
| API | FastAPI + WebSocket |
| Frontend | React 19 + TypeScript + Vite + Zustand, Vitest + ESLint |
| Deployment | Local only (Docker Compose) |

## Deploy & CI reality

No GitHub Actions CI exists — `.github/workflows/` was deleted entirely (issue #113); every `.github` Actions run was failing before that with 0 steps assigned, so removing it didn't lose real coverage. No deploy mechanism exists either (issue #110) — the demo runs entirely locally — `make dev` runs the native dev stack (:5173/:8080) and the Dockerized demo image (:8000, everything but Ollama in one container) side by side. `make ci` run locally is the only gate on this repo, full stop — run it before every push to `main` (see "New Session Checklist" — there's no PR to gate it either). It is one command with no fast/full split: static checks, unit tests, frontend build, then a live smoke round-trip (it brings Docker up itself).

## Reference Docs

Project memory (ongoing decisions, known gotchas, architecture context beyond what's here) lives at:

```
~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md
```

Rebuilt from a 2026-09-15 reset; check it before starting non-trivial work in this repo.
