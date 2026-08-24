# CLAUDE.md

Guidance to Claude Code (claude.ai/code) when working with this repository.

## New Session Checklist

When a new work session begins (especially when picking up an issue, feature, or non-trivial fix), **suggest creating a feature branch before writing code**. Confirm `git status` is clean and `main` is up to date, then propose a branch name (e.g. `feat/issue-6-judge-categories`, `fix/citation-urls`). Do not start editing on `main`. Skip only for one-line typos or doc tweaks the user explicitly says to commit straight to `main`.

## Recent Fixes & Status (2026-06-13)

- **Issue #69** (PR #73 / commit 3950a4f) — Switched BM25 analyzer from `snowball` (aggressive) to `kstem` (light stemming) for precision. Added `.heavy` sub-fields (snowball) at ^0.3 boost for recall insurance. Improves brand name precision (Beats ≠ beat) and adjective distinction (wireless ≠ wire) while maintaining morphological recall via dense vectors. All 730 unit tests pass; local + remote OpenSearch reindexed.
- **Issue #28** (PR #29 / commit be236e7) — Fixed Swagger page iframe hardcoding localhost URL in production, breaking browser back button. Now uses smart origin detection (localhost → :8000, else → window.location.origin).
- **Issues #20 + #22** (PR #27 / squash ad0f36b) — Warmer agent tone + observability snapshot hydration from LangGraph checkpoints.
- **Cross-encoder latency** (PR #26 / commit 10609a1) — Smoke test SLO raised 30s → 45s to accommodate FETCH_K=40 + cross-encoder model load time on first request.

## Project Overview

**Agentic Hybrid Search** — production-grade LangGraph RAG agent for Amazon ESCI e-commerce product search. Hybrid BM25 + vector retrieval with dynamic alpha per intent, reranking with quality gate, real-time WebSocket streaming. Deployed on GCP Cloud Run with Google Gemini.

## Repository Layout

- `langchain_agent/` — main application
  - `main.py` — LangGraph pipeline (~2,600 lines): intent classifier, query rewriter, query evaluator, retriever, reranker, quality gate, agent
  - `agent_state.py` — `CustomAgentState` TypedDict (~15 fields, only `messages` guaranteed)
  - `config.py`, `exceptions.py` (`AgenticHybridSearchError` root), `logging_config.py` (structlog)
  - `vector_store.py` — `OpenSearchVectorStore` + `OpenSearchRetriever` with RRF fusion
  - `reranker.py` — `GeminiReranker`, Pydantic-validated 0.0–1.0 scoring
  - `link_verifier.py`, `embedding_cache.py`, `retry_utils.py`, `doc_replacer.py`
  - `judge.py` — `LLMJudge` (Gemini Flash Lite, blind A/B with positional-bias randomization) producing `JudgmentResult`: pairwise verdict + 4 absolute scores (faithfulness/answer_relevance/citation_accuracy/context_utilization) + `List[FlaggedClaim]`. Each `FlaggedClaim` carries a `HallucinationCategory` (fabrication, cross_product_bleed, inference, overreach). `RETRY_ELIGIBLE_CATEGORIES = {fabrication, cross_product_bleed}` — see issue #6 / PR #11.
  - `relevancy_metrics.py` — pure-function metrics (`dcg`, `ndcg_at_k`, `mrr`, `recall_at_k`, `precision_at_k`, `compute_stage_metrics`, `confidence_from_scores`, `count_rank_changes`, `latency_cost_benefit`); zero deps for Cloud Run
  - `setup.py`, `benchmark_search.py`, `checkpoint_maintenance.py`, `checkpoint_optimizer.py`, `migrate_to_hnsw.py`
  - `api/` — FastAPI backend
    - `api/main.py`, `api/routes/{chat,conversations,health}.py`
    - `api/schemas/events.py` — Pydantic event models (must stay in sync with `web/src/types/events.ts`)
    - `api/middleware/{auth,origin_auth,session_auth}.py`
    - `api/services/observable_agent.py` — emits typed events
  - `web/` — React 18 + TypeScript + Tailwind + Zustand frontend
    - `web/src/stores/{chatStore,observabilityStore,authStore}.ts`
    - `web/src/types/events.ts` — must match `api/schemas/events.py`
    - `web/src/hooks/useWebSocket.ts`
    - `web/src/components/ObservabilityPanel/PipelineSummaryCard.tsx` — renders BM25 vs Hybrid vs Reranked NDCG@10/MRR/Recall@20/Precision@10 + lift-per-100ms (falls back to confidence-proxy when no judgments)
  - `tests/` — `unit/` (~668), `integration/`, `e2e/`; markers: phase1-3, unit, integration, e2e, slow, auth, search, rerank, websocket, database, content_generation
  - `scripts/` — `setup.sh`, `teardown.sh`, `start.sh`, `stop.sh`, `deploy.sh`, `gcp-init.sh`, `gcp-teardown.sh`
  - `Dockerfile`, `Makefile`, `.env.example`, `cloudbuild.yaml`
- `docker-compose.yml` (repo root) — local PostgreSQL + OpenSearch + Dashboards
- `web/` — skeleton web app (separate from `langchain_agent/web/`)
- `data/` — precomputed ESCI parquets shipped with the repo; read by Lucille ETL (`esci_products_sample_10000.parquet`, `esci_judgments_aggregated.parquet`)
- `esci/` — Amazon Shopping Queries Dataset (external, gitignored; cloned by `setup.sh`)

## Pipeline

```text
Intent Classifier → Query Rewriter → Query Evaluator → Retriever → Reranker → Quality Gate → Agent
```

Six intent classes: `search`, `comparison`, `attribute_filter`, `refinement`, `follow_up`, `summary`. See `ARCHITECTURE.md` for node-by-node detail.

**Intent Classifier** — keyword fast-path + LLM fallback. Confidence < 0.7 triggers clarification.

**Query Rewriter** (`_expand_vague_query`) — resolves follow-up references using conversation history. Detects pronouns, comparatives, short attribute questions. Skips when query has a specific brand/product. Emits `QueryExpansionEvent`.

**Query Evaluator** — sets `dynamic alpha`. Fast-path: comparison=0.60, attribute_filter=0.25, refinement=0.35. LLM path for search/follow_up. Alpha guide:

- Exact model numbers/ASINs → 0.0 (lexical)
- Attribute filter → 0.25
- Refinement → 0.35
- Comparison → 0.60
- Activity-based → 0.5–0.65
- Conceptual → 0.7–0.85
- Gift ideas/exploration → 1.0 (semantic)

**Retriever** — hybrid vector + BM25 fused via Reciprocal Rank Fusion (k=60). Runs hybrid + BM25-baseline in parallel (2-thread `ThreadPoolExecutor`; opensearch-py releases GIL during I/O). For `attribute_filter` intent, extracts brand/color constraints and applies normalized-field filters (`product_color_primary`, `product_color_secondary`, `product_brand_normalized`); see **Attribute Normalization** below. Adds `retrieved_documents`, `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms`. `judgments` is per-query ESCI judgment lookup or `None`. **Filter relaxation**: for `attribute_filter`/`refinement` intents, if the initial hybrid fetch returns fewer than 3 docs, the node drops `multi_match` (material_or_feature/size) filters and retries — color and brand `match` filters are kept since the user explicitly named them.

**Reranker** — LLM-scored 0.0–1.0; sets `reranker_max_score`.

**Quality Gate** — uses intent-specific thresholds (comparison=0.55, search/follow_up=0.50, attribute_filter/refinement=0.45). If `reranker_max_score < threshold` and not yet retried, adjusts alpha ±0.3 and retries; otherwise continues. Returns `quality_gate_threshold_used` so the observability panel displays the intent-specific value, not the global default.

**Agent** — conversational response with citations. ESCI products (no `url` metadata) cite via `https://www.amazon.com/s?k={title}` (search by title — robust against delisted ASINs; the legacy `/dp/{ASIN}` form 404'd often, see PR #10 / issue #4). Agent prompt forbids inline URLs; `_strip_inline_links` belt-and-suspenders post-processor drops any markdown/bare URL the LLM emits anyway. Citations dedup by URL, filtered by min reranker relevance (0.10). **CRITICAL**: All return paths in `agent_node` must include `"citations"` key (either populated list or empty list) — observable_agent depends on consistent state shape. Three early-return branches (summary, clarify, no-info) must return `"citations": []` (see issue #14 / commit b24719d).

**LLM Judge** (`llm_judge_node`) — runs after `agent_node` when both `optimizations.llm` and `optimizations.llm_judge` are on. Produces a `JudgmentResult` with categorically-tiered flagged claims. **Auto-correction retry (Layer 3a)** fires when at least one flag has `category in {fabrication, cross_product_bleed}` and we haven't already retried this turn — the `faithfulness` score is NOT checked (issue #77: the LLM can assign a high score while simultaneously flagging fabrications, making it an unreliable gate; categorical classification is the authoritative signal). Inference/overreach flags surface in the UI but skip the ~20-30s retry tax. The regenerator is given only retry-worthy claim text (don't ask the model to "fix" inference flags). **`hallucination_retry_used` is reset to `False` in `intent_classifier_node` at the top of every new user turn** (issue #83) — without this reset, LangGraph persists the flag through Postgres checkpoints, permanently disabling the gate for all subsequent turns in the same thread after the first retry fires. **`_format_docs_for_prompt` default `max_chars` is 10 000** (raised progressively: 360 → 1500 in PR #82, then 1500 → 2500 in issue #84, then 2500 → 10 000 to eliminate truncation entirely for any realistic ESCI product): ESCI products with both a prose description and Amazon bullet points can reach ~2498 chars, with key construction attributes (e.g. Thursday Boot "cork-bed midsoles") appearing as late as char 2039 — a tighter limit causes the judge to false-positive flag grounded claims as fabrications. 10 000 is a safety cap against pathological documents, not a tuned budget (4 docs × 10 000 chars ≈ 10 000 tokens, negligible for Gemini Flash Lite's 1M-token context).

### Observable Events

WebSocket-streamed Pydantic events: `SearchProgressEvent`, `RerankerProgressEvent`, `QualityGateEvent`, `QueryExpansionEvent`, `OpenSearchQueryEvent` (alpha/intent/filters + `body`/`index`/`params` DSL fields, tagged with `query_type` ∈ {`hybrid`, `bm25_baseline`, `quality_gate_retry`}; embedding vectors scrubbed to `<EMBEDDING_OMITTED_768_DIMS>`; the retriever node emits one `hybrid` and one `bm25_baseline` per request, `quality_gate_retry` only when the gate fires; surfaced in the UI by the DSL eye-icon viewer in `DslViewerModal.tsx`), `LLMResponseChunkEvent`, `LLMResponseCorrectedEvent` (emitted by `llm_judge` node when `hallucination_retry_used=True` + `corrected_response` is set; carries `corrected_content`, `original_faithfulness`, `corrected_faithfulness`; the frontend `useWebSocket` handler calls `correctLastAssistantMessage` in `chatStore` to replace the streamed message and sets `corrected=true` on the `ChatMessage`, which renders an amber "AI-corrected" badge with a "Show original" toggle in `Message.tsx`; only `fabrication` and `cross_product_bleed` judge categories trigger this — `inference`/`overreach` stay warning-only in the observability panel), `ClarificationRequestedEvent`, `ClarificationResolvedEvent`, `PipelineSummaryEvent` (per-stage NDCG/MRR/Recall/Precision + lift-per-100ms; emitted once after `AgentCompleteEvent`; falls back to confidence-proxy when no judgments exist; `corrected_response` field still present here for the observability panel diff view).

**Critical**: `api/schemas/events.py` must stay in sync with `web/src/types/events.ts`. Each event's `node` field pins it to a pipeline step regardless of emission order.

### Tech Stack

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

- **Bare imports & PYTHONPATH** — modules use `from config import ...`. All Python invocations from `langchain_agent/` need `PYTHONPATH=.` (pytest, main, custom scripts). Omitting it causes `ModuleNotFoundError`.

- **Frontend origin detection** — Components that embed iframes or make cross-domain requests should detect environment at runtime, not use hardcoded defaults. Pattern: (1) try to fetch config endpoint `/api/config`, (2) if config returns `apiUrl`, use it, (3) else fall back to smart detection: localhost → `http://localhost:8000`, non-localhost → `window.location.origin`. This ensures browser history and iframe src never contain hardcoded localhost in production. See `SwaggerPage.tsx` (issue #28).

- **State access** — `CustomAgentState` is `total=False`; only `messages` guaranteed. Always `state.get("field", default)`.
  - Classifier adds: `intent`, `confidence`, `user_query`
  - Query Evaluator adds: `alpha`, `intent_description`
  - Retriever adds: `retrieved_documents`, `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms`
  - Reranker adds: `reranker_max_score`, `reranked_documents`, `reranker_latency_ms`
  - Quality Gate adds: `quality_gate_retried`, `alpha_adjusted_value`, `quality_gate_threshold_used`
  - Other: `thread_id`, `current_node`, `retrieved_products`, `citations`

- **Dual-analyzer BM25** (issue #69) — In hybrid pipelines, dense vectors handle morphological recall ("running/runs/ran"). BM25 should focus on precision confirmation. Primary fields (`chunk_text`, `product_brand`, `product_color`) use `light_english_analyzer` (kstem) for precision. Sub-fields (`.heavy`) use `heavy_english_analyzer` (snowball) at ^0.3 boost for recall fallback. Balances precision (Beats ≠ beat) with recall (morphological variants via .heavy + embeddings). Updated `_build_multi_match()` to include `.heavy` fields in candidate field list.

- **Hybrid search** — RRF fusion (k=60); `alpha` ∈ [0,1] weights lexical→semantic.
- **Product dedup** — `OpenSearchRetriever.collapse_by_document()` for `esci_products`.
- **No chunking for products** — ESCI products indexed whole (50–500 words). Controlled by `CHUNKING_STRATEGY`.
- **Attribute normalization** — post-ingest enrichment adds normalized fields for better filter recall. `product_color_primary`, `product_color_secondary`, `product_brand_normalized` are keyword fields populated by `scripts/enrich_attribute_normalization.py` (Step 5b of `lucille_ingest.sh`). Uses `AttributeNormalizer` class with deterministic rules: 16 canonical colors (e.g., "grey" → "gray"), synonym expansion, compound extraction ("Black & Purple" → primary: "black", secondary: "purple"), brand case-folding. Improves recall: "blue" now matches "Navy", "Cyan", "Teal", etc. Raw fields preserved, no data loss. Reproducible and auditable (rules-only, no AI).

- **Dual-mapped attributes** — `product_brand` and `product_color` mapped as both `text` (BM25) and `keyword` (faceting). Use `.keyword` for aggregations. Filters use normalized fields instead (`product_color_primary`, `product_brand_normalized`).
- **Faceting** — `OpenSearchVectorStore.get_facets()`.
- **Error hierarchy** — all custom exceptions inherit from `AgenticHybridSearchError`.

- **Auth** — two layers, both enforced on protected routes:
  1. **Same-origin** (`origin_auth.py:verify_same_origin`) — allow-list of localhost dev ports + Cloud Run `*.run.app`. Host fallback only when **both** Origin AND Referer absent. Disallowed Origin always 403s.
  2. **Shared-password session + admin token** (`session_auth.py:verify_session`, `verify_admin_token`, added 2026-04-29 in PR #8 / #13):
     - **Session**: `LOGIN_PASSWORD` env var. `POST /api/auth/login` validates via `hmac.compare_digest`, sets Starlette `SessionMiddleware`-signed HttpOnly + SameSite=Lax cookie (`ahs_session`). REST routes call `verify_session(request)`; WS handshake calls `verify_websocket_session(websocket)` which closes with code **4401** on rejection. Frontend `useWebSocket` translates 4401 → `authStore.markUnauthenticated()` → LoginScreen re-render. Logout button in conversations sidebar (two-click confirm).
     - **Admin token** (automation): `ADMIN_TOKEN` env var (32+ chars). GitHub Actions and unattended callers use `X-Admin-Token` header. Routes first try session, catch `HTTPException`, fall back to token. Constant-time comparison via `hmac.compare_digest` prevents timing attacks. Applied to `/api/admin/*` routes (reindex, health, diagnose) and `/api/health` for automation (2026-04-30 PR #13).
  - Required env: `LOGIN_PASSWORD`, `SESSION_SECRET` (≥32 chars), `SESSION_COOKIE_SECURE` (true on Cloud Run, false for local HTTP), `SESSION_MAX_AGE_SECONDS`. Optional: `ADMIN_TOKEN`. Lifespan fails fast on missing required vars.
  - Legacy `API_KEY` / `verify_api_key` middleware exist but are dead code on protected routes — **do not wire new routes through `verify_api_key`**. Use `verify_same_origin` + `verify_session` (or `verify_admin_token` for automation).

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

# Lifecycle scripts (non-interactive)
./scripts/setup.sh                        # ESCI clone, venv, deps, Docker, DB init, ingest
./scripts/teardown.sh                     # remove everything (keeps .env)
./scripts/start.sh                        # Docker + backend + frontend
./scripts/stop.sh

# ESCI ingestion — default path via Lucille ETL (Docker must be up, requires Java 17+ and Maven)
bash scripts/lucille_ingest.sh                                # products + judgments, no API calls

# ESCI Relevancy Benchmarks (docker compose up -d required; see BENCHMARK_RESULTS.md for full docs)
make benchmark-esci-fast    # ~5 min, deterministic (no LLM), reproducible
make benchmark-esci         # ~10 min, full adaptive (requires GOOGLE_API_KEY)

# Other tools
PYTHONPATH=. python benchmark_search.py
PYTHONPATH=. python checkpoint_maintenance.py
PYTHONPATH=. python checkpoint_optimizer.py

# Tests (PYTHONPATH=. required)
PYTHONPATH=. pytest tests/unit/                    # ~0.5s, no services
PYTHONPATH=. pytest tests/integration/             # needs PostgreSQL + OpenSearch
PYTHONPATH=. pytest tests/e2e/                     # full system
PYTHONPATH=. pytest tests/ -m phase1               # by marker
PYTHONPATH=. pytest tests/ -k "test_auth"          # by name
PYTHONPATH=. pytest --cov=. --cov-report=html

# Lint / format / CI gate
make lint                  # pylint
make format                # black
make format-fix            # black + isort (run before every commit)
make type-check            # mypy
make ci                    # black + isort + flake8 + mypy + unit + frontend
                           # ALSO runs pytest --collect-only on tests/integration/ + tests/e2e/
make ci-frontend           # frontend tests + eslint + tsc
make ci-docker             # validate Dockerfile builds locally
make smoke-local           # full e2e smoke suite vs local backend (~90s, 20 tests)
make smoke-local-quick     # search-intent smoke only (~13s, what pre-commit runs)

# Two-tier git hooks (.git/hooks/, local-only):
#
# Pre-commit (~13s on backend changes; runs every commit):
#   1. black + isort + flake8 on staged .py files
#   2. SMOKE GATE — `make smoke-local-quick` (focused search-intent test, ~13s)
#      when files in api/services/, api/routes/, api/main.py, main.py, or
#      agent_state.py are staged. Reuses uvicorn on :8000 if running.
#
# Pre-push (~30s baseline, ~2-3min if smoke gate fires; runs once per push):
#   1. git-lfs pre-push (preserved from default)
#   2. `make ci` — full local CI gate (lint + unit + frontend + collect-only)
#   3. SMOKE GATE — `make smoke-local` (full 20-test suite, ~90s) when any
#      backend-path file (api/services/, api/routes/, api/main.py, main.py,
#      agent_state.py, or api/schemas/) was changed in the push range.
#
# Both gates fail-open if Docker is down (so hotfixes aren't blocked) and
# print a loud warning. Bypass with `--no-verify` (NOT recommended).
# Worked example: runs #160-#171 burned chasing a deadlock+UnboundLocalError
# that smoke-local would have caught in 90s. See memory/feedback_local_smoke_before_deploy.md.

# Frontend (from langchain_agent/web/)
npm install
npm run dev
npm run build
npm run lint
npm run test               # Vitest, 101+ tests

# Deployment
./scripts/deploy.sh --project <GCP_PROJECT_ID>
./scripts/gcp-init.sh --project <GCP_PROJECT_ID>     # first-time: Cloud SQL + ingest
./scripts/gcp-teardown.sh --project <GCP_PROJECT_ID>
```

## ESCI Data

**Default ingest path:** `bash scripts/lucille_ingest.sh` — reads precomputed files from `data/`, no embedding API calls, ~25s.

```bash
data/
├── esci_products_sample_10000.parquet   # 9,618 US products, precomputed 768-dim embeddings (seed=42)
└── esci_judgments_aggregated.parquet    # 97,345 queries × nested judgments, pre-aggregated for Lucille
```

Lucille config: `langchain_agent/lucille-esci/conf/`. `collection_id=esci_products` is set on every product doc — required by all search queries in `vector_store.py`.

The custom `lucille-esci` Maven module (configs + mappings) lives in-repo; the **upstream Lucille source tree is external** (default `~/github/kmwtechnology/lucille`, override via `LUCILLE_DIR`). `lucille_ingest.sh` Step 1 builds `lucille-bom` + `lucille-parquet` (currently `1.0.0-SNAPSHOT`) from that checkout into `~/.m2` on first run only; after that the checkout isn't read again. Bump `lucille.version` in `lucille-esci/pom.xml` + `LUCILLE_VERSION` in the script together when the external repo's version moves.

### Ingest (Lucille ETL — `scripts/lucille_ingest.sh`)

Lucille is the **only** ingest mechanism. Python ingest scripts (`ingest_esci_products.py`, `ingest_esci_judgments.py`) were removed in PR #48.

1. Reads precomputed parquets from `data/` — no Google API calls for the 10k sample
2. `products.conf` (Lucille) — sets `chunk_text`, `collection_id=esci_products`, dual-mapped brand/color fields; **also copies `product_title → title_suggest` and `product_brand → brand_suggest`** (edge-ngram fields required by `/api/suggest`; missing = typeahead returns 0 results)
3. `judgments.conf` (Lucille) — reads `esci_judgments_aggregated.parquet` (pre-aggregated by `prepare_judgments_parquet.py`)
4. ESCI labels → graded relevance: E=4.0, S=1.0, C=0.1, I=0.0 (set in `data/esci_judgments_aggregated.parquet`)
5. `OpenSearchVectorStore.lookup_judgments(query)` → exact `term` match on `query.keyword`. No fuzzy fallback.
5b. **Post-ingest enrichment** (`scripts/enrich_attribute_normalization.py`) — adds normalized color/brand fields for better filter recall. Populates `product_color_primary`, `product_color_secondary`, `product_brand_normalized` on all docs via bulk update. Uses deterministic rules (16 canonical colors, synonym expansion, compound extraction). Reproducible and auditable.

Flags: `--reset-index` atomically deletes+recreates the index via `setup.py --reset-index --skip-db --skip-docs --skip-models` (Python, not curl) before Lucille starts — prevents the race where Lucille's indexer auto-creates a broken default-mapped index between a curl DELETE and the next write; `--skip-judgments` skips the judgments step.

## Scripts

- `setup.sh` — one-time non-interactive: prereqs check (Docker, Python 3.14, Node, **Java 17+, Maven**), ESCI clone (~1GB), venv + deps, Docker up, `setup.py` (which calls `lucille_ingest.sh`). Creates `.env` from `.env.example` if missing; requires manual `GOOGLE_API_KEY`.
- `teardown.sh` — kills :8000/:5173, removes Docker containers + volumes, `.venv`, `node_modules`, logs. Keeps `.env` by default.
- `start.sh` / `stop.sh` — start/stop Docker + backend + frontend (Vite proxies API to :8000).
- `deploy.sh` — Cloud Run deploy with Cloud SQL + Secret Manager + autoscaling.
- `gcp-init.sh` — first-time GCP setup: Cloud SQL (PostgreSQL 16), schema + checkpoints table, product + judgment ingestion **via Lucille ETL** (runs on a workstation with Java/Maven + a Lucille checkout; reads static parquets from `data/`), API validation. It exports `OPENSEARCH_HOST`/`PORT`/`USE_SSL` for the hosted instance; `lucille_ingest.sh` loads `.env` with **non-override** semantics so those exports win (otherwise `.env`'s `localhost` would silently capture the ingest). **There is no in-container ingest** — the slim Cloud Run image has no Java; re-indexing is triggered via `reindex.yml` (Lucille on the Actions runner) or manually via `lucille_ingest.sh` with the hosted OpenSearch vars.
- `gcp-teardown.sh` — removes Cloud Run, Cloud SQL + backups, OpenSearch, Artifact Registry, Secrets.

## CI/CD — GitHub Actions

- `.github/workflows/test.yml` — every PR/push: backend unit + integration (with PostgreSQL + OpenSearch), lint (flake8/black/isort/mypy), Playwright e2e, coverage.
- `.github/workflows/build-deploy.yml` — main only: Docker build (cached) → push to `us-central1-docker.pkg.dev/<PROJECT_ID>/agentic-hybrid-search/agentic-hybrid-search:latest` → Cloud Run blue-green deploy → smoke tests on `/health` → 100% traffic. **Docker layer note:** `torch` CPU-only wheel is installed as a separate layer before `pip install -r requirements.txt` — this keeps the pip layer ~750MB instead of ~3GB (Cloud Run is CPU-only; GPU CUDA libraries in the default PyPI wheel are dead weight). LFS objects (`data/*.parquet`) are cached between builds via `actions/cache` keyed on file content hash. **Cross-encoder baked into image (issue #78):** the reranker model (`cross-encoder/ms-marco-MiniLM-L-12-v2`, ~128MB, `config.CROSS_ENCODER_MODEL`) is pre-downloaded at build time into `HF_HOME=/opt/hf-cache`, and runtime sets `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`. **Do NOT remove these** — without the baked model the image fetches it from HuggingFace Hub *unauthenticated at every cold start*, which trips HF's anonymous per-IP rate limit during a deploy burst and hangs agent init indefinitely (full outage; took down prod 2026-06-13, see `memory/cross_encoder_hf_runtime_fetch_outage.md`). Keep the Dockerfile model id in sync with `config.CROSS_ENCODER_MODEL`.
- Auth: Workload Identity Federation (no long-lived keys). GitHub secrets: `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`. Service account `github-actions@gen-lang-client-0250737934.iam.gserviceaccount.com` has roles `artifactregistry.writer`, `run.developer`, `iam.serviceAccountUser`. WIF setup is one-time and complete; see `memory/github_actions_cicd.md` for the full bootstrap commands.
- Monitoring: <https://github.com/kmwtechnology/agentic-hybrid-search/actions>; `gcloud run services logs read agentic-hybrid-search --region=us-central1 --project=gen-lang-client-0250737934 --limit 50`.

## Testing

- **Python 3.14** required (pytest.ini `minversion = 3.14`).
- **Unit tests** (~696 Python + 118 frontend) — no external deps; `PYTHONPATH=. pytest tests/unit/` (~3s).
- **CRITICAL — when modifying `tests/e2e/` or `tests/integration/`**: `make ci` runs `pytest --collect-only` on both directories to catch import errors, signature changes, library API drift (e.g., `websockets` v14 renamed `extra_headers` → `additional_headers` and moved connect to `websockets.asyncio.client`). Collection ≠ execution but catches the failures unit tests don't. **Do not push e2e/integration changes without `make ci`** — these only run live in CI against Cloud Run.
- **CRITICAL — local smoke gate before pushing backend changes**: when modifying anything under `api/services/`, `api/routes/`, `api/main.py`, `main.py`, or `agent_state.py`, run `make smoke-local-quick` (or full `make smoke-local`) against the local backend before push. The pre-commit hook auto-triggers this when those paths are staged AND Docker is up. **This catches the WebSocket/observability regression class** (deadlocks, unbound-asyncio, event-emission failures) that unit tests can't see and that otherwise costs a 14-min Cloud Run cycle to discover. Worked example: runs #160-#171 burned chasing an "agent_complete never emitted" bug whose root cause (`_warmup_lock` deadlock + local `import asyncio` shadowing) was visible in seconds against a local backend. See `memory/feedback_local_smoke_before_deploy.md`.
- **Pre-flight static guards** (in `tests/unit/`, run by `make ci`) — added 2026-04-29:
  - `test_e2e_event_types.py` — every `event["type"] == "..."` literal in `tests/e2e/` must exist in `api/schemas/events.py`.
  - `test_e2e_payload_shapes.py` — AST-walks `json.dumps({...})` in `tests/e2e/`; validates inbound WS contract (`{"type": "chat_message", "message": ..., "thread_id": ...}`).
  - `test_e2e_ws_url_routes.py` — every `/ws/...` URL must match a registered FastAPI route.
  - `test_frontend_backend_event_parity.py` — backend `Literal[...]` event types must exist in `web/src/types/events.ts`; per-event `node:` literals must agree.
  - `test_origin_auth_contract.py` — disallowed Origin + Cloud Run Host **must** 403; Host fallback only with both Origin and Referer absent.
  - `test_smoke_test_budget.py` — counts `chat_message` sends per smoke method × 25s/msg + 5s setup, asserts pytest `--timeout` covers it.
- **Smoke-test budget on Cloud Run**: single `chat_message` round-trip = 16–25s end-to-end. Workflow `pytest --timeout=120` covers two sequential messages. Don't tighten without reading `test_smoke_test_budget.py:PER_CHAT_MESSAGE_BUDGET_S`.
- **Live cloud-run + data e2e on every push to main** — 18 smoke + 17 cloud-run + 10 data = 45 real assertions (first fully-active green: 2026-04-29 run 25126889201). Both files use `websockets.asyncio.client` + `additional_headers={"Origin": ORIGIN_HEADER}`; `_skip_if_origin_blocked` is now `pytest.fail`.
- **Local e2e iteration**: `get_allowed_origins()` includes `http://localhost:8000` (and 127.0.0.1) for direct (non-Vite) drive:

  ```bash
  CLOUD_RUN_URL=http://localhost:8000 \
    LOGIN_PASSWORD=$(grep '^LOGIN_PASSWORD=' .env | cut -d= -f2) \
    PYTHONPATH=. .venv/bin/pytest tests/e2e/<file> -v -ra --tb=short \
    -m "e2e and slow" --timeout=120 --asyncio-mode=auto
  ```

  `tests/e2e/conftest.py` does login once per session; exposes `auth_ws_headers()` / `auth_rest_headers()` / `get_auth_cookie()`. Missing `LOGIN_PASSWORD` raises a clear `AssertionError`.

## Environment

Copy `langchain_agent/.env.example` → `langchain_agent/.env`.

### Required

- `GOOGLE_API_KEY` — LLM/embeddings (<https://aistudio.google.com/apikey>)
- `LOGIN_PASSWORD` — shared password for LoginScreen (auto-generated by `setup.sh`, 12 hex chars)
- `SESSION_SECRET` — cookie-signing secret ≥32 chars (auto-generated by `setup.sh` via `openssl rand -hex 32`)
- `API_KEY` — legacy; required by lifespan but unused on routes (cleanup pending)

### Database

`POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=postgres`, `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`, `POSTGRES_DB=langchain_agent`

### OpenSearch

`OPENSEARCH_HOST=localhost`, `OPENSEARCH_PORT=9200`, `OPENSEARCH_USER=` (empty for local Docker), `OPENSEARCH_PASSWORD=`, `OPENSEARCH_USE_SSL=false`, `OPENSEARCH_VERIFY_CERTS=false`, `OPENSEARCH_INDEX_NAME=agentic_hybrid_search_docs`

### Models & Retrieval

- `LLM_MODEL=gemini-3-flash-preview`, `LLM_TEMPERATURE=0`
- `EMBEDDINGS_MODEL=models/gemini-embedding-001`, `VECTOR_DIMENSION=768` (set `output_dimensionality=768`)
- `RERANKER_MODEL=gemini-3.1-flash-lite-preview`, `QUERY_EVAL_MODEL=gemini-3.1-flash-lite-preview`
- `RETRIEVER_K=4`, `RETRIEVER_FETCH_K=30`, `RETRIEVER_ALPHA=0.25`
- `ENABLE_RERANKING=true`, `RERANKER_FETCH_K=15`, `RERANKER_TOP_K=4`
- `ENABLE_QUERY_EVALUATION=true`, `QUERY_EVAL_TIMEOUT_MS=3000`
- `ENABLE_COMPACTION=true`, `MAX_CONTEXT_TOKENS=3000`, `DEFAULT_THREAD_ID=default_thread`

### Session / CORS

- `SESSION_COOKIE_SECURE=true` (Cloud Run TLS) / `false` (local HTTP)
- `SESSION_MAX_AGE_SECONDS=86400`
- `CORS_ORIGINS=` — comma-separated; empty for local

### ESCI

`ESCI_DATASET_DIR=../esci/shopping_queries_dataset` (used only by Python fallback scripts; Lucille reads from `data/` directly), `ESCI_PRODUCT_LOCALE=us`, `ESCI_INGEST_LIMIT=10000`

### Logging & Frontend

- `LOG_LEVEL=INFO`, `LOG_FORMAT=console` (dev) | `json` (prod)
- `VITE_API_URL` — auto-set by `setup.sh`. Frontend never receives `LOGIN_PASSWORD`/`SESSION_SECRET`; user types into LoginScreen; cookie rides via `credentials: 'include'`.

### Optional

- `LANGSMITH_API_KEY=` (<https://smith.langchain.com>), `LANGSMITH_PROJECT=agentic-hybrid-search`

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'config'` | missing `PYTHONPATH=.` | `PYTHONPATH=. python ...` from `langchain_agent/` |
| `ConnectionError: Error connecting to OpenSearch` | OpenSearch not running | `docker compose up -d`; verify with `curl http://localhost:9200` |
| `ConnectionError: Error connecting to database` | PostgreSQL not running | `docker compose up -d`; check `POSTGRES_*` in `.env` |
| `Google AI API validation failed` | missing/invalid `GOOGLE_API_KEY` | get key from aistudio.google.com/apikey, set in `.env`, re-run `setup.py` |
| ESCI parquet missing | dataset not downloaded | `ls ../esci/shopping_queries_dataset/shopping_queries_dataset_products.parquet`; download if missing |
| Tests fail with import errors | no `PYTHONPATH=.` | `export PYTHONPATH=.` then run pytest |
| WebSocket connection refused | backend not up / wrong URL | `make dev-api`; `lsof -i :8000` |
| `npm install` fails | Node version mismatch | `node --version` (must be 24+; CI/Docker build on 24 LTS); `rm -rf node_modules package-lock.json && npm install` |
