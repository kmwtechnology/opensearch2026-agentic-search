# Agentic Hybrid Search — E-Commerce Product Search Agent

> See also: [repo root README](../README.md) ·
> [tests/README.md](tests/README.md) ·
> [tests/e2e/README.md](tests/e2e/README.md)

A production-grade LangGraph RAG agent for e-commerce product discovery.
Uses Google Gemini for LLM inference and embeddings, OpenSearch for hybrid
vector + BM25 search, and PostgreSQL for LangGraph checkpoints.

**Capabilities:**

- **6-intent classification** — `search`, `comparison`, `attribute_filter`,
  `refinement`, `follow_up`, `summary`. Keyword fast-path + LLM fallback.
- **Hybrid retrieval** — vector (768-dim Gemini embeddings) + BM25, fused via
  RRF (k=60), with dynamic α per intent.
- **Cross-encoder reranking** — `ms-marco-MiniLM-L-12-v2` scores
  query-product relevance (~10ms); Gemini Flash Lite fallback (~500ms).
- **Quality gate** — retries once with α ±0.3 (fabrication/cross-product-bleed triggers auto-correction ~30s; inference/overreach surface only) if max reranker score < 0.5.
- **Real-time streaming** — token-by-token WebSocket output with full
  observability events.
- **Pipeline Quality Summary** — per-turn scorecard (NDCG@10 / MRR /
  Recall@20 / Precision@10 against ESCI judgments, or a self-referential
  confidence proxy when ground truth is unavailable) with a latency
  cost-benefit table.
- Data is the Amazon ESCI / Shopping Queries Dataset (products + relevance judgments).

**Stack:**

- **Backend:** Python 3.14+, FastAPI, LangGraph, LangChain
- **Frontend:** React 18, TypeScript, Tailwind, Zustand
- **Data layer:** OpenSearch 2.19.1 (HNSW + BM25) · PostgreSQL 16
  (LangGraph checkpoints only)
- **LLM:** Google Gemini 3 Flash (generation) + Gemini 3.1 Flash Lite
  (classify/rerank) · `models/gemini-embedding-001` (embeddings)

---

## Deployment Paths

This application has two supported run paths:

- **Path A: Local development with Docker** — `setup.sh` and `start.sh`
  run PostgreSQL/OpenSearch locally with Docker, plus the FastAPI backend
  and React frontend.
- **Path B: Deployment to GCP** — `deploy.sh` deploys to Cloud Run,
  connects to Cloud SQL for checkpoints, reads secrets from Secret
  Manager, and uses an externally hosted OpenSearch cluster.

Path A is the right starting point for development and tests. Path B is
for deployed Cloud Run environments.

### Prerequisites

Both paths need a Google API key from <https://aistudio.google.com/apikey>.

Path A needs:

```bash
docker --version      # Docker Desktop
python3 --version     # Python 3.14+
node --version        # Node.js 24+
java -version         # Java 17+ (for Lucille ETL ingest)
mvn -version          # Maven 3.8+ (for Lucille ETL ingest)
```

Install Java + Maven on macOS: `brew install openjdk@17 maven`

Path B needs the Google Cloud SDK authenticated to the target project,
permissions for Cloud Run, Cloud SQL, Artifact Registry, Secret Manager,
and IAM, plus a reachable OpenSearch cluster. The deployment scripts do
not provision OpenSearch.

For local browser login, `setup.sh` generates `LOGIN_PASSWORD`,
`SESSION_SECRET`, and `SESSION_COOKIE_SECURE=false` in `.env`. In
production, keep `SESSION_COOKIE_SECURE=true`.

### Path A: Local Development With Docker

```bash
cd langchain_agent
cp .env.example .env
# Set GOOGLE_API_KEY in .env before continuing.
./scripts/setup.sh
./scripts/start.sh
```

Takes ~3–5 min on first run (embeddings are precomputed in the shipped sample — no API calls needed for the default 10 k ingest):

1. Generates a secure `API_KEY`
2. Creates `.venv`, installs Python + frontend dependencies
3. Starts PostgreSQL and OpenSearch via Docker
4. Initializes the checkpoint DB and OpenSearch index
5. Validates the Google AI API key
6. Ingests an ESCI product sample (9,618 docs) and judgments (97,345 queries) via [Lucille ETL](lucille-esci/)

Backend FastAPI runs on `:8000`, React frontend on `:5173` (Vite proxies
`/api` to the backend).

The login password is stored as `LOGIN_PASSWORD` in `.env`. The UI uses a
signed session cookie after login; admin automation can use
`X-Admin-Token: $API_KEY` on protected admin routes.

Stop or clean up local services:

```bash
./scripts/stop.sh
./scripts/teardown.sh
```

Removes running services, the Docker volumes, `.venv`, `node_modules`, and
log files. Keeps `.env` by default (prompted separately).

### Path B: Deployment to GCP

```bash
cd langchain_agent
./scripts/deploy.sh --project <GCP_PROJECT_ID>
./scripts/gcp-init.sh --project <GCP_PROJECT_ID>
./scripts/smoke_test.sh <CLOUD_RUN_URL>
```

`deploy.sh` builds and deploys the Cloud Run service. `gcp-init.sh`
initializes Cloud SQL and ingests ESCI products into OpenSearch. The smoke
test verifies the deployed API.

---

## Usage

### Web UI

Open <http://localhost:5173> and chat. The observability panel on the right
streams every pipeline stage in real time.

### CLI

```bash
source .venv/bin/activate
PYTHONPATH=. python main.py
```

### API

All endpoints require a valid session cookie (issued on
`POST /api/auth/login`). Automated callers can use the `X-Admin-Token`
header instead for admin/health routes.

```bash
# Login and save the session cookie
curl -c /tmp/cookies.txt -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"<LOGIN_PASSWORD>"}' | jq .

# Use the cookie on subsequent requests
curl -b /tmp/cookies.txt http://localhost:8000/api/health
```

The primary surface is the WebSocket endpoint under `/api/chat` — see
`api/routes/chat.py`. REST routes cover health (`/api/health`),
conversation CRUD (`/api/conversations`), typeahead suggestions
(`/api/suggest` — see `api/routes/suggest.py`), and admin reindex
operations (`/api/admin/*` — see `api/routes/admin.py`).

#### Typeahead autocomplete — `GET /api/suggest`

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/suggest?q=nik&limit=8"
```

Response:

```json
{
  "suggestions": [
    {
      "title": "Nike Air Max 90",
      "brand": "Nike",
      "score": 1.0,
      "highlight": ["<mark data-th>Nike</mark> Air Max 90"]
    }
  ],
  "spell_correction": null
}
```

Misspelled queries populate `spell_correction` instead of (or alongside)
`suggestions`:

```bash
curl "http://localhost:8000/api/suggest?q=nikey"
# {"suggestions":[], "spell_correction":{"title":"nike","brand":"Nike","score":0.889}}
```

Behavior:

- Edge-ngram prefix matching on `title_suggest` and `brand_suggest` subfields
- Spell correction via Levenshtein distance + `SequenceMatcher` ratio
  (ratio ≥ 0.6, confidence ≥ 0.5). Returns a `spell_correction` payload
  (`{"title": "...", "brand": "...", "score": 0.xx}`) rendered as "Did you
  mean?" in the UI
- Fuzzy fallback for distance-1 typos (e.g., `"nikey"` → `"nike"`) when the
  primary prefix query returns no results
- Correction is skipped when the query is already a corpus token, or when
  it is a prefix of the candidate (prevents "charg" → "charger" suggestions)

Frontend UI (`web/src/components/ChatPanel/TypeaheadSuggestions.tsx`):

- Three sections: **Did you mean?** (spell correction) → **Suggestions**
  (API results) → **Recent Searches** (localStorage via
  `web/src/hooks/useRecentSearches.ts`, capped at 8, case-insensitive dedup,
  clear button)
- ARIA combobox semantics with `role="combobox"`, `aria-expanded`,
  `aria-activedescendant`
- Keyboard navigation: `ArrowDown`/`ArrowUp` to move, `Enter`/`Tab` to
  accept and submit, `Esc` to close
- Requests use `AbortController` to cancel stale responses

#### Admin API — `/api/admin/*`

```bash
# Kick off a background reindex (optionally resetting the index)
curl "http://localhost:8000/api/admin/reindex?reset_index=true&limit=10000"

# Poll job status: running | success | error
curl http://localhost:8000/api/admin/reindex/status

# Inspect current index health + document count
curl http://localhost:8000/api/admin/health
```

The reindex runs in a background task so the HTTP request returns
immediately. The status endpoint is the source of truth for progress
(`running` → `success` / `error`). A separate GitHub Actions workflow
(`.github/workflows/reindex.yml`) exposes this as a manual-dispatch job for
rebuilding production indexes without redeploying.

#### Conversations observability — `GET /api/conversations/{thread_id}/observability`

- Return the last observability snapshot for a conversation (intent, alpha,
  reranker score, quality gate verdict, per-stage latency). Hydrated from
  the latest LangGraph checkpoint. Returns `has_data: false` when no
  checkpoint exists.

### Example Queries

**RAG Q&A:**

```text
Find wireless headphones under $50
Show me Nike running shoes
Compare Sony WH-1000XM5 vs Bose QuietComfort 45
Make them waterproof                  ← refinement of prior search
Any cheaper options?                  ← follow-up
Summarize our conversation
```

---

## Configuration

Everything lives in `config.py` with `.env` overrides (see `.env.example`).

### Models

```bash
LLM_MODEL=gemini-3-flash-preview                   # generation
RERANKER_MODEL=gemini-3.1-flash-lite-preview       # reranking
QUERY_EVAL_MODEL=gemini-3.1-flash-lite-preview     # query evaluator
EMBEDDINGS_MODEL=models/gemini-embedding-001      # 768-dim embeddings
VECTOR_DIMENSION=768
LLM_TEMPERATURE=0
QUERY_EVAL_TEMPERATURE=0
QUERY_EVAL_MAX_TOKENS=1024
```

### Data stores

```bash
# OpenSearch (hybrid search)
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_INDEX_NAME=agentic_hybrid_search_docs
OPENSEARCH_USE_SSL=false

# PostgreSQL (LangGraph checkpoints only)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=langchain_agent
```

### Retrieval / reranking

```bash
RETRIEVER_K=10              # Final docs
RETRIEVER_FETCH_K=40        # Candidates before reranking
RETRIEVER_ALPHA=0.25        # Default α (evaluator usually overrides)
ENABLE_RERANKING=true
RERANKER_FETCH_K=40         # Candidates reranked
RERANKER_TOP_K=10           # Final top-K
ENABLE_QUERY_EVALUATION=true
QUERY_EVAL_TIMEOUT_MS=3000
```

### Intent routing

The 6-intent classifier routes every turn:

| Intent | Pipeline | Examples |
| --- | --- | --- |
| `search` | RAG Q&A (LLM-path α) | "Find wireless headphones" |
| `comparison` | RAG Q&A (fast-path α=0.60) | "Compare Sony vs Bose" |
| `attribute_filter` | RAG Q&A (fast-path α=0.25) | "Blue running shoes size 10" |
| `refinement` | RAG Q&A (fast-path α=0.35) | "Make them waterproof" |
| `follow_up` | RAG Q&A (LLM-path α, context-aware) | "Any cheaper ones?" |
| `summary` | Summary node (no retrieval) | "Recap our conversation" |

Documentation-style asks ("write a guide", "create a comparison") are
detected during content-type classification inside the generator pipeline
rather than as a separate intent class.

---

## GCP Deployment Details

### Path B: Deploy to Cloud Run

```bash
./scripts/deploy.sh --project <GCP_PROJECT_ID>
```

This will:

1. Build the multi-stage Docker image locally
2. Push to Artifact Registry
3. Deploy to Cloud Run
4. Wire secrets (`GOOGLE_API_KEY`, `API_KEY`, OpenSearch creds) via Secret Manager
5. Connect to Cloud SQL via the built-in proxy

### Path B: One-time Cloud SQL + product ingestion

```bash
./scripts/gcp-init.sh --project <GCP_PROJECT_ID>
```

### Path B: Check Cloud Run logs

```bash
gcloud logging read resource.type=cloud_run_revision --project=<GCP_PROJECT_ID>
```

Useful signals:

- `POST /api/chat` 200 — successful request
- `AgentCompleteEvent` — generation finished
- `DocReplacer` — broken citation link auto-fixed
- `ERROR` — investigate

### Live Deployment

- **Service URL:** <https://agentic-hybrid-search-375500751528.us-central1.run.app>
- **Health:** `/api/health`
- **API docs:** `/swagger` (FastAPI Swagger UI)
- **OpenSearch:** hosted externally on GCP VM, ESCI products indexed
- **PostgreSQL:** Cloud SQL (checkpoints only)

---

## Features

### Conversational query rewriting

Resolves pronouns ("it", "those"), comparatives ("which is cheaper"), and
short attribute questions ("how much?") using conversation history before
retrieval. Skips expansion when the query already names a specific
brand/product. Emits `QueryExpansionEvent` for the observability panel.

### Context-validated refinement

"Make them waterproof" narrows the prior result set, not a fresh search.
A continuity score combines category matching and document-ID overlap:

- `> 0.7` — refine against prior products (α=0.35)
- `0.3–0.7` — ambiguous; ask the user to clarify
- `< 0.3` — pivot detected; reset prior context, treat as new search

### Quality gate with α adjustment

If the top reranker score is below 0.5 after reranking, the quality gate
adjusts α by ±0.3 (toward the opposite strategy) and retries retrieval
once. Prevents low-relevance outputs without an infinite loop.

### Link verification

Every citation URL is validated before reaching the LLM. Results cached
for 60 minutes (thread-safe); URLs timing out above 2 s are marked
invalid. Broken links are replaced with valid alternatives via
`doc_replacer.py`.

### Typeahead autocomplete

Edge-ngram prefix search over ESCI product titles and brands, with spell
correction (Levenshtein + `SequenceMatcher` ratio ≥ 0.6, confidence ≥ 0.5)
and a distance-1 fuzzy fallback for typos like `"nikey"` → `"nike"`.
Correction is skipped when the query is already a corpus token or a prefix
of the candidate, avoiding over-correction of in-progress words. The
frontend (`TypeaheadSuggestions.tsx` + `useRecentSearches.ts`) renders a
three-section dropdown (Did you mean? / Suggestions / Recent Searches),
uses ARIA combobox semantics with full keyboard navigation, and cancels
stale in-flight requests via `AbortController`.

### BM25 lexical optimizations

Beyond vanilla BM25, the lexical side of hybrid search applies:

- **Synonym expansion** (search-time)
- **Fuzzy matching** (auto-edit-distance on longer tokens)
- **Phrase boosting** (exact multi-word matches score higher)
- **Field boosting** (title/brand weighted above generic content)
- **Phonetic matching** via `double_metaphone` analyzer (requires the
  `analysis-phonetic` OpenSearch plugin)

These are surfaced in the frontend observability panel as a collapsible
"Search Optimizations" card — see
`web/src/components/ObservabilityPanel/SearchOptimizationDetails.tsx`.

### Pipeline Quality Summary

Every turn ends with a `PipelineSummaryEvent` (emitted right after
`AgentCompleteEvent`) that powers the **Pipeline Quality Summary** card
at the bottom of the observability panel.

The retriever runs hybrid search and a BM25-only baseline in parallel via
a 2-worker `ThreadPoolExecutor` (opensearch-py releases the GIL during
HTTP I/O). State now carries `pre_rerank_documents`, `bm25_documents`,
`judgments`, and per-stage latency (`bm25_latency_ms`,
`retriever_latency_ms`, `reranker_latency_ms`).

**With ESCI ground truth** — when a best-effort exact-keyword lookup
against the `esci_judgments` index hits a known query, the card renders
three rows (BM25 → Hybrid → Reranked) with **NDCG@10**, **MRR**,
**Recall@20**, **Precision@10**, plus a latency cost-benefit table that
includes a "Lift / 100ms" column. ESCI labels are mapped to numeric
relevance: `E=4.0`, `S=1.0`, `C=0.1`, `I=0.0`.

**Without ground truth** — the card falls back to a self-referential
**confidence proxy**: `top1_score`, `score_gap` (top-1 vs top-2),
`score_variance`, and `rank_changes_count` (rank churn between hybrid and
reranked). These collapse to a `confidence_label` of `high`, `medium`,
or `low`. The latency table still renders without the lift column.

Implementation:

- [`relevancy_metrics.py`](relevancy_metrics.py) — pure-Python (no NumPy)
  module with `ndcg_at_k`, `mrr`, `recall_at_k`, `precision_at_k`,
  `compute_stage_metrics`, `confidence_from_scores`,
  `count_rank_changes`, `latency_cost_benefit`. 43 unit tests in
  [`tests/unit/test_relevancy_metrics.py`](tests/unit/test_relevancy_metrics.py).
- [`vector_store.py`](vector_store.py) — `bm25_only_search()` (BM25
  baseline) and `lookup_judgments(query)` (judgments index lookup).
- [`api/services/observable_agent.py`](api/services/observable_agent.py) —
  accumulates pipeline state across the LangGraph stream
  (last-write-wins) and emits the summary in `_build_pipeline_summary()`.
  5 unit tests in
  [`tests/unit/test_pipeline_summary_event.py`](tests/unit/test_pipeline_summary_event.py).
- [`web/src/components/ObservabilityPanel/PipelineSummaryCard.tsx`][psc] —
  the rendered card.

[psc]: web/src/components/ObservabilityPanel/PipelineSummaryCard.tsx

### Admin reindex API

`GET /api/admin/reindex?reset_index=true&limit=10000` kicks off a
background ESCI re-ingestion. `GET /api/admin/reindex/status` returns
`idle` / `queued` / `running` / `success` / `error` with detail.
`GET /api/admin/health` returns index health and document count. Add
`reindex_judgments=true` when the ESCI judgment index also needs a rebuild.
A dedicated GitHub Actions
workflow (`.github/workflows/reindex.yml`) exposes the flow as a manual
dispatch against a deployed Cloud Run instance.

### Observable events

Full pipeline is instrumented with Pydantic-typed events streamed over
WebSocket:

| Event | Purpose |
| --- | --- |
| `intent_classification` | 6 intents + confidence + keyword/LLM path |
| `query_evaluation` | Assigned α, reasoning |
| `query_expansion` | Original vs rewritten query |
| `opensearch_query` | α, intent, applied filters, full DSL `body` + `index` + `params`. Tagged with `query_type` (`hybrid`, `bm25_baseline`, `quality_gate_retry`) so the UI can render an eye-icon viewer per query type. |
| `hybrid_search_start` / `hybrid_search_result` | Candidates + scores |
| `reranker_start` / `reranker_progress` / `reranker_result` | Per-doc 0.0–1.0 |
| `quality_gate` | pass / retry / α adjusted |
| `llm_response_start` / `llm_response_chunk` | Token streaming |
| `agent_complete` | Final response + citations |
| `pipeline_summary` | Per-stage NDCG/MRR/Recall/Precision (or confidence proxy) + latency cost-benefit |

Schemas in [api/schemas/events.py](api/schemas/events.py) must stay in sync
with [web/src/types/events.ts](web/src/types/events.ts).

---

## Architecture

### LangGraph Pipeline

Seven nodes wired into a graph:

```text
START → intent_classifier
  ├── search / comparison / attribute_filter /
  │   refinement / follow_up   → query_evaluator → retriever → reranker → quality_gate → agent → END
  │                                                                               │
  │                                                                               └─(retry)→ retriever
  ├── summary                  → summary → agent → END
  └── clarify (confidence<0.7) → agent (requests disambiguation) → END
```

### Hybrid Search

Reciprocal Rank Fusion combines vector and BM25 rankings:

```text
rrf_score = Σ 1 / (rank + k)      where k = 60
```

The **α parameter** controls weighting:

| α | Strategy | Best for |
| --- | --- | --- |
| 0.0–0.15 | Pure lexical | ASINs, model numbers, UPCs |
| 0.15–0.40 | Lexical-heavy | Brand + category, attributes |
| 0.40–0.60 | Balanced | Feature combinations |
| 0.60–0.75 | Semantic-heavy | "Best for X", use-case queries |
| 0.75–1.0 | Pure semantic | Gift ideas, mood/style, exploration |

The query evaluator picks α per turn. If the top reranker score is still
below 0.5, the quality gate retries with α adjusted by ±0.3.

### State

`CustomAgentState` (see [agent_state.py](agent_state.py)) is a `total=False`
TypedDict — only `messages` is guaranteed. Always use `state.get(...)`.

| Added by | Fields |
| --- | --- |
| Classifier | `intent`, `confidence`, `user_query` |
| Query Evaluator | `alpha`, `intent_description` |
| Retriever | `retrieved_documents` |
| Reranker | `reranker_max_score`, `reranked_documents`, `reranker_latency_ms` |
| Quality Gate | `quality_gate_retried`, `alpha_adjusted_value` |
| Pipeline Summary | `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms` |
| Other | `thread_id`, `current_node`, `retrieved_products`, `citations` |

---

## Development

### Re-ingest ESCI data (Lucille ETL — default)

The standard ingest path uses [Lucille](lucille-esci/) — a Java ETL framework
that reads parquet files and bulk-indexes into OpenSearch without calling the
embedding API (embeddings are precomputed in the shipped parquet).

```bash
# Re-run the full ingest (products + judgments)
bash scripts/lucille_ingest.sh

# Pre-aggregate only (skip if esci_judgments_aggregated.parquet already exists)
python scripts/prepare_judgments_parquet.py --locale us --force
```

Config lives in `lucille-esci/conf/` (HOCON). The script auto-builds the Maven
module on first run and skips the build when no source files changed.

The default 10 k sample ships precomputed at `data/esci_products_sample_10000.parquet` (read by Lucille). Lucille is the **only** supported ingest mechanism — the Python ingest scripts (`ingest_esci_products.py`, `ingest_esci_judgments.py`) were removed in PR #48.

ESCI labels are mapped to numeric relevance: `E=4.0`, `S=1.0`, `C=0.1`,
`I=0.0`. Lookups from `OpenSearchVectorStore.lookup_judgments(query)` are
best-effort exact-keyword matches; absence is non-fatal — the summary
falls back to the confidence proxy.

### Batch embedding via BigQuery

For large ingestions, `bigquery_batch_embeddings.py` offloads embedding
generation to BigQuery ML (`AI.GENERATE_EMBEDDING`) — ~15–30 min for
1.2 M products vs ~4.5 h serially. See the script's `--help` for the
one-time GCP setup and flags.

### Benchmarks

```bash
PYTHONPATH=. python benchmark_search.py
```

### Checkpoint maintenance

```bash
PYTHONPATH=. python checkpoint_maintenance.py   # garbage-collect old checkpoints
PYTHONPATH=. python checkpoint_optimizer.py     # tune checkpoint performance
```

### Testing

```bash
PYTHONPATH=. pytest tests/unit/           # no external deps, ~0.5 s
PYTHONPATH=. pytest tests/integration/    # requires Postgres + OpenSearch
PYTHONPATH=. pytest tests/e2e/            # requires deployed Cloud Run
PYTHONPATH=. pytest --cov=. --cov-report=html
```

`make ci` runs the local pre-push gate used by this repo: backend format,
lint/import checks, unit tests, and frontend test/lint/type/build. It only
collects integration and e2e tests; execute those suites separately when a
change touches service wiring, WebSocket contracts, OpenSearch mappings, or
Cloud Run behavior.

See [tests/README.md](tests/README.md) for the full layout and fixtures, and
[tests/e2e/README.md](tests/e2e/README.md) for Cloud Run smoke/regression
scenarios.

### Lint / format / types

```bash
make lint            # pylint
make format          # black
make format-fix      # black + isort (run before every commit)
make type-check      # mypy
make ci              # full local gate: black + isort + flake8 + mypy + unit tests + frontend
```

A git pre-commit hook (`.git/hooks/pre-commit`) automatically runs black,
isort, and flake8 on every staged `.py` file. If a commit is blocked, run
`make format-fix` then re-stage. The hook is local-only and not tracked by
git — reinstall it by running:

```bash
cp scripts/pre-commit.sh ../.git/hooks/pre-commit && chmod +x ../.git/hooks/pre-commit
```

### Frontend (from `web/`)

```bash
npm install
npm run dev          # vite dev server on :5173
npm run build        # tsc + vite build → dist/
npm run lint         # eslint
```

---

## Performance

| Operation | Typical |
| --- | --- |
| Hybrid search (BM25 + kNN) | ~300–800 ms |
| Cross-encoder reranking (40 → 10) | ~200 ms–1 s (CPU-bound; ~10 ms/doc × FETCH_K) |
| Query evaluation (α + expansion) | ~300–500 ms |
| Quality Gate retry | +1–2 s |
| LLM response (streaming) | ~3–8 s |
| **Total per query** | **~6–15 s** local; ~10–35 s Cloud Run (cross-encoder on cold container adds latency) |
| Link verification (cached) | ~50 ms / URL |

Optimizations: HNSW vector index · embedding cache (60-min TTL) ·
thread-safe link cache · streaming WebSocket generation · fast-path α
for comparison/attribute_filter/refinement to skip the LLM evaluator.

---

## Directory Layout

```text
langchain_agent/
├── scripts/               # Lifecycle scripts — see scripts/README.md
│   ├── setup.sh           # One-time local setup
│   ├── start.sh           # Start services
│   ├── stop.sh            # Stop services
│   ├── teardown.sh        # Full local cleanup
│   ├── logs.sh            # View backend/frontend logs
│   ├── deploy.sh          # GCP Cloud Run deploy
│   ├── gcp-init.sh        # Cloud SQL + product ingestion (one-time)
│   ├── gcp-teardown.sh    # Remove GCP resources
│   └── smoke_test.sh      # Post-deploy smoke test
├── api/                   # FastAPI backend — see api/README.md
│   ├── main.py            # FastAPI lifespan
│   ├── routes/            # chat (WebSocket), conversations, health, suggest, admin, auth
│   ├── middleware/        # Auth, CORS, session handling
│   ├── schemas/events.py  # Pydantic event models (MUST sync with web/src/types/events.ts)
│   └── services/          # Observable agent wrapper
├── web/                   # React frontend — see web/README.md
│   └── src/
│       ├── hooks/         # useWebSocket, useRecentSearches, custom hooks
│       ├── stores/        # Zustand stores (chat, observability, auth)
│       ├── components/    # React components (Chat, ObservabilityPanel, Sidebar)
│       ├── pages/         # Page components
│       ├── types/         # TypeScript types (events.ts MUST sync with api/schemas/events.py)
│       └── utils/         # Utilities
├── lucille-esci/          # Lucille ETL config — see lucille-esci/README.md
│   ├── conf/              # HOCON pipeline configs (products, judgments)
│   ├── mapping/           # OpenSearch field mappings and analyzers
│   └── pom.xml            # Maven coordinates
├── tests/                 # Test suite — see tests/README.md
│   ├── unit/              # Fast, no external services (~0.5s, 612 tests)
│   ├── integration/       # Multi-component, live services — see tests/integration/README.md
│   └── e2e/               # Deployed Cloud Run checks — see tests/e2e/README.md
├── main.py                # LangGraph agent core (~2,600 lines)
├── agent_state.py         # CustomAgentState TypedDict
├── config.py              # All configuration constants
├── exceptions.py          # Custom exception hierarchy
├── vector_store.py        # OpenSearchVectorStore + retriever (RRF)
├── reranker.py            # CrossEncoderReranker (default) + GeminiReranker (fallback)
├── embedding_cache.py     # Thread-safe query embedding cache
├── link_verifier.py       # URL validation w/ TTL cache
├── doc_replacer.py        # Broken-link replacement
├── retry_utils.py         # Tenacity decorators
├── logging_config.py      # structlog setup (JSON/console)
├── setup.py               # DB + index init; also calls lucille_ingest.sh for ESCI data
├── relevancy_metrics.py           # NDCG/MRR/Recall/Precision + confidence proxy (no NumPy)
├── bigquery_batch_embeddings.py   # Parallel embedding via BigQuery ML
├── generate_embeddings.py         # Serial embedding fallback
├── benchmark_search.py            # Latency benchmarks
├── checkpoint_maintenance.py      # Checkpoint GC
├── checkpoint_optimizer.py        # Checkpoint tuning
├── migrate_to_hnsw.py             # Index migration utility
├── Dockerfile             # Multi-stage (Node + Python)
├── cloudbuild.yaml
├── Makefile
├── requirements.txt
├── requirements-dev.txt
└── pytest.ini
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'config'`

Bare imports require `PYTHONPATH=.`:

```bash
cd langchain_agent
PYTHONPATH=. pytest tests/unit/
PYTHONPATH=. python setup.py
```

### View logs

```bash
./scripts/logs.sh backend
./scripts/logs.sh frontend
./scripts/logs.sh all
```

### Backend won't start

```bash
grep ^API_KEY .env       # must exist
./scripts/logs.sh backend

# If the port is stuck:
lsof -ti :8000 | xargs kill -9
./scripts/start.sh
```

### Frontend shows connection error

```bash
curl http://localhost:8000/api/health
./scripts/logs.sh frontend
```

### Google AI API issues

```bash
echo $GOOGLE_API_KEY
python -c "from langchain_google_genai import GoogleGenerativeAIEmbeddings; \
  e = GoogleGenerativeAIEmbeddings(model='models/gemini-embedding-001', output_dimensionality=768); \
  print(len(e.embed_query('test')))"
```

### Database issues

```bash
docker compose ps
# Restart:
cd .. && docker compose down && docker compose up -d postgres && cd langchain_agent
PYTHONPATH=. python setup.py
```

### Content stops streaming after generation completes

Backend logs should show `LLM STREAMING STARTED` followed by
`Emitting AgentCompleteEvent: N chars`. If they don't, pull latest,
`./scripts/stop.sh` and `./scripts/start.sh`.

### Verify the stack

```bash
docker compose ps                              # PostgreSQL + OpenSearch
curl http://localhost:9200/_cluster/health     # OpenSearch
curl http://localhost:8000/api/health          # Backend
```

---

## Security

- **Session-cookie auth** — `POST /api/auth/login` validates `LOGIN_PASSWORD`
  via `hmac.compare_digest` (timing-safe), sets a signed HttpOnly
  `ahs_session` cookie (SameSite=Lax). All protected routes call
  `verify_session`; WebSocket handshake uses `verify_websocket_session`
  (rejects with code 4401).
- **Admin token** — `X-Admin-Token` header accepted on `/api/admin/*` and
  `/api/health` for automation (GitHub Actions). Constant-time comparison
  via `hmac.compare_digest`. Requires `ADMIN_TOKEN` env var (32+ chars).
- **Same-origin enforcement** — `Origin` header allow-list (localhost dev
  ports + `*.run.app`). Disallowed origins always 403; host-fallback only
  when both Origin and Referer are absent.
- **Timing-attack resistant** — `hmac.compare_digest` used throughout.
- **Input validation** — thread IDs validated by regex
- **Thread safety** — all caches use `threading.Lock`
- **Rate limiting** — configurable via `slowapi`

---

## External References

- Amazon ESCI dataset: <https://github.com/amazon-science/esci-data>
- LangGraph: <https://langchain-ai.github.io/langgraph/>
- LangChain: <https://python.langchain.com/>
- OpenSearch: <https://opensearch.org/docs/latest/>
- OpenSearch Python client: <https://opensearch-project.github.io/opensearch-py/>
- Google Gemini: <https://ai.google.dev/>
- Google AI Studio: <https://aistudio.google.com/>
- Google Cloud Run: <https://cloud.google.com/run/docs>
