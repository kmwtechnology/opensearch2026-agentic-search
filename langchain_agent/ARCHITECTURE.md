# Architecture — Agentic Hybrid Search LangGraph Agent

This document provides a deep-dive into the system design, pipeline flow, state management, and observable events. Start here if you want to understand how the agent works end-to-end.

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         User Interfaces                             │
│  ┌─────────────────────────┐         ┌─────────────────────────┐   │
│  │   Web UI (React 18)     │◄───────►│  FastAPI WebSocket API  │   │
│  │  - Chat Panel           │         │  - Real-time streaming  │   │
│  │  - Observability Panel  │         │  - Event emission       │   │
│  └─────────────────────────┘         └─────────────────────────┘   │
└──────────────────┬────────────────────────────────────┬──────────────┘
                   │                                    │
                   ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LangGraph Pipeline                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   Intent     │  │    Query     │  │  Retriever   │              │
│  │  Classifier  │─►│  Evaluator   │─►│ (Hybrid)     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│         │                │                    │                    │
│         │                │             ┌──────┴──────┐             │
│         │                │             ▼             ▼             │
│         │                │        ┌─────────────────────────────┐  │
│         │                │        │  Vector + BM25 Fusion (RRF) │  │
│         │                │        │  - HNSW knn_vector          │  │
│         │                │        │  - BM25 lexical             │  │
│         │                │        └─────────────────────────────┘  │
│         │                │                    │                    │
│         │                │                    ▼                    │
│         │                │            ┌──────────────┐             │
│         │                │            │  Reranker    │             │
│         │                │            │  (LLM)       │             │
│         │                │            └──────────────┘             │
│         │                │                    │                    │
│         │                │                    ▼                    │
│         │                │            ┌──────────────┐             │
│         │                └───────────►│ Quality Gate │             │
│         │                             │ (Retry?)     │             │
│         │                             └──────────────┘             │
│         │                                    │                    │
│         ├───────────────────────────────────►│                    │
│         │                                    │                    │
│         ▼                                    ▼                    │
│  ┌──────────────────────────────────────────────────┐             │
│  │  Agent Node (Response Generation)                │             │
│  │  - Formats retrieved documents                   │             │
│  │  - Generates conversational response             │             │
│  │  - Builds citations (Amazon URLs)                │             │
│  │  - Streams token-by-token via WebSocket         │             │
│  └──────────────────────────────────────────────────┘             │
│         │                                                          │
└─────────┼──────────────────────────────────────────────────────────┘
          │
     ┌────┴────┐
     ▼         ▼
  PostgreSQL  OpenSearch
  (Checkpts)  (Vector DB)
```

## Pipeline Nodes (Detailed)

### 1. Intent Classifier

**Input State**: `messages` (conversation history)

**Process**:

- Keyword-based fast-path: pattern matching for 6 intents
  - `search` — product discovery ("find me...")
  - `comparison` — compare products ("Sony vs Bose")
  - `attribute_filter` — filtered search ("blue running shoes")
  - `refinement` — constrain prior results ("make them waterproof")
  - `follow_up` — vague continuation ("the next one?")
  - `summary` — summarize conversation ("what did we discuss?")
- LLM fallback: Gemini 3.1 Flash Lite classifies if confidence < 0.7
- Emits `IntentClassificationEvent` with detected intent and confidence

**Output State**:

- `intent`: Detected intent (one of 6 above)
- `intent_confidence`: 0.0–1.0 score
- `user_query`: Cleaned query string
- `reasoning`: Explanation of classification

**Key Decision**: If confidence < 0.7, agent asks for clarification instead of proceeding.

---

### 2. Query Evaluator

**Input State**: `user_query`, `intent`

**Process**:

- **Fast-path**: Immediate α assignment for intent-specific categories
  - `comparison` → α = 0.60 (semantic-heavy, needs meaning matching)
  - `attribute_filter` → α = 0.25 (lexical-heavy, exact attributes)
  - `refinement` → α = 0.35 (lexical-heavy, constrains prior results)
- **LLM-path**: For `search` and `follow_up`, Gemini evaluates query type and assigns α
- **Query expansion**: Resolves pronouns ("does it"), comparatives ("which is cheaper"), short attribute questions ("how much?") using conversation history
- Skips expansion if query contains specific brand/product name (avoids over-expansion)
- Emits `QueryEvaluationEvent` with assigned α, reasoning, expanded query if applicable

**Output State**:

- `alpha`: 0.0–1.0 weighting for hybrid search
- `query_analysis`: Explanation of α choice

**α Interpretation Table**:

| α Range | Strategy | Best For |
|---------|----------|----------|
| 0.0–0.15 | Pure lexical (BM25) | Exact IDs, ASINs, UPCs |
| 0.15–0.40 | Lexical-heavy | Brand + category, specific attributes |
| 0.40–0.60 | Balanced | Feature combinations, activity-based |
| 0.60–0.75 | Semantic-heavy | Conceptual needs, occasion-based |
| 0.75–1.0 | Pure semantic | Gift ideas, mood/style, exploration |

---

### 3. Retriever (Hybrid Search)

**Input State**: `alpha`, `user_query`, optional filters

**Process**:

- **Attribute extraction & filtering** (for `attribute_filter` intent):
  - Extracts brand and color constraints from user query (LLM-powered)
  - Filters on **normalized fields**:
    - `product_color_primary` (normalized primary color, e.g., "black", "white", "blue")
    - `product_color_secondary` (normalized secondary color if compound entry, e.g., "Black & Purple" → primary: "black", secondary: "purple")
    - `product_brand_normalized` (case-folded brand, e.g., "sony", "apple")
  - Normalization rules: 16 canonical color forms (e.g., "grey" → "gray", "navy" → "blue", "taupe" → "brown"), synonym expansion, compound color extraction
  - See **Attribute Normalization** section below for details
  - **Filter relaxation**: If fetch returns < 3 results with all filters, drops multi-match (material/size) filters but keeps color + brand exact-match filters (user explicitly named them)
- **Dual-path search**:
  1. **Vector Search** (HNSW): Gemini 768-dim embeddings, cosine similarity
  2. **Lexical Search** (BM25): Dual-analyzer pattern — primary fields (`chunk_text`, `product_brand`, `product_color`) use `light_english_analyzer` (kstem, light stemming) for precision; `.heavy` sub-fields use `heavy_english_analyzer` (snowball, aggressive stemming) at ^0.3 boost for morphological recall fallback. Dense vectors handle the bulk of morphological recall, so BM25 is tuned for precision ("Beats" ≠ "beat" with kstem, but still matches "running/runs/ran" via embeddings).
- **RRF Fusion** (Reciprocal Rank Fusion):

  ```text
  score = Σ 1/(rank + k)  where k=60 (RRF constant)
  ```

  Normalizes ranks from both methods, avoids probability calibration
- **Candidate fetching**: `fetch_k=20` candidates (before deduplication/reranking)
- **Product deduplication**: ESCI products may have multiple chunks; collapse to one per product
- Emits `RetrievalProgressEvent` with candidate counts, top-K previews, OpenSearchQueryEvent with DSL details

**Output State**:

- `retrieved_documents`: List of top `fetch_k` candidates (Document objects)

**Key Details**:

- `alpha=0.0` → pure BM25 (ignores vector scores)
- `alpha=1.0` → pure vector (ignores lexical scores)
- RRF is robust to outliers and doesn't require probability calibration

---

### 4. Reranker (LLM-Based Scoring)

**Input State**: `retrieved_documents`, `user_query`

**Process**:

- **Batch scoring**: Sends up to `batch_size=10` documents per LLM call
- **Structured output**: Gemini 3.1 Flash Lite returns JSON with score per document
- **Pydantic validation**: Ensures all scores are floats in [0.0, 1.0]
- **Sorting**: Returns documents sorted by score (highest first)
- Emits `RerankerProgressEvent` with per-document scores and top-K selection
- Sets `reranker_max_score` for Quality Gate decision

**Output State**:

- `reranker_max_score`: Maximum score across all documents (0.0–1.0)

**Score Interpretation**:

- 0.0–0.2: Off-topic, unrelated
- 0.2–0.5: Partial match, weak relevance
- 0.5–0.7: Good match, clearly relevant
- 0.7–1.0: Excellent match, high confidence

---

### 5. Quality Gate

**Input State**: `reranker_max_score`, `alpha`, `retrieved_documents`

**Process**:

- **Decision Logic**:
  1. If `max_score >= 0.50` → **PASS**: Continue to agent
  2. If `max_score < 0.50` and not yet retried → **RETRY**:
     - Adjust α by ±0.3 (opposite direction from original)
     - Loop back to retriever with new α
  3. If already retried or other condition → **ACCEPT**: Continue to agent
- **Intent-specific thresholds** (override the 0.50 default):
  - `comparison`: 0.55 (stricter, needs clear winner)
  - `attribute_filter`: 0.45 (looser, exact attribute match is easy)
  - `search`, `follow_up`: 0.50 (standard)
- Emits `QualityGateEvent` with pass/retry/accept decision and reasoning

**Output State**:

- `quality_gate_retried`: Boolean flag (True if retry was triggered)
- `quality_gate_reason`: Explanation of decision
- `quality_gate_threshold_used`: The intent-specific threshold that was applied (float)

**Why This Works**:

- Catches cases where initial α was poorly calibrated
- If original α favored semantics but query is exact ID → adjust to lexical
- If original α favored lexical but query is conceptual → adjust to semantic
- Avoids endless retry loops (max 1 retry per query)

---

### 6. Agent (Response Generation)

**Input State**: `retrieved_documents` (after quality gate), `user_query`, `messages`

**Process**:

- **Document formatting**: Creates context window with product details
- **LLM generation**: Gemini 3 Flash generates conversational response
- **Citation building**:
  - Extracts product IDs from metadata
  - Constructs Amazon URLs: `https://www.amazon.com/dp/{product_id}`
  - Filters by minimum reranker score (0.10 threshold)
  - Deduplicates by URL
- **Token-by-token streaming**: Emits `LLMResponseChunkEvent` with each token
- **Link verification** (optional): Validates URLs before inclusion (60-min TTL cache)
- Emits `AgentCompleteEvent` when done

**Output State**:

- Appends `AIMessage` to `messages`
- Updates checkpoint in PostgreSQL (for conversation persistence)

**Key Details**:

- ESCI products have ASIN metadata; canonical URL construction
- Streaming allows real-time UI feedback (not waiting for full response)
- Link verification filters out broken URLs (trust but verify)

---

## State Management (CustomAgentState)

```python
class CustomAgentState(TypedDict, total=False):
    # Core (required)
    messages: Sequence[BaseMessage]  # Always exists, managed by add_messages reducer

    # Intent Classifier (→)
    intent: str
    intent_confidence: float
    user_query: str
    reasoning: str

    # Query Evaluator (→)
    alpha: float  # 0.0–1.0 weighting
    query_analysis: str

    # Retriever (→)
    retrieved_documents: List[Document]

    # Reranker (→)
    reranker_max_score: float  # 0.0–1.0

    # Quality Gate (→)
    quality_gate_retried: bool
    quality_gate_reason: str | None
    quality_gate_threshold_used: float  # intent-specific threshold applied
```

**IMPORTANT**: Since `total=False`, optional fields are **not guaranteed** at runtime.

**Safe Access**:

```python
alpha = state.get("alpha", 0.25)  # ✓ Safe
alpha = state["alpha"]             # ✗ KeyError before query_evaluator runs
```

---

## Observable Events (Real-Time Streaming)

The pipeline emits typed Pydantic events over WebSocket for every stage. Frontend subscribes and visualizes in real-time.

### Event Flow

```text
Backend (main.py)              WebSocket               Frontend (React)
─────────────────              ─────────────           ───────────────
emit_event(event) ──JSON──────────────────────────────► receiveEvent(json)
                                                         parse → Pydantic
                                                         → observabilityStore
                                                         → ObservabilityPanel
```

### Event Types (by Node)

| Node | Event | Fields |
|------|-------|--------|
| Intent Classifier | `IntentClassificationEvent` | intent, confidence, reasoning |
| Query Evaluator | `QueryEvaluationEvent` | alpha, query_analysis, expanded_query |
| Retriever | `RetrievalProgressEvent`, `OpenSearchQueryEvent` | query_dsl, alpha, intent, candidates; `query_type` ∈ {`hybrid`, `bm25_baseline`, `quality_gate_retry`} |
| Reranker | `RerankerProgressEvent` | per-doc scores, top-k |
| Quality Gate | `QualityGateEvent` | decision (pass/retry/accept), reasoning |
| Agent | `LLMResponseChunkEvent`, `AgentCompleteEvent` | token, finish_reason |
| Agent (low confidence) | `ClarificationRequestedEvent`, `ClarificationResolvedEvent` | emitted when intent confidence < 0.7; resolved on user reply |
| LLM Judge | `LLMResponseCorrectedEvent` | `corrected_content`, `original_faithfulness`, `corrected_faithfulness`; emitted when judge auto-correction fires (any fabrication/cross-product-bleed flag present — faithfulness score is NOT a gate, see issue #77); `hallucination_retry_used` reset to `False` in `intent_classifier_node` so the gate is live for every new user turn (issue #83); frontend replaces the streamed chat message |

### Event Schema Sync

**Critical**: Event Pydantic models in `api/schemas/events.py` **must** stay in sync with TypeScript types in `web/src/types/events.ts`.

**Check-in workflow**:

1. Add new event to `api/schemas/events.py` (e.g., `NewNodeProgressEvent`)
2. Add TypeScript type to `web/src/types/events.ts` with same field names
3. Call `_emit_event_from_sync(NewNodeProgressEvent(...), node="my_node")` in backend node
4. Add accumulation logic in `web/src/stores/observabilityStore.ts`
5. Add UI rendering in `web/src/components/ObservabilityPanel/`

If the two schemas diverge, WebSocket serialization will fail or frontend won't render the event.

---

## Typeahead Autocomplete (`GET /api/suggest`)

The typeahead surface lives outside the LangGraph pipeline — it's a
synchronous FastAPI route backed directly by OpenSearch.

```text
User keystroke (debounced)
   │
   ▼
GET /api/suggest?q=<prefix>&limit=8      (api/routes/suggest.py)
   │
   ├─► OpenSearch prefix query
   │     - edge-ngram analyzer on title_suggest + brand_suggest subfields
   │     - returns top-N product and brand suggestions
   │
   ├─► No results? → fuzzy fallback
   │     - distance-1 match for single-character typos (e.g. "nikey" → "nike")
   │
   └─► Spell correction pass
         - Levenshtein distance on the corpus vocabulary
         - SequenceMatcher ratio ≥ 0.6, confidence ≥ 0.5
         - Skipped if the query is already a corpus token
         - Skipped if the query is a prefix of the candidate
         - Returns {"spell_correction": {"title": "...", "brand": "...", "score": 0.xx}}
```

Frontend rendering:

- `web/src/hooks/useRecentSearches.ts` — localStorage history (max 8,
  case-insensitive dedup, clear button)
- `web/src/components/ChatPanel/TypeaheadSuggestions.tsx` — three-section
  dropdown (Did you mean? / Suggestions / Recent Searches), ARIA combobox
  semantics, `ArrowDown`/`ArrowUp`/`Enter`/`Tab`/`Esc` handling, and
  `AbortController` cancellation of stale fetches

The typeahead does not emit observable pipeline events — it's purely a
UI-assist path.

---

## Admin Reindex API (`/api/admin/*`)

Admin routes (`api/routes/admin.py`) provide operational control over the
ESCI index without redeploying:

```text
GET /api/admin/reindex?reset_index=true&limit=10000
   │
   ├─► spawns background task (FastAPI BackgroundTasks)
   │     1. optional index reset
   │     2. run ingest_esci_products logic
   │     3. update in-memory job state
   │
   └─► returns 200 with {"status":"started", "message":"..."} immediately

GET /api/admin/reindex/status
   └─► returns {"status": "queued"|"running"|"success"|"error",
                 "started_at": "...", "finished_at": "...",
                 "documents_ingested": N, "chunks_created": N,
                 "limit": N, "reset_index": bool, "error": "..." | null}

GET /api/admin/health
   └─► returns {"status": "healthy", "opensearch": {"connected": bool,
                 "index": "...", "documents": N}}
```

A dedicated GitHub Actions workflow (`.github/workflows/reindex.yml`)
exposes the flow as a manual dispatch — it calls `GET /api/admin/reindex`
on the deployed Cloud Run instance and polls `/api/admin/reindex/status`
until the job reaches a terminal state (`success` or `error`).

---

## BM25 Lexical Optimizations

The lexical side of hybrid search layers several relevance boosters on top
of vanilla BM25:

| Optimization | Effect |
|--------------|--------|
| **Synonym expansion** | Search-time synonym mapping broadens recall |
| **Fuzzy matching** | Auto-edit-distance on longer tokens catches typos |
| **Phrase boosting** | Exact multi-word matches outrank loose token matches |
| **Field boosting** | Title/brand fields weighted above generic content |
| **Phonetic matching** | `double_metaphone` analyzer (from the `analysis-phonetic` OpenSearch plugin) matches "fone" to "phone" |

These are surfaced in the observability panel via the
`SearchOptimizationDetails` component
(`web/src/components/ObservabilityPanel/SearchOptimizationDetails.tsx`)
as a collapsible "Search Optimizations" card, alongside the existing
`OpenSearchQueryEvent` rendering.

---

## Hybrid Search Deep-Dive

### Why Hybrid (Vector + BM25)?

| Approach | Pros | Cons |
|----------|------|------|
| **Pure Vector** | Semantic understanding, conceptual matching | Misses exact terms, slow (200–500ms) |
| **Pure BM25** | Exact term matching, fast (100–300ms) | No semantics, fails on synonyms/concepts |
| **Hybrid (RRF)** | Both signals, robust to outliers, fast enough | Slightly slower than pure, needs α tuning |

### RRF Formula

```text
For each document in rank list:
  score = Σ 1/(rank_vector + 60) + 1/(rank_lexical + 60)

Normalize both ranks before fusion:
  - Vector rank: #1 most similar → k=60 is constant
  - Lexical rank: #1 exact term match → k=60 is constant
```

**Why k=60?** Balances contribution of top-K results. Larger k → lower rank penalties.

### Alpha Parameter

**Definition**: `alpha = weight of vector score`

- **α=0.0** (pure lexical):

  ```text
  final_score = lexical_score × 1.0 + vector_score × 0.0
  ```

  Best for exact IDs, ASINs, model numbers (e.g., "iPhone 15 Pro")

- **α=0.5** (balanced):

  ```text
  final_score = lexical_score × 0.5 + vector_score × 0.5
  ```

  Good for mixed queries (e.g., "blue running shoes")

- **α=1.0** (pure semantic):

  ```text
  final_score = lexical_score × 0.0 + vector_score × 1.0
  ```

  Best for conceptual queries (e.g., "gift ideas for someone who loves hiking")

### Quality Gate Retry with Alpha Adjustment

If `reranker_max_score < 0.5`:

1. Was original query `search` or `follow_up`? (LLM-path intents)
   - Yes: Retry with **opposite** α direction
     - If α was 0.7 → try 0.4 (favor lexical)
     - If α was 0.3 → try 0.6 (favor semantic)
   - No: Accept results (fast-path intents already tuned)

2. Loop retriever → reranker with new α

3. If still low score, accept results (avoid endless retry)

**Example**:

```text
User: "best gifts for someone into photography"
Intent: search (LLM-path)
Query Evaluator: α=0.8 (conceptual)
Retrieved results scored poorly (0.35 max)
Quality Gate: Adjust to α=0.5 (balanced), retry
New results score better (0.62 max)
Continue to agent
```

---

## OpenSearch Index Design

### Mapping (per document/product)

```json
{
  "knn_vector": {
    "type": "knn_vector",
    "dimension": 768,
    "method": {
      "engine": "hnsw",
      "space_type": "cosinesimil",
      "parameters": {
        "ef_construction": 512,
        "m": 4
      }
    }
  },
  "content": {
    "type": "text",
    "analyzer": "english"
  },
  "product_brand": {
    "type": "text",
    "analyzer": "english",
    "fields": {
      "keyword": {
        "type": "keyword"
      }
    }
  },
  "product_color": {
    "type": "text",
    "analyzer": "english",
    "fields": {
      "keyword": {
        "type": "keyword"
      }
    }
  },
  "product_color_primary": {
    "type": "keyword"
  },
  "product_color_secondary": {
    "type": "keyword"
  },
  "product_brand_normalized": {
    "type": "keyword"
  },
  "product_id": {
    "type": "keyword"
  }
}
```

### Why Dual-Mapped Fields?

`product_brand` and `product_color` are mapped as both **text** (for BM25 search) and **keyword** (for exact faceting):

- **Text mapping**: `_search` queries match "Sony" in "Sony WH-1000XM5"
- **Keyword mapping** (`.keyword` suffix): Exact match, no tokenization, used for faceting

### Attribute Normalization (Color & Brand)

**Problem:** Raw color/brand fields have high variance ("grey" vs "gray", "Light Grey", "Black & Purple"). Users expect "black" to match all black variants.

**Solution:** Post-ingest normalization (Python script in Step 5b of `lucille_ingest.sh`):

1. **Color Normalization** (16 canonical forms):
   - Synonym expansion: "grey" → "gray", "navy" → "blue", "taupe" → "brown"
   - Compound extraction: "Black & Purple" → primary: "black", secondary: "purple"
   - Descriptor stripping: "light grey" → "grey" → "gray"
   - Case folding and special-character cleanup

2. **Brand Normalization**:
   - Case folding: "Sony" → "sony"
   - Generic consolidation: "Unknown", "N/A" deduplicated
   - Preserves real brands

3. **Output fields** (added to every document):
   - `product_color_primary`: Canonical primary color (keyword, for exact filtering)
   - `product_color_secondary`: Canonical secondary color if present (keyword)
   - `product_brand_normalized`: Case-folded brand (keyword, for exact filtering)

**Impact:**
- Filter recall: 79.4% of products classified into 16 base colors
- "blue running shoes" now matches "Navy Running Shoes", "Cyan Runners", etc.
- Deterministic (rules-only, no AI calls) — reproducible, auditable
- Raw fields preserved — no data loss

**Implementation Details:**
- Executed after Lucille ingest via `scripts/enrich_attribute_normalization.py`
- Uses `OpenSearch search_after` pagination; bulk-updates all docs
- `AttributeNormalizer` class (reusable for tests, future offline enrichment)
- `color_mappings.json` committed to git for reproducibility

### Search Pipeline (OpenSearch DSL)

```json
{
  "query": {
    "bool": {
      "should": [
        {
          "knn": {
            "knn_vector": {
              "vector": [0.1, 0.2, ...],
              "k": 20
            }
          }
        },
        {
          "multi_match": {
            "query": "wireless headphones",
            "fields": ["content", "product_brand^2", "product_color"]
          }
        }
      ],
      "filter": [
        {
          "term": {
            "product_locale.keyword": "us"
          }
        }
      ]
    }
  }
}
```

**With attribute filters** (e.g., "black wireless headphones"):

```json
{
  "query": {
    "bool": {
      "should": [
        {
          "knn": {
            "knn_vector": {
              "vector": [0.1, 0.2, ...],
              "k": 20
            }
          }
        },
        {
          "multi_match": {
            "query": "wireless headphones",
            "fields": ["content", "product_brand^2", "product_color"]
          }
        }
      ],
      "filter": [
        {
          "term": {
            "product_locale.keyword": "us"
          }
        },
        {
          "match": {
            "product_color_primary": "black"
          }
        }
      ]
    }
  }
}
```

Both `knn` (vector) and `multi_match` (BM25) queries run in parallel; results are fused via RRF at the retriever level. Attribute filters are applied post-fusion to narrow results.

---

## Conversation Memory & Checkpointing

### Checkpoint Storage

LangGraph checkpoints are stored in PostgreSQL, allowing conversation resumption:

1. User sends message → agent processes
2. `agent_node` appends `AIMessage` to `messages`
3. Graph saves checkpoint with `thread_id` (conversation ID)
4. Next turn, load checkpoint → history restored
5. Continue conversation as if uninterrupted

### Context Compaction

For long conversations, context window fills up:

- Compaction (enabled by default): Trims older messages when `len(context) > MAX_CONTEXT_TOKENS`
- Keeps recent `k` turns + system prompt
- Prevents timeout on very long chats

---

## Extension Points

### Adding a New Intent

1. Add to intent list in `_build_intent_prompt()` docstring
2. Implement keyword patterns in `intent_classifier_node()`
3. Add LLM prompt case if using fallback
4. Set default α in `query_evaluator_node()` fast-path
5. Add test in `tests/unit/intent/test_intent_classifier.py`

### Adding a New Pipeline Node

1. Implement `async def my_node(state: CustomAgentState) -> Dict[str, Any]:`
2. Add fields to `CustomAgentState` if returning new state
3. Add to `build_graph()`: `graph.add_node("my_node", my_node)`
4. Wire edges (conditional or deterministic)
5. Add `MyNodeEvent` to `api/schemas/events.py` + `web/src/types/events.ts`
6. Add accumulation in `observabilityStore.ts`
7. Add UI rendering in ObservabilityPanel
8. Test with `PYTHONPATH=. pytest tests/integration/test_pipeline_flow.py`

### Swapping the LLM Provider

1. Replace `ChatGoogleGenerativeAI` with `ChatOpenAI`, `ChatAnthropic`, etc. in `main.py`
2. Update model names in `config.py`
3. Ensure all models support structured output (required for reranker)
4. Update temperature/token settings if needed
5. Test: `PYTHONPATH=. python3 setup.py` to validate API connection

---

## Performance Characteristics

| Component | Latency | Notes |
|-----------|---------|-------|
| Intent Classification | 0–500ms | Keyword fast-path ~10ms, LLM ~500ms |
| Query Evaluation | 0–500ms | Fast-path instant, LLM ~300–500ms |
| Vector Search (HNSW) | 200–500ms | 768-dim, k=20 |
| Lexical Search (BM25) | 100–300ms | Full-text analysis |
| RRF Fusion | ~10ms | In-memory rank merge |
| Reranking (LLM) | 1–2s | Batch scoring, 10 docs per call |
| Quality Gate Retry | +1–2s | If triggered (max 1 retry) |
| Response Generation | 3–8s | LLM streaming (cached/fresh embedding) |
| **Total (Q&A)** | **6–15s** | Sum of all stages |

Cached queries (60-min embedding cache) save ~2–3s.

---

## Testing Checklist

- [ ] Unit tests: `PYTHONPATH=. pytest tests/unit/ -v` (~0.5s, all mocked)
- [ ] Integration tests: `PYTHONPATH=. pytest tests/integration/ -v` (needs Postgres + OpenSearch)
- [ ] E2E tests: `PYTHONPATH=. pytest tests/e2e/ -v` (needs Cloud Run deployed)
- [ ] Manual: Query all 6 intents, verify correct α assigned, check observability panel
- [ ] Manual: Trigger quality gate retry by searching for something obscure
- [ ] Manual: Verify citations are valid Amazon URLs

---

## Debugging Tips

### Use LangSmith Tracing

Enable `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` in `.env`. View traces at <https://smith.langchain.com>.

### Check Observability Panel

Open browser DevTools → Network tab. WebSocket messages show every event emitted.

### Log Structured Output

Structured logging (`json` format) in `logging_config.py` makes it easy to grep specific fields:

```bash
grep '"node":"retriever"' app.log
```

### Verify Vector Embeddings

```python
from vector_store import get_embeddings
emb = get_embeddings("wireless headphones")
print(len(emb))  # Should be 768
```

### Test RRF Fusion

```python
from vector_store import OpenSearchRetriever
retriever.invoke("query", search_type="hybrid", alpha=0.5)
```

---

## Summary

The Agentic Hybrid Search system is a **LangGraph-powered RAG agent** that:

1. **Classifies intent** (6 categories) to route conversation
2. **Evaluates queries** with dynamic α to balance semantic/lexical search
3. **Retrieves candidates** via hybrid search (vector + BM25 fused by RRF)
4. **Reranks** with LLM-based scoring
5. **Quality gates** with automatic α retry if scores are low
6. **Generates responses** with citations and streaming
7. **Persists memory** in PostgreSQL checkpoints
8. **Emits observable events** for real-time UI visualization

Every stage is testable, extensible, and documented. The system is designed for e-commerce product discovery but generalizes to any RAG use case.
