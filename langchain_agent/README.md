# Backend: Agentic Hybrid Search

> **Parent**: [../README.md](../README.md) · Design: [ARCHITECTURE.md](ARCHITECTURE.md) · Demo script: [DEMO.md](DEMO.md) · API: [api/README.md](api/README.md) · UI: [web/README.md](web/README.md) · Tests: [tests/README.md](tests/README.md)

A LangGraph RAG agent over 158,637 Amazon ESCI products: hybrid BM25 + vector
retrieval (RRF), a dynamic alpha per intent, cross-encoder reranking behind a
quality gate, an LLM judge, streamed pipeline events over WebSocket, and a
taxonomy the agent grows and corrects live. Everything runs locally: Docker
Compose for PostgreSQL and OpenSearch, native [Ollama](https://ollama.com/)
for every model.

## Prerequisites

- Docker Desktop
- Python 3.14 and Node.js 24 (for native dev; the demo container needs neither)
- Ollama installed and running natively (Metal GPU on macOS — never containerized).
  `make setup` pulls the models (~23 GB on first run):
  `qwen3.6:35b-a3b-q4_K_M` (every chat call) and `nomic-embed-text` (query embeddings).
- Git LFS (`git lfs install`) — the corpus ships as a precomputed export in
  `data/precomputed/`; see [../data/README.md](../data/README.md).

## Run it

All commands run from `langchain_agent/`. The Makefile has five targets:

```bash
make doctor     # check prerequisites (bare `make` does the same)
make setup      # first time: Docker services, .venv, Ollama models, load the precomputed index (~1-2 min)
make dev        # every session — see below
make ci         # the pre-push gate
make teardown   # DESTRUCTIVE: .venv, node_modules, Docker volumes, logs
```

`make dev` starts everything, side by side, sharing PostgreSQL and OpenSearch:

| | URL | What it serves |
|---|---|---|
| Dev UI | http://localhost:5173 | Vite with live reload; proxies `/api` and `/ws` to the native backend |
| Native backend | http://localhost:8080 | `uvicorn --reload`, logs in `logs/backend.log` (Swagger at `/swagger`) |
| Demo | http://localhost:8000 | One container with the backend and the built UI, rebuilt from the tree on each `make dev` |

Edits show on :5173 immediately; :8000 is frozen until the next `make dev`.
Stop everything with `./scripts/stop.sh` (containers stop, volumes and data
survive). Other direct commands — unit tests only, formatting, the full e2e
suite — are listed in the Makefile header.

`make ci` is the only gate this repo has (there is no CI service): format,
lint, types, unit tests, frontend test/lint/build, then it brings Docker up
and runs the live integration tests and one WebSocket smoke round-trip
against :8080. Run it before every push.

## How a turn works

```
intent_classifier ─┬─(summary)──► summary ─┬─(continue)──► retriever
                    ├─(clarify)──► agent    └─(done)──────► agent
                    └─(other)────► query_evaluator ──► retriever ──► reranker ──► quality_gate ─┬─(retry)───► retriever
                                                                                                  └─(continue)► agent ──► llm_judge ──► END
```

Eight LangGraph nodes (`main.py::create_agent_graph`):

1. **intent_classifier** — one structured LLM call picks `search`, `comparison`,
   `attribute_filter`, `refinement`, `follow_up`, or `summary`; confidence < 0.7
   routes to the agent for a clarifying question.
2. **query_evaluator** — estimates the hybrid alpha (0 = pure BM25, 1 = pure
   vector); comparison/attribute_filter/refinement take a fast-path alpha.
3. **retriever** — rewrites vague queries against history, extracts color /
   waterproof / category filters, runs hybrid search plus a BM25 baseline in
   parallel. Unresolved color and waterproof terms are hard filters, so an
   unknown term produces a genuine zero-result query — that is what triggers
   taxonomy growth.
4. **reranker** — local cross-encoder (`ms-marco-MiniLM-L-12-v2`), scores
   rescaled so the ceiling stays below the quality-gate thresholds.
5. **quality_gate** — if the top reranker score is under the intent's threshold
   (comparison 0.55, search/follow_up 0.50, attribute_filter/refinement 0.45),
   adjusts alpha by ±0.3, widens the candidate pool 4x, and retries once.
6. **agent** — streams the answer with citations; offers `trigger_enrichment`
   when it sees a taxonomy gap, or a correction when a shopper disputes a tag.
7. **llm_judge** — flags hallucinations against the retrieved products and
   regenerates once for `fabrication` / `cross_product_bleed`.
8. **summary** — recap turns skip retrieval.

Every turn ends with a `pipeline_summary` event: a reranker-confidence proxy,
the judge's verdict, and per-stage latency. Mechanism details, state fields, and the taxonomy
growth-and-correction loop are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Taxonomy growth and correction

Color and waterproof tags (`product_<type>_primary` / `_secondary`) were
detected once when the corpus was built and ship in the precomputed export.
The taxonomy itself lives in OpenSearch. At runtime the agent's one tool,
`trigger_enrichment(attribute_type, variant, canonical)` (gated by
`ENABLE_ENRICHMENT_TOOL`), writes a mapping and re-tags only the products
whose text mentions the changed term (`pipeline/scoped_retag.py`, seconds, no
re-embedding). `waterproof` deliberately starts with zero variants so the gap
is real on every fresh cluster. `POST /api/admin/enrich` exposes the same
mechanism without the LLM loop; `./scripts/reset_demo_taxonomy.sh` (or the
UI's Restart button) re-arms the demos.

## Configuration

`.env.example` is the authoritative list of what `core/config.py` reads from
the environment: Ollama host and models, PostgreSQL and OpenSearch connection
settings, `PORT`, the embedding cache, reranker warm-up, the quality gate
(`ENABLE_QUALITY_GATE`, `QUALITY_GATE_THRESHOLD`), the query evaluator's
temperature/tokens/timeout, logging, and `ENABLE_ENRICHMENT_TOOL`.

Retrieval tuning is **not** environment-configurable — `RETRIEVER_K`,
`RETRIEVER_FETCH_K`, `RETRIEVER_ALPHA`, `RERANKER_FETCH_K`, `RERANKER_TOP_K`,
`VECTOR_DIMENSION` and friends are Python literals in `core/config.py`; a
matching `.env` line is ignored.

`PORT` defaults to 8080. The demo container listens on 8080 too and is
published on host :8000 (`docker-compose.yml`), which is why both can run at
once.

## API

Same-origin checking is the only auth layer: `/api/health` is public; every other route (chat, WebSocket, `/api/admin/*`) requires an
allow-listed `Origin`. The full route table, WebSocket protocol, and event
list are in [api/README.md](api/README.md).

```bash
curl http://localhost:8080/api/health
curl -H 'Origin: http://localhost:8080' http://localhost:8080/api/admin/health
```

## Data

The only data in the repo is `data/precomputed/` — a one-time export of the
products index (with embeddings) and the attribute-mapping store,
bulk-loaded by `scripts/load_precomputed_indices.py`. There is
no ingest or rebuild path; see [../data/README.md](../data/README.md).

## Testing

`PYTHONPATH=.` is required for every direct `pytest`/`python` invocation
(bare imports like `from core.config import ...`).

```bash
PYTHONPATH=. .venv/bin/pytest tests/unit/      # fast, no services
make ci                                       # everything, including live integration + smoke
bash scripts/smoke_local.sh                   # the full e2e suite against :8080
```

Layout, markers, fixtures, and which test guards which invariant:
[tests/README.md](tests/README.md). Formatting is enforced by the pre-commit
hook `setup.sh` installs (black, isort, flake8 on staged `.py` files).

## Layout

```text
langchain_agent/
├── main.py                 EcommerceSearchAgent: setup, graph wiring, lifecycle
├── setup.py                DB tables, index + search pipeline, precomputed load
├── core/                   agent_state.py, config.py, exceptions.py, llm.py, logging_config.py
├── pipeline/               pipeline_nodes.py (the 8 nodes), conversation_management.py,
│                           enrichment_events.py, reindex_trigger.py, scoped_retag.py
├── retrieval/              vector_store.py (OpenSearch, RRF), reranker.py, embeddings.py,
│                           attribute_discovery.py, attribute_mapping_store.py
├── quality/                judge.py, enrichment_service.py, enrichment_value_judge.py, demo_reset.py
├── tools/enrichment_tool.py
├── observability/          confidence_proxy.py, embedding_cache.py, llm_content.py
├── checkpoints/            checkpoint_optimizer.py (Postgres checkpoint tuning)
├── api/                    FastAPI app — see api/README.md
├── web/                    React UI — see web/README.md
├── scripts/                lifecycle scripts — see scripts/README.md
├── tests/                  unit / integration / e2e — see tests/README.md
├── Dockerfile              the demo image (built UI + backend, one process)
├── Makefile                doctor · setup · dev · ci · teardown
└── .env.example            every environment variable the app reads
```

## Troubleshooting

```bash
# Is everything up?
docker compose -f ../docker-compose.yml ps        # PostgreSQL + OpenSearch (+ demo)
curl http://localhost:9200/_cluster/health
curl http://localhost:8080/api/health             # native backend
curl http://localhost:8000/api/health             # demo container
curl http://localhost:11434/api/tags              # Ollama and pulled models

# Logs
tail -f logs/backend.log logs/frontend.log logs/demo-build.log

# Port stuck (:8080 native backend, :5173 Vite). :8000 is Docker's port proxy — stop it
# with `docker compose stop app`, never kill it.
./scripts/stop.sh
lsof -ti :8080 | xargs kill -9
make dev
```

- `ModuleNotFoundError: No module named 'config'` — you forgot `PYTHONPATH=.`.
- `make ci` fails at "docker services" — Docker Desktop isn't running: `open -a Docker`.
- `make setup` says `data/precomputed/` is missing — `git lfs pull`.
- Ollama errors — `ollama pull qwen3.6:35b-a3b-q4_K_M && ollama pull nomic-embed-text`.
- Database trouble — `cd .. && docker compose down && docker compose up -d --wait`,
  then `PYTHONPATH=. python setup.py` recreates tables and reloads the index.

## References

- Amazon ESCI dataset: <https://github.com/amazon-science/esci-data>
- SQID image URLs: <https://github.com/Crossing-Minds/shopping-queries-image-dataset>
- LangGraph: <https://langchain-ai.github.io/langgraph/>
- OpenSearch: <https://opensearch.org/docs/latest/>
- Ollama: <https://ollama.com/>
