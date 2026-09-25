# Plan: fully local models (Ollama) + full SQID image corpus

Status: **paused 2026-09-25**, on branch `feat/issue-147-local-ollama-sqid-corpus` (not pushed).
Steps 0–3 are done and committed (820e2fb, 6b2330e, dbf5689, 35d5109). **Resume at "Resume here" below.** Tracks issue #147 plus a
new scope expansion (the Ollama swap) that has no issue yet.

## Goal

1. **Every product has a real image** (#147): replace the hand-curated demo-image
   workaround with SQID `image_url`s ingested onto every product.
2. **Full judged corpus** (#147, scope update): ingest all judged products from
   the ESCI US `test` + `small_version` queries instead of a random 10K sample.
3. **Everything runs locally on Ollama** (new): replace Gemini for both the LLM
   and embeddings. **Lucille does the chunking/parsing/embedding** at ingest, so
   no pre-embedded parquet is committed any more.

## Measured facts (2026-09-25)

| Fact | Value |
|---|---|
| Raw ESCI products | 1,814,924 (US 1,215,854) |
| US test/small queries | 8,956, ~20.3 judgments each |
| Distinct judged products in them | 164,902 |
| …after `MIN_TEXT_LENGTH >= 50` filter | **158,637** |
| …with a real SQID image URL | **151,563 (95.5%)** |
| Today's random sample | 9,618 products, 15.5% with SQID image, 1.09 judged products/query |
| Demo preconditions in new corpus | tan color 274 · "boot" titles 1,475 · waterproof text 7,488 · "running shoe" 663 · "sewing machine" titles 45 |
| Product text length | mean 1,201 chars, p99 3,838, max 4,692 (fits one embedding; no chunking needed) |
| Machine | Apple M4 Max, 64 GB; Ollama 0.34.4 native (Metal) |
| Local models installed | `qwen3.6:35b-a3b-q4_K_M` (23 GB), `qwen3.5:9b` (6.6 GB), `nomic-embed-text` (274 MB, **768-dim** — matches the current index) |
| nomic-embed-text throughput | batch-64: 97 docs/s · single-doc 1 thread: 74/s · 4–8 threads: **101/s** (GPU-bound) |
| Full-corpus embed time | **~26 min** for 158,637 products |
| Chat latency (warm, structured JSON) | 0.3–0.4 s; cold load 7–18 s; 65 tok/s (9b), 80 tok/s (35b-a3b) |
| Intent smoke test | "show me waterproof boots under $100": 9b → `search` 0.95 ✓, 35b-a3b → `comparison` 0.85 ✗ (bare prompt, not the real system prompt) |

## Lucille capabilities (checked in `~/github/kmwtechnology/lucille`, 0.13.0-SNAPSHOT)

- `ChunkText`: exists (fixed/paragraph/sentence/custom, attaches child docs).
- `OpenAIEmbed`: OpenAI models only, no base-URL option, so it can't point at Ollama.
- `PromptOllama`: chat only, using `ollama4j`, which is already a lucille-core dependency.
- **No Ollama embedding stage exists.** Write `OllamaEmbed` in
  `langchain_agent/lucille-esci/src/main/java/com/kmwllc/esci/` next to
  `AttributeDetectorStage`.

## Work already done (uncommitted)

- `langchain_agent/scripts/build_product_sample.py`: query-first selector
  (whole queries, seeded shuffle, `--max-products` cap), SQID join
  (placeholder `Default_Background_Art` → null), demo-precondition report,
  `--dry-run`. **Its Gemini embedding half (`embed_all`, shards, cache) must be
  removed**, because embedding moves into Lucille. Output becomes text + `product_image_url`.
- Inputs staged locally under gitignored `<repo>/esci/`:
  `shopping_queries_dataset/shopping_queries_dataset_products.parquet` (1.1 GB,
  unchanged from the existing clone) and `sqid/product_image_urls.csv`,
  `sqid/supp_product_image_urls.csv`.
- A Gemini embedding run was started and killed. Its partial cache was deleted, so nothing needs cleanup.

## Decisions: confirmed on resume

1. **Chat model:** `qwen3.6:35b-a3b-q4_K_M` for **every** call (generation,
   intent, evaluator/alpha, judge, value judge). The planned 9b/35b split was dropped
   after the Step 0 smoke test: the MoE 35b-a3b (~3B active) was *faster* than
   the 9b on every call, with the same accuracy. `LLM_MODEL` / `QUERY_EVAL_MODEL` /
   `JUDGE_MODEL` stay separate env vars, so a split can come back later. Set `keep_alive`.
2. **Gemini:** removed entirely. No `GOOGLE_API_KEY`, no `langchain-google-genai`,
   and no Gemini reranker (the local cross-encoder is the only reranker).
3. **Embeddings:** `nomic-embed-text`, 768-dim, so the mapping doesn't change. Prefixes:
   `search_document: ` at ingest, `search_query: ` at query time.
4. **Chunking:** none. One document per product.
5. **Live taxonomy demos:** scoped `_update_by_query` re-tag. The full Lucille run stays
   for setup and an explicit full mode.
6. **Git:** work on branch `feat/issue-147-local-ollama-sqid-corpus` and open a PR.
   The user asked for this for this session instead of cowboy direct-to-main.

### Step 0 smoke test (2026-09-25, real `_build_intent_prompt` + real Pydantic schemas)

`ChatOllama(reasoning=False, temperature=0)` + `with_structured_output` (langchain-ollama 1.1.0):

| | qwen3.5:9b | qwen3.6:35b-a3b |
|---|---|---|
| Intent, 8 demo turns (vs DEMO.md) | 8/8 | 8/8 |
| Intent latency (warm) | ~2.5 s | ~1.5 s |
| `AlphaEstimation` | valid | valid |
| `JudgmentResult` (caught planted "carbon plate") | yes, 4.1 s | yes, 2.6 s |
| `bind_tools(trigger_enrichment)`: "waterproof boots" gap | called correctly, 3.3 s | called correctly, 1.9 s |
| `bind_tools`: typo "shwo me bots" | no call | no call |

Note: `DEMO.md` records demo 1 turn 1 ("Show me blue running shoes") as
`attribute_filter` / alpha 0.25, and both local models match that.

## Work order

### Step 0: before coding
- [x] Confirm the decisions above.
- [x] Smoke-test `ChatOllama.with_structured_output` against the **actual**
      Pydantic schemas in `pipeline/pipeline_nodes.py` (intent, query evaluator,
      alpha, judge), and `bind_tools` with `trigger_enrichment`, on both Qwen
      models with the real system prompts. Check `think`/reasoning handling.
- [ ] Open the Ollama issue and edit #147.

### Step 1: ingest-time embedding in Lucille
- [ ] `OllamaEmbed` stage: Spec `source`, `dest`, `modelName`, `hostURL`,
      `prefix` (`search_document: `), optional `timeout`. Use ollama4j or plain
      HTTP to `/api/embed`; check that the pinned ollama4j version supports
      `/api/embed`. **Hard-fail** on connection errors (per the CLAUDE.md
      custom-stage rule). Add unit tests in the style of `AttributeDetectorStageTest`.
- [ ] Lucille runs in Docker and Ollama stays on the host: pass
      `OLLAMA_HOST=http://host.docker.internal:11434` through
      `lucille_ingest.sh`, as was done for the OTEL vars.
- [ ] `config_generator.py` / products conf: after `buildChunkText`, add the
      embed stage → `embedding`. Set `worker.threads` to about 4 (throughput is flat above 4).
- [ ] Sampler: remove the embedding code and write the text-only parquet
      `data/esci_products.parquet` (LFS). Delete `data/esci_products_sample_10000.parquet`
      and `scripts/bigquery_batch_embeddings.py`. Update `lucille_ingest.sh` paths.
- [ ] OpenSearch heap: `docker-compose.yml` `-Xmx512m` → 2–4g.
- [ ] Fresh cluster plus full ingest, once (about 30 min). **Confirm before `make teardown`.**

### Step 2: query side
- [ ] `main.py`: `GoogleGenerativeAIEmbeddings` → `langchain_ollama.OllamaEmbeddings`,
      wrapped so `embed_query` prepends `search_query: `.
- [ ] `ChatGoogleGenerativeAI` → `ChatOllama` everywhere (generation, intent,
      evaluator/alpha, LLM judge, optional LLM reranker).
- [ ] `core/config.py`, `.env.example`: add `OLLAMA_HOST`, `LLM_MODEL`,
      `LLM_SMALL_MODEL`, `EMBEDDINGS_MODEL=nomic-embed-text`, `OLLAMA_KEEP_ALIVE`; drop
      `GOOGLE_API_KEY`. Update `requirements.txt`, `setup.py`, `scripts/doctor.sh`
      (Ollama reachable + models pulled), `setup.sh` (`ollama pull`).
- [ ] Oodle/OTel: confirm the Traceloop LangChain instrumentor still records
      `ChatOllama` spans. Update the `gen_ai.request.model` filter examples in CLAUDE.md.
- [ ] Re-tune prompts where the local models misroute. Re-check the confidence ≥ 0.7
      clarify gate and the per-intent quality-gate thresholds (fit on Gemini).

### Step 3: scoped live reindex (#147 §6)
- [ ] `pipeline/reindex_trigger.py`: add a scoped mode that re-tags only products matching the
      changed `(attribute_type, variant)` via `_update_by_query`, with results
      identical to `AttributeDetectorStage`. Make it the default for `trigger_enrichment`.
- [ ] Add a parity test: scoped re-tag and full Lucille run must produce the same `product_<type>_*` fields.
- [ ] Update the copy that says "rebuilding all 9,618 products … ~20 seconds"
      (`EnrichmentMoment.tsx`, `GuidePage.tsx`, `DEMO.md`, `ARCHITECTURE.md`,
      `quality/demo_reset.py`, `narrate.test.ts`, `LLMAgentDetails.test.tsx`).

### Step 4: images end to end (#147 §2–3)
- [ ] Mapping: add `image_url` keyword (`index: false`) to `lucille-esci/mapping/opensearch_mapping.json`
      and the Python mapping in `retrieval/vector_store.py` (~line 150). Lucille passes
      parquet columns through without a whitelist, so only the rename or copy is needed.
- [ ] `vector_store._hit_to_document`: add `image_url` to metadata.
- [ ] Every `agent_node` citation gets `image_url`. Update the `Citation` model in
      `api/routes/chat.py` and `web/src/types`. `api/schemas/events.py` needs no change.
- [ ] Delete `scripts/fetch_product_images.py`, `demo_product_asins.json`,
      `demo_product_image_substitutes.json`, and `web/src/assets/products/`.
      `ChatPanel/productIndex.ts` → `citation.image_url`. On `<img onError>`, fall back to a plain
      bullet, and set `referrerPolicy="no-referrer"`. Verify Amazon hotlinking works on :5173 and :8000.

### Step 5: demos, benchmarks, docs
- [ ] Re-validate all 4 demos (`web/src/demos/registry.ts`; keep query strings
      exact and mirror them into `DEMO.md`, `DEMO_QUERIES.md`, `demo_queries.txt`). Choose a
      ground-truth query with ~20+ judgments and drop the "don't oversell" note.
- [ ] Benchmarks: run all ~8,956 queries or a fixed subset, then replace `BENCHMARK_RESULTS.md`.
- [ ] Docs: CLAUDE.md (tech stack, images section, commands), READMEs,
      ARCHITECTURE.md, `data/README.md`, and the manual. Rewrite (don't append) the memory files
      `project_demo_product_images.md` and `project_oodle_llm_observability.md`.
- [ ] `make check` green, then push to `main`.

## Risks

- **Intent/routing quality on local models:** the four demos depend on specific
  intents and confidence ≥ 0.7. Budget time for prompt tuning.
- **Setup time:** first-time setup gains about 30 min of embedding.
- **Hotlinked Amazon images:** URLs can die, and offline demos won't show images.
  Could add a generated (not curated) local cache later.
- **Memory:** two Qwen models (~30 GB) + OpenSearch (2–4 GB heap) + Postgres + the
  cross-encoder on 64 GB works, but check this under demo load.


## Resume here (paused 2026-09-25)

**Done and committed on the branch:** Step 0 (decisions + smoke test), Step 1 (Lucille
`OllamaEmbedStage`, text-only `data/esci_products.parquet`, 158,637 products),
Step 2 (all LLM calls go through `core/llm.py` ChatOllama, query embeddings through
`retrieval/embeddings.py`, Gemini removed), and Step 3 (scoped re-tag is the default
`REINDEX_TRIGGER`; `scripts/check_retag_parity.py` passes on the smoke index).
Unit tests: 861 pass. Frontend: 311 pass.

**Local state, not in git:**
- The full ingest into index **`agentic_hybrid_search_docs_v2`** was left running in the
  background, at ~92K of 158K products at 18:02, ~60 docs/s. Log:
  `$TMPDIR/.../scratchpad/full_ingest.log` (session scratchpad). Check the doc count with
  `curl -s localhost:9200/agentic_hybrid_search_docs_v2/_count`. If it died, re-run:
  `OPENSEARCH_INDEX_NAME=agentic_hybrid_search_docs_v2 bash scripts/lucille_ingest.sh --reset-index --skip-judgments`
  (from `langchain_agent/`).
- **v2 was created before `chunk_text.words` existed.** Once the ingest finishes, add
  the subfield in place (no re-embed): close the index, add `ascii_word_tokenizer` +
  `ascii_words_analyzer` to its settings, reopen, `put_mapping` chunk_text from
  `vector_store.INDEX_MAPPING`, then `_update_by_query` over all docs. The session
  used a one-off script for this, `add_words_subfield.py`, in the scratchpad; it's
  about 20 lines and easy to recreate. Then run
  `OPENSEARCH_INDEX_NAME=agentic_hybrid_search_docs_v2 PYTHONPATH=. python scripts/check_retag_parity.py`,
  which must PASS. A fresh `make setup` doesn't need any of this, because `setup.py`
  creates the index with the subfield.
- The old demo index `agentic_hybrid_search_docs` (9,618 products, Gemini vectors) is
  untouched. Its query-side embeddings no longer match (nomic vs Gemini), so the app
  must point at v2: set `OPENSEARCH_INDEX_NAME` in `.env`, or re-ingest into the default name.
- Local `.env` model lines were switched to Ollama. The pre-change backup is in the
  session scratchpad as `env.backup-pre-ollama`. `GOOGLE_API_KEY` and `RERANKER_MODEL`
  lines are still in `.env`; both are harmless and unused.
- OpenSearch now runs with a 2g heap (the container was recreated).
- `data/esci_products_smoke.parquet` (1,921 products) and the `ollama_smoke_docs`
  index are throwaway smoke artifacts. Delete both when done.
- Judgments were **not** re-ingested for the new corpus (`--skip-judgments`). Do that
  at cutover, and re-seed the color taxonomy on the new corpus (`--seed-taxonomy`),
  both of which rewrite shared indexes.

**Remaining:** Step 4 (images: `product_image_url` into the mapping, metadata and
citations, and remove the old image workaround), Step 5 (re-validate all 4 demos
live, benchmarks, docs), then `make check`, push, and open a PR. The user asked
for a branch and PR this session, not a direct push to main.
