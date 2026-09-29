# Architecture

How the agent works end to end: the LangGraph pipeline, its state, the events
it streams, the OpenSearch index, and the taxonomy growth-and-correction
mechanism. For running it see [README.md](README.md); for the API contract see
[api/README.md](api/README.md).

## System overview

```text
Browser (React 19)  <-- WebSocket /ws/chat -->  FastAPI (api/)
                                                     |
                                          LangGraph StateGraph (main.py::create_agent_graph)
                                                     |
   intent_classifier -+-(summary)-> summary -+-(continue)-> retriever
                      +-(clarify)-> agent    +-(done)-----> agent
                      +-(other)---> query_evaluator -> retriever -> reranker -> quality_gate -+-(retry)--> retriever
                                                                                             +-(pass)---> agent -> llm_judge -> END
                                                     |
                        OpenSearch (HNSW vectors + BM25)      PostgreSQL (LangGraph checkpoints)
                                                     |
                        Native Ollama: qwen3.6:35b-a3b-q4_K_M (every LLM call), nomic-embed-text (query embeddings)
```

Every node lives in `pipeline/pipeline_nodes.py` (`PipelineNodesMixin`);
conversation helpers in `pipeline/conversation_management.py`;
`main.py::EcommerceSearchAgent` composes them and wires the graph. The API
drives the graph with `astream_events()`; each node emits typed events that
the frontend renders live.

## Pipeline nodes

### 1. Intent classifier

One structured-output LLM call classifies the latest message into `search`,
`comparison`, `attribute_filter`, `refinement`, `follow_up`, or `summary`.
There is no keyword fast path; every turn pays this round-trip. Confidence
below 0.7 routes to `agent` with `clarifying_questions` instead of retrieving.
A `refinement` with no continuity to the prior turn is downgraded to `search`.
This node also resets `hallucination_retry_used` to `False` — without that,
the Postgres checkpoint would carry a previous turn's flag forward and disable
the judge's retry for the rest of the conversation.

Writes: `intent`, `intent_confidence`, `reasoning`, `user_query`,
`clarifying_questions`. Emits `IntentClassificationEvent`.

### 2. Query evaluator

Sets `alpha`, the weight of the vector side of hybrid search (0 = pure BM25,
1 = pure vector).

| Intent | alpha | Path |
| --- | --- | --- |
| `comparison` | 0.60 | fast path |
| `attribute_filter` | 0.25 | fast path |
| `refinement` | 0.35 | fast path |
| `search`, `follow_up` | LLM-assigned | one LLM call, bounded by `ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS`, falls back to a default on timeout |

Guide the LLM is given: 0.0–0.15 exact IDs and model numbers; 0.15–0.40
brand + category and concrete attributes; 0.40–0.60 feature combinations;
0.60–0.75 conceptual needs; 0.75–1.0 mood, style, open-ended exploration.

Writes: `alpha`, `query_analysis`. Emits `QueryEvaluationEvent`.

### 3. Retriever

1. **Query rewriting** (`_expand_vague_query`) — resolves pronouns,
   comparatives, and elliptical follow-ups against the conversation ("what
   about trail running?" becomes "Show me blue trail running shoes in size
   10"). Skipped when the query names a specific brand or product. Emits
   `QueryExpansionEvent`.
2. **Attribute extraction** (`_extract_attributes`, one structured LLM call)
   — brand, color, waterproof, a generic feature term, and size. Color and
   waterproof terms are resolved against the taxonomy in OpenSearch
   (`AttributeMappingStore`) and applied as **hard** `term` filters on
   `product_color_primary` / `product_waterproof_primary`; an unresolved
   color/waterproof term is still a hard filter on the raw text, which is what
   makes a genuinely unknown term return zero documents (the enrichment
   trigger, below). Brand filters `product_brand_normalized`. The feature term
   is a **soft** `multi_match`. A boolean the model emits for `waterproof`
   (`false` instead of `null`) is rejected by `_coerce`, otherwise it becomes a
   truthy filter that matches nothing.
3. **Refinement context** — for `refinement`, the search is pinned to the
   prior turn's documents (`prior_search_documents`) when category and
   document overlap say the user is narrowing rather than pivoting.
4. **Hybrid search** (`retrieval/vector_store.py`) — the query is embedded
   with `nomic-embed-text` (prefix `search_query:`; the corpus was embedded
   with `search_document:`), then vector and BM25 run in parallel and are
   fused with RRF, `score = sum 1/(rank + 60)`. `RETRIEVER_FETCH_K` candidates, collapsed to one hit per product.
5. **Filter relaxation** — if fewer than 3 documents survive all filters, the
   soft `multi_match` filters are dropped and the search retried; hard
   color/waterproof/brand filters are never relaxed, because the user named
   them. This is why an unknown color or waterproof term reliably produces an
   empty result instead of a vaguely related one.

Writes: `retrieved_documents`, `pre_rerank_documents`, latency. Emits
`HybridSearchStartEvent`, `OpenSearchQueryEvent` (the exact DSL, embeddings
scrubbed; `query_type` is `hybrid` or `quality_gate_retry`),
`HybridSearchResultEvent`, `SearchProgressEvent`.

BM25 fields and their boosts, fuzziness, and the title phrase field live in
`_build_multi_match`; the primary
text fields use `light_english_analyzer` (kstem) for precision, with
`.heavy` subfields (snowball) at a low boost for morphological recall.

### 4. Reranker

`retrieval/reranker.py::CrossEncoderReranker` — the local
`cross-encoder/ms-marco-MiniLM-L-12-v2` (baked into the Docker image) scores
`RERANKER_FETCH_K` candidates in one `predict()` call, sigmoid-normalized to
0–1, keeps `RERANKER_TOP_K`. It is the only reranker. Scores are rescaled so
that a uniformly irrelevant batch tops out at `RESCALE_CEILING = 0.3`, which
is deliberately below every quality-gate threshold: a batch of junk must not
pass the gate.

Writes: `reranker_max_score`, `all_reranked_documents`. Emits
`RerankerStartEvent`, `RerankerProgressEvent`, `RerankerResultEvent`.

### 5. Quality gate

Compares `reranker_max_score` against the intent's threshold — `comparison`
0.55, `search` / `follow_up` 0.50, `attribute_filter` / `refinement` 0.45.
Below it, and not yet retried this turn, it loops back to the retriever once
with alpha shifted by 0.3 in the other direction and a
`RETRY_FETCH_MULTIPLIER` (4x) wider candidate pool. It never retries a
zero-document first pass: alpha cannot fix an exclusionary filter, so that
case goes straight to the agent, which is where the enrichment tool is
offered.

`quality_gate_status` is set to `"pass"` or `"retry"` on every return path;
leaving it unset lets a checkpointed `"retry"` from a previous turn leak
forward.

Writes: `quality_gate_status`, `quality_gate_retried`, `quality_gate_reason`,
`quality_gate_threshold_used`. Emits `QualityGateEvent`.

### 6. Summary

For the `summary` intent: summarizes the conversation from checkpointed
messages (`summarize_messages`) and hands the text to the agent. Emits
`SummaryEvent`.

### 7. Agent

Builds a grounded FACTS block from the retrieved documents
(`_build_grounded_context` — it lists a product's raw `product_color` and its
indexed `product_color_primary` as separate lines so the model can call out a
mismatch in prose), streams the answer token by token
(`LLMResponseStartEvent` / `LLMResponseChunkEvent`), then emits
`AgentCompleteEvent` carrying `citations`. Every return path — answer,
clarification, summary, no-results — includes a `citations` key.

Citations are `{label, url, asin?, image_url?}` with
`url = https://www.amazon.com/s?k={title}` (search by title survives delisted
ASINs), deduplicated, and dropped entirely when the best reranker score is
under 0.10. Inline links the model writes are stripped (`_strip_inline_links`).
`image_url` comes from the SQID dataset joined into the corpus; the UI renders
each cited bullet as a product card.

The agent node is registered with both faces, `RunnableCallable(agent_node,
aagent_node)`: `agent_node` is the body (unit tests call it directly),
`aagent_node` runs it in a worker thread so a taxonomy re-tag cannot stall the
WebSocket loop.

This node also hosts the enrichment tool offer and the correction detector —
see "Taxonomy growth and correction".

### 8. LLM judge

Runs after the agent on every retrieval turn (`quality/judge.py::LLMJudge`). A second structured-output call grades
the answer against the query and the same documents (shuffled, to blunt
positional bias) and returns `JudgmentResult`: faithfulness, answer
relevance, citation accuracy, context utilization, and a list of
`FlaggedClaim`s categorized `fabrication`, `cross_product_bleed`,
`inference`, or `overreach`.

Only `fabrication` and `cross_product_bleed` trigger a regeneration, once per
turn, with just those claims quoted back to the model; the corrected answer
replaces the streamed one via `LLMResponseCorrectedEvent`. The faithfulness
score is not the gate — the categorical flags are. `_format_docs_for_prompt`
keeps up to 10,000 characters per document because product bullets often put
the load-bearing attribute past character 2,000, and truncating them produced
false fabrication flags. The judge skips turns where the enrichment tool ran.

Writes: `judgment`, `original_judgment`, `corrected_response`,
`hallucination_retry_used`.

### Pipeline summary

After `AgentCompleteEvent`, `observable_agent` emits `PipelineSummaryEvent`:
per-stage latencies (hybrid, reranked), the judge's verdict, and a confidence
proxy (top-1 score, top-1/top-2 gap, variance, rank churn) bucketed high /
medium / low. It is a heuristic over the reranker's own scores, not an
offline relevance metric; the pure-Python helpers are in
`observability/confidence_proxy.py`.

## State

`core/agent_state.py::CustomAgentState` is a `TypedDict(total=False)`; only
`messages` (with the `add_messages` reducer) is guaranteed. Read with
`state.get("field", default)`. The file's docstring is the field-lifetime
table — which node writes what, and what must be reset per turn. LangGraph
filters each node's output to declared channels, so a new field must be added
there or it silently never reaches `astream_events`.

Checkpoints are stored in PostgreSQL by `langgraph-checkpoint-postgres`,
keyed by `thread_id`; the next turn on the same thread resumes from them.
`checkpoints/checkpoint_optimizer.py` keeps large transient fields (retrieved
documents) out of the persisted state.

## Events and the WebSocket contract

`api/schemas/events.py` defines every event (`BaseEvent` plus `NodeStart`,
`NodeEnd`, `ConversationContext`, `IntentClassification`, `QueryEvaluation`,
`QueryExpansion`, `OpenSearchQuery`, `HybridSearchStart/Result`,
`RerankerStart/Progress/Result`, `SearchProgress`, `QualityGate`, `Summary`,
`LLMReasoningStart/Chunk`, `LLMResponseStart/Chunk/Corrected`, `ToolCall`,
`AgentComplete`, `AgentError`, `PipelineSummary`, `Metrics`,
`EnrichmentTriggered`). Each carries `type`, `node`, and a timestamp.
`web/src/types/events.ts` mirrors them field for field;
`tests/unit/test_frontend_backend_event_parity.py` fails the build if they
diverge. Add an event on both sides, then handle it in
`web/src/stores/observabilityStore.ts` and render it in
`web/src/components/ObservabilityPanel/`.

- Connect: `GET /ws/chat?thread_id=<id>`. The `Origin` header is checked
  first (`verify_websocket_origin`); a disallowed origin is closed with 4003.
- Inbound: `{"type": "chat_message", "message": "...", "thread_id": "<id>"}`
  (thread id must match the connection's) and `{"type": "stop_execution"}`.
- Outbound: one complete JSON event per frame. Citations arrive on
  `agent_complete`, one frame after the final `llm_response_chunk`; the UI
  commits text and citations together so an answer renders exactly once.

Auth is same-origin only: `api/middleware/origin_auth.py` allow-lists the
localhost ports (5173, 8000, 8080 and a few dev spares); a disallowed
`Origin` is a 403. `/api/health` is public.

## OpenSearch index

`retrieval/vector_store.py::INDEX_MAPPING` is the single source of truth
(`setup.py` creates the index from it; `scripts/load_precomputed_indices.py`
refuses a dump whose mapping hash differs). In outline:

- `embedding` — `knn_vector`, 768 dims, Lucene HNSW, cosine,
  `ef_construction` 512, `m` 16.
- `chunk_text` (title + description + bullets), `title`, `product_brand`,
  `product_color`, `product_waterproof` — analyzed text with `light` (kstem)
  and `.heavy` (snowball) variants, a shingle subfield for phrase boosts, and
  a `chunk_text.words` subfield on an ASCII-word tokenizer used by the scoped
  re-tag to find candidate products.
- `product_color_primary/_secondary`, `product_waterproof_primary/_secondary`,
  `product_brand_normalized`, `product_id` — `keyword` filters.
- `title_suggest`, `brand_suggest` — edge-ngram fields, unused since typeahead was removed; they stay because the index mapping is pinned to the frozen dump.
- `product_image_url` — stored, not indexed.

The taxonomy lives in
`agentic_hybrid_search_attribute_mappings` (`retrieval/attribute_mapping_store.py`):
one document per `(attribute_type, variant) -> canonical`.

Both indices are loaded verbatim from `data/precomputed/` by every
`make setup`; the corpus is a frozen export and there is no ingest or rebuild
path (see `../data/README.md`). The one thing that mutates the products index
afterwards is the scoped re-tag below.

## Taxonomy growth and correction

Color and waterproof detection ran once, when the corpus was built:
`product_<type>_primary/_secondary` hold the canonical bucket for the
longest, word-boundary match of any known variant in `chunk_text`, driven by
the taxonomy store. That result ships in the precomputed export; nothing in
the repo re-detects the whole corpus. `pipeline/scoped_retag.py` is the
Python implementation of that exact algorithm (its docstring is the spec),
used only to re-tag the products a taxonomy change can affect.

`WATERPROOF_CANONICALS` (`retrieval/attribute_discovery.py`) registers the
`waterproof` bucket with **zero** variants on purpose: on a freshly loaded
corpus, "waterproof boots" is a real, reproducible gap. Do not seed it.

Two situations, one tool, one write path:

**Gap** — a term the taxonomy has never seen. `attribute_filter` extracts it,
the hard filter returns nothing, the gate does not retry an empty first pass,
and `agent_node` offers the LLM the `trigger_enrichment(attribute_type,
variant, canonical)` tool (`tools/enrichment_tool.py`, gated by
`ENABLE_ENRICHMENT_TOOL`). The offer is a manual two-call loop: bind, invoke,
execute the tool call and append a `ToolMessage`, invoke again without tools
for the final answer. The trigger fires when documents scored under the
threshold even after a retry, or when an `attribute_filter` query's filters
excluded everything on the first pass.

**Correction** — a shopper disputes an existing tag ("that's not tan, that's
tagged yellow"). `_detect_correction_signal` is a keyword pre-filter for
dispute language on `refinement` / `follow_up` turns only; when it fires,
`_try_correction_tool` offers the same tool with recent conversation as
context. A wrong-but-mapped result *passes* the quality gate — the products
are relevant, just filed in the wrong bucket — so no automated check can
find it; only a person looking at the answer can. `_build_grounded_context`
makes that possible by showing the raw color next to the indexed one.

**Value gate** — before either path executes the tool,
`quality/enrichment_value_judge.py` makes an independent structured-output
call (`JUDGE_MODEL`, temperature 0) asking whether the change would improve
search for real shoppers, given the current mapping and the conversation. A
decline short-circuits the write and the agent explains why.
`POST /api/admin/enrich` (an operator's explicit action) bypasses it.

**Write path** — `quality/enrichment_service.py::enrich_attribute`:
classify the term (or take the LLM's canonical), write the mapping,
distinguish a no-op (same canonical, idempotent) from a correction
(`corrected_from`), then `pipeline/reindex_trigger.py` runs the scoped
re-tag: find candidates via `chunk_text.words`, re-run detection on just
those, bulk-update the changed ones. Measured live: tan → brown re-checked
905 products and re-tagged 679 in under a second; teaching "waterproof"
tagged 7,441 in about 8 seconds. No re-embedding. `EnrichmentTriggeredEvent`
narrates started / complete / failed / declined in the UI.

The two self-consuming demos re-arm through `POST /api/admin/demo-reset`
(`quality/demo_reset.py`), which restores the tan → yellow mis-mapping and
clears the waterproof taxonomy.

## Extension points

**A new pipeline node.** Implement it on `PipelineNodesMixin`, declare its
output fields in `CustomAgentState`, add it in `main.py::create_agent_graph`
with its edges, add its event to `events.py` and `events.ts`, accumulate it
in `observabilityStore.ts`, render it in the panel, and unit-test it with the
`bare_agent` fixture.

**A new attribute type.** There is no corpus-wide detection pass any more, so
a new type can only start the way `waterproof` does — registered in
`_CANONICAL_SEEDS_BY_TYPE` with an empty variant list and grown live. Add its
extraction field and filter in `_extract_attributes` (decide: hard filter like
color/waterproof, or soft like `feature`), give its field a BM25 boost in
`_build_multi_match`, and the tool and admin route accept the new
`attribute_type` unchanged. Corpus-wide seed coverage would need new one-off
tooling and a new export.

**A different LLM.** `core/llm.py::build_chat_model` is the one place a chat
model is constructed; the intent classifier, query evaluator, judge, and
value judge all require structured output. Query embeddings come from
`retrieval/embeddings.py`; changing the embedding model means a new corpus
export, since the index holds 768-dim `nomic-embed-text` vectors.

## Performance (M4 Max, local Ollama)

| Stage | Latency |
| --- | --- |
| Intent classification | ~300–500 ms |
| Query evaluation | 0 (fast path) – 500 ms |
| Vector + BM25 + RRF | ~300–800 ms |
| Cross-encoder rerank (40 docs) | ~1.5–2 s |
| Quality-gate retry | +1–2 s when it fires |
| Answer generation (streaming) | ~3–8 s |
| LLM judge (+ one regeneration) | ~5–30 s |
| **Per turn** | **~6–21 s** measured across the three demos |

Query embeddings are cached for 60 minutes (`observability/embedding_cache.py`).

## Debugging

- Backend and frontend logs: `logs/backend.log`, `logs/frontend.log`
  (`tail -f logs/*.log`). Logging is structlog (`core/logging_config.py`);
  `LOG_FORMAT=json` makes fields greppable.
- Every event is visible in the browser DevTools Network tab on the
  `/ws/chat` socket; the panel's F2 view shows the raw DSL per turn.
- `GET /api/admin/health` reports index document count and service status.
