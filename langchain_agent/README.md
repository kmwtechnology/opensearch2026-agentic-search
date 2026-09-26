# Agentic Hybrid Search — E-Commerce Product Search Agent

> See also: [repo root README](../README.md) ·
> [tests/README.md](tests/README.md) ·
> [tests/e2e/README.md](tests/e2e/README.md)

A production-grade LangGraph RAG agent for e-commerce product discovery.
Uses a local Ollama LLM and embeddings, OpenSearch for hybrid vector + BM25
search, and PostgreSQL for LangGraph checkpoints. No cloud API key required.

**Capabilities:**

- **6-intent classification** — `search`, `comparison`, `attribute_filter`,
  `refinement`, `follow_up`, `summary`. Single structured-output LLM call
  (no keyword fast-path).
- **Hybrid retrieval** — vector (768-dim `nomic-embed-text` embeddings via
  Ollama) + BM25, fused via RRF (k=60), with dynamic α per intent.
- **Cross-encoder reranking** — local `ms-marco-MiniLM-L-12-v2` scores
  query-product relevance, no API call; the only reranker.
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
- **Frontend:** React 19, TypeScript, Tailwind, Zustand
- **Data layer:** OpenSearch 3.8.0 (HNSW + BM25) · PostgreSQL 16
  (LangGraph checkpoints only)
- **LLM:** local Ollama `qwen3.6:35b-a3b-q4_K_M` (generation, classify,
  eval, judge) · `nomic-embed-text` via Ollama (embeddings)

---

## Local Development

This application runs local-only (issue #110/#113) — `setup.sh` and
`start.sh` run PostgreSQL/OpenSearch locally with Docker, plus the FastAPI
backend and React frontend.

### Prerequisites

[Ollama](https://ollama.com/) installed and running locally, plus:

```bash
docker --version      # Docker Desktop
python3 --version     # Python 3.14+
node --version        # Node.js 24+
```

`scripts/setup.sh` checks that Ollama is installed/running and pulls any
missing models (~23 GB on first run); `scripts/doctor.sh` re-checks
reachability and that the configured models are pulled.

Lucille ETL ingest runs via Docker by default (`LUCILLE_USE_DOCKER=true`) —
no local Java/Maven needed. Set `LUCILLE_USE_DOCKER=false` to use the native
path instead (requires Java 21+ and Maven: `brew install openjdk@21 maven`).

### Local Development With Docker

```bash
cd langchain_agent
cp .env.example .env
./scripts/setup.sh
./scripts/start.sh
```

First-time setup, including pulling Ollama models and the full ~158K-product
ingest, takes roughly 35-40 minutes on an M4 Max:

1. Creates `.env` from `.env.example` (set `ADMIN_TOKEN` yourself if you want automation access to `/api/admin/*`)
2. Creates `.venv`, installs Python + frontend dependencies
3. Checks Ollama is installed/running and pulls any missing models
4. Starts PostgreSQL and OpenSearch via Docker
5. Initializes the checkpoint DB and OpenSearch index
6. Ingests the full ESCI product corpus (158,637 products, embedded through
   Ollama at ingest time) and judgments (65,028 queries) via [Lucille ETL](lucille-esci/)

Backend FastAPI runs on `:8000`, React frontend on `:5173` (Vite proxies
`/api` to the backend).

There is no login gate — the UI opens straight to the chat, and every
same-origin caller, including `/api/admin/*`, is unauthenticated. See
[auth-patterns.md](../docs/integration/auth-patterns.md).

Stop or clean up local services:

```bash
./scripts/stop.sh
./scripts/teardown.sh
```

Removes running services, the Docker volumes, `.venv`, `node_modules`, and
log files. Keeps `.env` by default (prompted separately).

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

`/api/health` is public. Every other endpoint is same-origin-only (see
[auth-patterns.md](../docs/integration/auth-patterns.md)).

```bash
curl -H "Origin: http://localhost:8000" http://localhost:8000/api/conversations
```

The primary surface is the WebSocket endpoint under `/api/chat` — see
`api/routes/chat.py`. REST routes cover health (`/api/health`),
conversation CRUD (`/api/conversations`), typeahead suggestions
(`/api/suggest` — see `api/routes/suggest.py`), and admin reindex
operations (`/api/admin/*` — see `api/routes/admin.py`).

#### Typeahead autocomplete — `GET /api/suggest`

```bash
curl "http://localhost:8000/api/suggest?q=nik&limit=8"
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
# Grow/correct the live color/waterproof taxonomy and trigger a scoped re-tag
curl -X POST http://localhost:8000/api/admin/enrich \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: your_admin_token_here" \
  -d '{"attribute_type": "waterproof", "variant": "weatherproof", "canonical": "waterproof"}'

# Inspect current index health + document count
curl http://localhost:8000/api/admin/health \
  -H "X-Admin-Token: your_admin_token_here"
```

There is no in-container full-ingest endpoint. A full re-ingest happens via
`scripts/lucille_ingest.sh`; `POST /api/admin/enrich` triggers a scoped
re-detection/re-tag (`REINDEX_TRIGGER=scoped`, the default) as a side effect
of adding/correcting one taxonomy mapping — only products whose text
mentions the changed variant are re-checked and updated, no re-embedding.
Verify the result via `GET /api/admin/health`.

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

Everything lives in `core/config.py`; most (but not all) values are `.env`-overridable — see `.env.example` for the current, authoritative list of what's genuinely read from the environment vs. hardcoded.

### Models

```bash
LLM_MODEL=qwen3.6:35b-a3b-q4_K_M   # generation, classify, judge (default for all chat calls)
QUERY_EVAL_MODEL=qwen3.6:35b-a3b-q4_K_M   # query evaluator (defaults to LLM_MODEL)
JUDGE_MODEL=qwen3.6:35b-a3b-q4_K_M        # LLM judge (defaults to LLM_MODEL)
EMBEDDINGS_MODEL=nomic-embed-text  # 768-dim embeddings
OLLAMA_HOST=http://localhost:11434
OLLAMA_KEEP_ALIVE=60m
OLLAMA_NUM_CTX=32768
LLM_TEMPERATURE=0
QUERY_EVAL_TEMPERATURE=0
QUERY_EVAL_MAX_TOKENS=1024
```

Every chat call goes through `core/llm.py::build_chat_model` (`ChatOllama`,
`reasoning=False`).

`VECTOR_DIMENSION` (768) is **not** on this list — it's a hardcoded literal in `core/config.py`, not an env override, despite living right next to `EMBEDDINGS_MODEL` in the source.

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

**None of these are `.env`-settable** — they're plain Python literals in `core/config.py`. Values shown are the actual current defaults; edit `core/config.py` and redeploy to change them.

```python
RETRIEVER_K = 10              # Final docs
RETRIEVER_FETCH_K = 40        # Candidates before reranking
RETRIEVER_ALPHA = 0.25        # Default α (evaluator usually overrides)
ENABLE_RERANKING = True
RERANKER_FETCH_K = 40         # Candidates reranked
RERANKER_TOP_K = 10           # Final top-K
ENABLE_QUERY_EVALUATION = True
```

`ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS` (default 5) **is** `.env`-settable — it bounds the query evaluator's alpha-estimation call and the retriever's attribute-extraction/query-expansion calls (same underlying model), replacing the formerly-dead `QUERY_EVAL_TIMEOUT_MS`.

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

If the top reranker score is below the intent-specific threshold
(comparison=0.55, search/follow_up=0.50, attribute_filter/refinement=0.45)
after reranking, the quality gate adjusts α by ±0.3 (toward the opposite
strategy) and retries retrieval once. Prevents low-relevance outputs
without an infinite loop.

### Link verification

Every citation URL is validated before reaching the LLM. Results cached
for 60 minutes (thread-safe); URLs timing out above 2 s are marked
invalid. Broken links are replaced with valid alternatives via
`retrieval/doc_replacer.py`.

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

- [`observability/relevancy_metrics.py`](observability/relevancy_metrics.py) — pure-Python (no NumPy)
  module with `ndcg_at_k`, `mrr`, `recall_at_k`, `precision_at_k`,
  `compute_stage_metrics`, `confidence_from_scores`,
  `count_rank_changes`, `latency_cost_benefit`. 43 unit tests in
  [`tests/unit/test_relevancy_metrics.py`](tests/unit/test_relevancy_metrics.py).
- [`retrieval/vector_store.py`](retrieval/vector_store.py) — `bm25_only_search()` (BM25
  baseline) and `lookup_judgments(query)` (judgments index lookup).
- [`api/services/observable_agent.py`](api/services/observable_agent.py) —
  accumulates pipeline state across the LangGraph stream
  (last-write-wins) and emits the summary in `_build_pipeline_summary()`.
  5 unit tests in
  [`tests/unit/test_pipeline_summary_event.py`](tests/unit/test_pipeline_summary_event.py).
- [`web/src/components/ObservabilityPanel/PipelineSummaryCard.tsx`][psc] —
  the rendered card.

[psc]: web/src/components/ObservabilityPanel/PipelineSummaryCard.tsx

### Admin API

`GET /api/admin/health` returns index health and document count.
`GET /api/admin/diagnose` probes field-level hit counts and mapping
presence per field. `POST /api/admin/enrich` grows or corrects the
color/waterproof taxonomy and, by default, triggers a scoped re-detection
of only the affected products (well under a second to a few seconds,
measured live) — see "Agentic Taxonomy Growth & Correction" below and
`docs/integration/rest-api.md` for the request/response shape. All three
rely on same-origin checking only (no login gate); `X-Admin-Token` support
exists in `api/middleware/admin_auth.py` but isn't wired into these routes.

Routine full re-ingestion (not tied to a specific taxonomy change) is done
via `bash scripts/lucille_ingest.sh` rather than an HTTP endpoint — it
reindexes both products and judgments by default; pass `--skip-judgments`
to reindex products only.

### Agentic Taxonomy Growth & Correction

The agent can grow *or fix* its own catalog taxonomy live via one shared
tool, `trigger_enrichment(attribute_type, variant, canonical)`, gated by
`ENABLE_ENRICHMENT_TOOL` (default off). Calling it writes the mapping to
OpenSearch and, by default (`REINDEX_TRIGGER=scoped`), re-detects the
attribute only on the products whose text mentions the changed variant and
bulk-updates just those (`pipeline/scoped_retag.py`) — no re-embedding, no
full reindex. `REINDEX_TRIGGER=local` remains available for a genuine full
Lucille reindex but takes 30+ minutes.

**Gap** (a term the taxonomy has never seen): when `attribute_filter`
intent extracts a color or waterproof term the taxonomy doesn't recognize
and the resulting search genuinely fails, `agent_node` offers the tool.
Both color's and waterproof's unresolved-term filter is a hard exact
match (excluded from the retriever's filter-relaxation safety net, which
only ever drops `multi_match` clauses), so either one reliably produces a
genuine zero-result query through live chat. `WATERPROOF_CANONICALS`
ships with zero seed variants on purpose (`retrieval/attribute_discovery.py`)
so this gap is real and reproducible on a fresh cluster, not something
that merely happens to be missing — the generic `feature` field (anything
that isn't a color or a waterproofing requirement, e.g. "breathable",
"insulated") is the one that stays a deliberately soft lexical match, and
*that* is subject to relaxation.

**Correction** (a term already mapped to the *wrong* bucket — the live
demo's centerpiece, see `DEMO.md`): a separate detection branch in
`agent_node` watches `refinement`/`follow_up` turns for dispute language
("that's wrong", "mistagged", ...) via `_detect_correction_signal`, and
if the shopper is disputing a real, verifiable mistake, offers the same
tool framed as a correction. `enrichment_service.enrich_attribute`
distinguishes this from a no-op by comparing the requested canonical
against what's already stored — a genuine mismatch is tracked via
`EnrichmentResult.corrected_from` and reported distinctly ("Corrected
'tan' from 'yellow' to 'brown'", not "Added"). This case matters because
it produces a **passing** quality-gate score (the wrong result is still
relevant, just mis-colored) — invisible to any automated check, only
catchable by a shopper actually looking at the product.

See `ARCHITECTURE.md`'s "Attribute Detection" / "Taxonomy Growth &
Correction" sections for the full mechanism and `DEMO.md` for the live
walkthrough.

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
| `enrichment_triggered` | Agent called `trigger_enrichment`; carries `attribute_type`/`variant`/`canonical` |
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

`CustomAgentState` (see [core/agent_state.py](core/agent_state.py)) is a `total=False`
TypedDict — only `messages` is guaranteed. Always use `state.get(...)`.

| Added by | Fields |
| --- | --- |
| Classifier | `intent`, `confidence`, `user_query` |
| Query Evaluator | `alpha`, `intent_description` |
| Retriever | `retrieved_documents` |
| Reranker | `reranker_max_score`, `reranked_documents`, `reranker_latency_ms` |
| Quality Gate | `quality_gate_retried`, `alpha_adjusted_value` |
| Pipeline Summary | `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms` |
| Agent (enrichment) | `enrichment_triggered`, `enrichment_attribute_type`, `enrichment_variant`, `enrichment_canonical` |
| Other | `thread_id`, `current_node`, `retrieved_products`, `citations` |

---

## Development

### Re-ingest ESCI data (Lucille ETL — default)

The standard ingest path uses [Lucille](lucille-esci/) — a Java ETL framework
that reads parquet files, embeds each document through Ollama's
`nomic-embed-text` at ingest time (`OllamaEmbedStage`), and bulk-indexes into
OpenSearch.

```bash
# Re-run the full ingest (products + judgments)
bash scripts/lucille_ingest.sh

# Pre-aggregate only (skip if esci_judgments_aggregated.parquet already exists)
python scripts/prepare_judgments_parquet.py --locale us --force
```

Config lives in `lucille-esci/conf/` (HOCON). The script auto-builds the Maven
module on first run and skips the build when no source files changed.

The full corpus ships at `data/esci_products.parquet` (158,637 products,
text only — no precomputed vectors; read by Lucille). Lucille is the
**only** supported ingest mechanism — the Python ingest scripts
(`ingest_esci_products.py`, `ingest_esci_judgments.py`) were removed in PR
#48.

ESCI labels are mapped to numeric relevance: `E=4.0`, `S=1.0`, `C=0.1`,
`I=0.0`. Lookups from `OpenSearchVectorStore.lookup_judgments(query)` are
best-effort exact-keyword matches; absence is non-fatal — the summary
falls back to the confidence proxy.

### Benchmarks

```bash
PYTHONPATH=. python benchmarks/benchmark_search.py
```

### Checkpoint maintenance

```bash
PYTHONPATH=. python checkpoints/checkpoint_maintenance.py   # garbage-collect old checkpoints
PYTHONPATH=. python checkpoints/checkpoint_optimizer.py     # tune checkpoint performance
```

### Testing

```bash
PYTHONPATH=. pytest tests/unit/           # no external deps, ~0.5 s
PYTHONPATH=. pytest tests/integration/    # requires Postgres + OpenSearch
PYTHONPATH=. pytest tests/e2e/            # requires a running local backend (see tests/e2e/README.md)
PYTHONPATH=. pytest --cov=. --cov-report=html
```

`make check` is the local pre-push gate used by this repo: `make ci` (backend
format, lint/import checks, unit tests, frontend test/lint/type/build) plus
`make smoke` (a real round-trip against a running backend). `ci` alone
only collects integration and e2e tests; execute those suites separately
when a change touches service wiring, WebSocket contracts, or OpenSearch
mappings.

See [tests/README.md](tests/README.md) for the full layout and fixtures, and
[tests/e2e/README.md](tests/e2e/README.md) for the local smoke/regression
scenarios.

### Lint / format / types

```bash
make lint            # flake8 + mypy
make format-fix      # black + isort (run before every commit)
make ci              # fast local gate: black/isort check + flake8 + mypy + unit tests + frontend
make check           # ci + smoke — run this before every push
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
| **Total per query** | **~6–21 s** (measured across the 4 scripted demos on the local-Ollama stack, M4 Max) (first request after startup is slower: cross-encoder model load) |
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
│   └── logs.sh            # View backend/frontend logs
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
│   └── e2e/               # Local backend checks by default — see tests/e2e/README.md
│
│  # --- Entry points (stay at root: invoked by path from shell scripts/CI) ---
├── main.py                # EcommerceSearchAgent: setup, graph wiring, routers, lifecycle (~600 lines)
├── cli.py                 # Interactive terminal REPL (dev only; `make run`)
├── setup.py               # DB + index init; also calls lucille_ingest.sh for ESCI data
├── config_generator.py    # Regenerates lucille-esci/conf/products.generated.conf from OpenSearch
│
│  # --- Packages ---
├── core/
│   ├── agent_state.py     # CustomAgentState TypedDict
│   ├── config.py          # All configuration constants
│   ├── exceptions.py      # Custom exception hierarchy
│   └── logging_config.py  # structlog setup (JSON/console)
├── pipeline/
│   ├── pipeline_nodes.py  # PipelineNodesMixin: the 8 LangGraph nodes + helpers (~3,000 lines)
│   ├── conversation_management.py  # ConversationManagementMixin: threads, titles, summarize/compact
│   └── reindex_trigger.py # local Lucille subprocess trigger
├── retrieval/
│   ├── vector_store.py    # OpenSearchVectorStore + retriever (RRF)
│   ├── reranker.py        # CrossEncoderReranker (only reranker)
│   ├── attribute_discovery.py      # Attribute/taxonomy discovery
│   ├── attribute_mapping_store.py  # OpenSearch-backed taxonomy store
│   ├── link_verifier.py   # URL validation w/ TTL cache
│   └── doc_replacer.py    # Broken-link replacement
├── quality/
│   ├── judge.py           # LLM Judge (hallucination detection)
│   ├── enrichment_service.py       # enrich_attribute + reindex orchestration
│   └── enrichment_value_judge.py   # Value gate on proposed taxonomy edits
├── observability/
│   ├── relevancy_metrics.py  # NDCG/MRR/Recall/Precision + confidence proxy (no NumPy)
│   ├── embedding_cache.py    # Thread-safe query embedding cache
│   └── llm_content.py        # _flatten_llm_content (LLM content-block normalization)
├── checkpoints/
│   ├── checkpoint_maintenance.py  # Checkpoint GC
│   └── checkpoint_optimizer.py    # Checkpoint tuning
├── benchmarks/
│   ├── benchmark_esci.py     # ESCI relevancy benchmark (`make benchmark-esci`)
│   └── benchmark_search.py   # Latency benchmarks
├── Dockerfile             # Multi-stage (Node + Python)
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
curl http://localhost:11434/api/tags  # Ollama must be reachable
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

### Ollama issues

```bash
curl http://localhost:11434/api/tags   # confirm Ollama is running and models are pulled
ollama pull qwen3.6:35b-a3b-q4_K_M
ollama pull nomic-embed-text
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

- **Same-origin enforcement** — `Origin` header allow-list (localhost dev
  ports + `*.run.app`). Disallowed origins always 403; host-fallback only
  when both Origin and Referer are absent. This is the only auth layer —
  there is no login gate.
- **Admin token utility** — `api/middleware/admin_auth.py:verify_admin_token`
  (constant-time comparison via `hmac.compare_digest`, `ADMIN_TOKEN` env var,
  32+ chars) is preserved for unattended automation but isn't wired into any
  route today; same-origin already covers `/api/admin/*` for this demo box.
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
- Ollama: <https://ollama.com/>
