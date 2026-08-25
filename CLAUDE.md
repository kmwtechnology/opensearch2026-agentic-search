# CLAUDE.md

Guidance to Claude Code (claude.ai/code) when working with this repository.

## New Session Checklist

When a new work session begins (especially when picking up an issue, feature, or non-trivial fix), **suggest creating a feature branch before writing code**. Confirm `git status` is clean and `main` is up to date, then propose a branch name (e.g. `feat/issue-6-judge-categories`, `fix/citation-urls`). Do not start editing on `main`. Skip only for one-line typos or doc tweaks the user explicitly says to commit straight to `main`.

## Working Session Skills (`/workflow-start`, `/workflow-check`, `/workflow-deploy`)

These three skills are **global** (`~/.claude/skills/`), shared across every project. Their written instructions default to Nasuni/Hyrule's Jira/Slack world. **None of that applies here.** This repo tracks work in **GitHub Issues** (`kmwtechnology/opensearch2026-agentic-search`):

| Skill step | Default (ignore) | This project |
|---|---|---|
| Ticket lookup / "Done" check | Nasuni Jira | `gh issue view <N>`; "done" = `state == CLOSED` |
| Branch name | `TICKET-NNN-slug` | `feat/issue-N-slug` / `fix/issue-N-slug` |
| Commit / PR prefix | Jira ticket ID | Reference issue in PR body (`Closes #N`); no commit prefix needed |
| Local tests | `./run_app_tests.sh hyrule_api` (doesn't exist) | `PYTHONPATH=. pytest tests/unit/`, `make ci`, `make smoke-local-quick` / `make smoke-local` |
| Ready-for-review / deploy announcement | Slack `#nasuni-int` | **Skip entirely** — no Slack channel configured for this project |
| Deploy-outcome close-out | Jira comment + transition | `gh issue close <N> --comment "..."`; Obsidian tag `#opensearch2026-agentic-search` not `#nasuni` |
| CI/deploy watch | Hyrule k8s workflows | `.github/workflows/build-deploy.yml` (PR + main) and `.github/workflows/reindex.yml` (manual Lucille ETL) |

When skills say "load `mcp__atlassian-nasuni__*`" or "post to `#nasuni-int`," treat as inapplicable. Use GitHub equivalents instead.

## Project Overview

**Agentic Hybrid Search** — production-grade LangGraph RAG agent for Amazon ESCI e-commerce product search. Hybrid BM25 + vector retrieval with dynamic alpha per intent, reranking with quality gate, real-time WebSocket streaming. Deployed on GCP Cloud Run with Google Gemini.

## Pipeline

```text
Intent Classifier → Query Rewriter → Query Evaluator → Retriever → Reranker → Quality Gate → Agent
```

Six intent classes: `search`, `comparison`, `attribute_filter`, `refinement`, `follow_up`, `summary`. See `ARCHITECTURE.md` for node-by-node detail.

**Key nodes:**

- **Intent Classifier** — keyword fast-path + LLM fallback. Confidence < 0.7 triggers clarification.
- **Query Rewriter** — resolves follow-up references using conversation history.
- **Query Evaluator** — sets `dynamic alpha` (0.0 for lexical exact matches, 1.0 for semantic/exploration).
- **Retriever** — hybrid vector + BM25 via RRF fusion (k=60); applies attribute filters for `attribute_filter` intent; filter relaxation if <3 results.
- **Reranker** — LLM-scored 0.0–1.0; sets `reranker_max_score`.
- **Quality Gate** — intent-specific thresholds (comparison=0.55, search/follow_up=0.50, attribute_filter/refinement=0.45). Retries with adjusted alpha if below threshold.
- **Agent** — conversational response with citations. ESCI products cite via `https://www.amazon.com/s?k={title}` (robust against delisted ASINs).
- **LLM Judge** (post-agent, optional) — flags hallucinations; auto-correction retry for `fabrication` and `cross_product_bleed` categories only. **Reset `hallucination_retry_used=False` at top of every new user turn** (issue #83).

## Tech Stack

| Layer | Tech |
|-------|------|
| LLM (generation) | Gemini 3 Flash (preview) |
| LLM (classify/rerank/eval) | Gemini 3.1 Flash Lite (preview) |
| Embeddings | `models/gemini-embedding-001` (768-dim) |
| Agent framework | LangGraph + LangChain |
| Vector DB | OpenSearch 2.19.1 (HNSW knn + BM25) |
| Checkpoints | PostgreSQL 16 |
| API | FastAPI + WebSocket |
| Frontend | React 18 + TypeScript + Tailwind + Zustand |
| Deployment | GCP Cloud Run |

## Key Patterns

- **Bare imports & PYTHONPATH** — modules use `from config import ...`. All Python invocations from `langchain_agent/` need `PYTHONPATH=.` (pytest, main, custom scripts). Omitting causes `ModuleNotFoundError`.

- **Frontend origin detection** — Components with iframes/cross-domain requests should detect environment at runtime, not hardcode defaults. Pattern: (1) try `/api/config`, (2) if it returns `apiUrl`, use it, (3) else smart detection: localhost → `http://localhost:8000`, non-localhost → `window.location.origin`. See `SwaggerPage.tsx` (issue #28).

- **State access** — `CustomAgentState` is `total=False`; only `messages` guaranteed. Always `state.get("field", default)`. Each node adds specific fields: Classifier → `intent`, `confidence`, `user_query`; Query Evaluator → `alpha`, `intent_description`; Retriever → `retrieved_documents`, `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms`; Reranker → `reranker_max_score`, `reranked_documents`, `reranker_latency_ms`; Quality Gate → `quality_gate_retried`, `alpha_adjusted_value`, `quality_gate_threshold_used`.

- **Dual-analyzer BM25** (issue #69) — Dense vectors handle morphological recall ("running/runs/ran"). BM25 focuses precision. Primary fields use `light_english_analyzer` (kstem). Sub-fields (`.heavy`) use `heavy_english_analyzer` (snowball) at ^0.3 boost for recall fallback. Balances precision (Beats ≠ beat) with recall via .heavy + embeddings.

- **Hybrid search** — RRF fusion (k=60); `alpha` ∈ [0,1] weights lexical→semantic.

- **Attribute normalization** — integrated into Lucille ETL via `AttributeNormalizerStage` (custom Java stage in `langchain_agent/lucille-esci/src/main/java`). Outputs: `product_color_primary`, `product_color_secondary`, `product_brand_normalized` as keyword fields. Rules-based (16 canonical colors), auditable, no AI.

- **Auth** — two layers:
  1. **Same-origin** (`origin_auth.py`) — allow-list of localhost ports + Cloud Run `*.run.app`. Disallowed Origin always 403s.
  2. **Shared-password session + admin token** (`session_auth.py`):
     - **Session**: `LOGIN_PASSWORD` env var. `POST /api/auth/login` sets HttpOnly + SameSite=Lax cookie (`ahs_session`). WS rejects with code **4401** on failure.
     - **Admin token** (automation): `ADMIN_TOKEN` env var (32+ chars). Use `X-Admin-Token` header. Constant-time comparison via `hmac.compare_digest`.
  - **Do NOT wire new routes through legacy `verify_api_key`** — use `verify_same_origin` + `verify_session` (or `verify_admin_token` for automation).

- **Event sync** — `api/schemas/events.py` must stay in sync with `web/src/types/events.ts`. Each event's `node` field pins it to pipeline step. All return paths in `agent_node` must include `"citations"` key (empty list if no citations).

- **Error hierarchy** — all custom exceptions inherit from `AgenticHybridSearchError`.

## Common Commands

All backend commands run from `langchain_agent/`. Bare imports require `PYTHONPATH=.`.

```bash
# Local services
docker compose up -d                      # from repo root: PostgreSQL + OpenSearch + Dashboards
docker compose down

# Setup & dev
cd langchain_agent
python3 setup.py                          # one-time DB + index setup
make dev-api                              # FastAPI :8000 (--reload)
make dev-web                              # React :5173
make dev                                  # both (backend backgrounded)
make stop

# ESCI ingestion via Lucille ETL
bash scripts/lucille_ingest.sh            # products + judgments, no API calls (default: Docker-based)

# Benchmarks (requires docker compose up -d)
make benchmark-esci-fast                  # ~5 min, deterministic (no LLM)
make benchmark-esci                       # ~10 min, full adaptive (requires GOOGLE_API_KEY)

# Tests (PYTHONPATH=. required)
PYTHONPATH=. pytest tests/unit/                      # ~0.5s, no services
PYTHONPATH=. pytest tests/integration/               # needs PostgreSQL + OpenSearch
PYTHONPATH=. pytest tests/e2e/                       # full system
PYTHONPATH=. pytest tests/ -m phase1                 # by marker
make ci                                  # black + isort + flake8 + mypy + unit + frontend

# Pre-commit/push gates (local-only, in .git/hooks/)
make smoke-local-quick                    # ~13s, search-intent smoke (pre-commit fires on backend changes)
make smoke-local                          # ~90s, full 20-test suite (pre-push fires on backend changes)

# Frontend (from langchain_agent/web/)
npm install && npm run dev                # :5173, proxies API to :8000
npm run lint && npm run test              # Vitest, 101+ tests

# Deployment
./scripts/deploy.sh --project <GCP_PROJECT_ID>
./scripts/gcp-init.sh --project <GCP_PROJECT_ID>     # first-time GCP setup
```

## Reference Docs

Detailed information has been moved to memory to keep CLAUDE.md concise:
- **Recent fixes & status** → `memory/project_status_recent_fixes.md`
- **Repository layout** → `memory/reference_repository_layout.md`
- **ESCI data & Lucille ingest** → `memory/reference_esci_data_lucille_ingest.md`
- **CI/CD workflows** → `memory/reference_cicd_github_actions.md`
- **Environment variables & scripts** → `memory/reference_environment_vars_scripts.md`
- **Testing & troubleshooting** → `memory/reference_testing_troubleshooting.md`
