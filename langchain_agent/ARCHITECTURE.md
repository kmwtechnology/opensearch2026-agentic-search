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
  - Extracts brand, color, material/feature, and size constraints from the user query (LLM-powered)
  - Classifies color/material terms against the OS-backed taxonomy first, then filters on
    **detected fields**:
    - `product_color_primary`/`_secondary`, `product_material_primary`/`_secondary` — canonical
      values (keyword), populated during ingest by `AttributeDetectorStage`
    - `product_brand_normalized` — case-folded brand, e.g., "sony", "apple"
  - Color's unresolved-term fallback is a **hard** exact-match filter; material's is a **soft**
    lexical `multi_match` (protects legitimate non-material feature words like "waterproof") —
    see **Attribute Detection** section below for the full mechanism and why this asymmetry
    matters for the enrichment flywheel
  - **Filter relaxation**: If fetch returns < 3 results with all filters, drops multi-match
    (material/size) filters but keeps color + brand exact-match filters (user explicitly named
    them) — this can retry all the way down to 0 fully-filtered results
- **Dual-path search**:
  1. **Vector Search** (HNSW): Gemini 768-dim embeddings, cosine similarity
  2. **Lexical Search** (BM25): Dual-analyzer pattern — primary fields (`chunk_text`, `product_brand`, `product_color`) use `light_english_analyzer` (kstem, light stemming) for precision; `.heavy` sub-fields use `heavy_english_analyzer` (snowball, aggressive stemming) at ^0.3 boost for morphological recall fallback. Dense vectors handle the bulk of morphological recall, so BM25 is tuned for precision ("Beats" ≠ "beat" with kstem, but still matches "running/runs/ran" via embeddings).
- **RRF Fusion** (Reciprocal Rank Fusion):

  ```text
  score = Σ 1/(rank + k)  where k=60 (RRF constant)
  ```

  Normalizes ranks from both methods, avoids probability calibration
- **Candidate fetching**: `fetch_k=40` candidates (before deduplication/reranking)
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
  - `refinement`: 0.45 (looser, narrowing scope is easy)
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
  - Extracts product titles from metadata (ESCI products have no ASIN; use title-based search for robustness)
  - Constructs Amazon URLs: `https://www.amazon.com/s?k={title}` (search by title; ASIN-based `/dp/` links 404 frequently)
  - Filters by minimum reranker score (0.10 threshold)
  - Deduplicates by URL
  - Post-processor strips any inline URLs/markdown the LLM emitted (agent prompt forbids inline URLs; belt-and-suspenders defense)
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

### 7. LLM Judge (Hallucination Detection & Auto-Correction)

**Input State**: `messages` (with the Agent's response appended), `retrieved_documents`, `user_query`

**Trigger**: Runs **after Agent** only when both `optimizations.llm` and `optimizations.llm_judge` are enabled (configurable).

**Process**:

- **Blind A/B evaluation**: Gemini Flash Lite scores the response against the query + context, unaware of the original LLM's generation process (reduces inherent bias)
- **Positional-bias randomization**: Shuffles doc order when presenting context to avoid ranking artifacts
- **Produces `JudgmentResult`**: Pydantic model with:
  - `pairwise_verdict` — boolean (is this response accurate?)
  - `absolute_scores` (0.0–1.0 each):
    - `faithfulness` — claims grounded in retrieved context
    - `answer_relevance` — response answers the user's query
    - `citation_accuracy` — cited products actually match claims
    - `context_utilization` — uses available context, doesn't fabricate
  - `List[FlaggedClaim]` — suspicious claims, each tagged with a `HallucinationCategory`:
    - `fabrication` — claim unsupported by any retrieved doc (RETRY-ELIGIBLE)
    - `cross_product_bleed` — claim from one product mistakenly applied to another (RETRY-ELIGIBLE)
    - `inference` — plausible inference not explicitly stated (warning-only, no retry)
    - `overreach` — overgeneralization or scope creep (warning-only, no retry)

**Auto-Correction Retry (Layer 3a)**:

- Triggers if **any flag has `category in {fabrication, cross_product_bleed}`** AND this is the first retry this turn
- **Critically**: `hallucination_retry_used` flag is **reset to `False` at the start of every new user turn** in `intent_classifier_node` (issue #83) — without this reset, LangGraph's Postgres checkpoint persistence would permanently disable retry for all subsequent turns after the first flag
- Regenerator receives **only retry-worthy claim text** (doesn't ask model to "fix" inference/overreach flags)
- New response replaces the original in `messages` and UI (via `LLMResponseCorrectedEvent`)
- Inference/overreach flags surface in observability panel but skip the ~20–30s retry tax

**Output State**:

- `hallucination_retry_used`: Boolean; set True if auto-correction retry fired this turn (reset to False at start of next turn)
- `corrected_response`: If retry fired, the regenerated response text
- `llm_judgment`: The full `JudgmentResult` object

**CRITICAL Behaviors**:

1. **`faithfulness` score is NOT the gate** (issue #77) — LLM can assign high faithfulness while simultaneously flagging fabrications; categorical classification is authoritative
2. **All return paths in `agent_node` must include `"citations"` key** (issue #14) — observable_agent depends on consistent state shape; early returns (summary, clarify, no-info) return `"citations": []`
3. **`_format_docs_for_prompt` default `max_chars=10000`** — raised progressively (360 → 1500 → 2500 → 10000) because ESCI products with prose descriptions + Amazon bullets can reach ~2498 chars, with key construction attributes appearing late (char 2039+); tight limits cause false-positive fabrication flags on grounded claims

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

### WebSocket Security & Message Contract

**Handshake**:
- Frontend initiates `GET /ws/<thread_id>` (via `useWebSocket` hook)
- Backend checks session cookie (or admin token) before upgrading to WebSocket
- If auth fails, the backend closes with code **4401** — frontend interprets this as `markUnauthenticated()` and redirects to LoginScreen
- Once upgraded, the connection is authenticated for its lifetime (session cookie persists across messages)

**Inbound Message Contract** (frontend → backend):
```typescript
{
  type: "chat_message",
  message: string,
  thread_id: string
}
```
All messages must include these three fields; missing fields cause rejection. Thread ID must match the WebSocket URL path (prevents accidental cross-thread sends).

**Outbound Event Contract** (backend → frontend):
- All events are typed Pydantic models (see `api/schemas/events.py`)
- Every event includes:
  - `type: str` — event class name (must exist in `api/schemas/events.py`)
  - `node: str` — pipeline stage that emitted it (intent_classifier, retriever, agent, etc.)
  - Timestamp metadata
- TypeScript types in `web/src/types/events.ts` must match Python schema exactly; CI-enforced by `test_frontend_backend_event_parity.py`

**Critical Invariants**:
- All agent return paths must include `"citations": []` or populated list (issue #14) — observable_agent depends on consistent state shape for WebSocket emission
- No partial events — every message is complete JSON before transmission
- No stream fragmentation — large responses (LLMResponseChunkEvent) stream token-by-token but each chunk is a complete, valid JSON event

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

## Re-Indexing

The canonical re-indexing mechanism is the **GitHub Actions workflow** `.github/workflows/reindex.yml`, which runs **Lucille ETL via Docker** on the Actions runner to ingest ESCI products and (optionally) judgments into the remote OpenSearch cluster.

**Workflow dispatch parameters**:
- `reset_index` (default: `true`) — drop and recreate the products index before ingest
- `reindex_judgments` (default: `false`) — also rebuild the esci_judgments (ground-truth) index

**For details**, see:
- `.github/workflows/reindex.yml` — workflow file with WIF auth, Secret Manager credential fetch, and Lucille Docker invocation
- `langchain_agent/scripts/lucille_ingest.sh` — orchestrates Lucille container with Docker Compose
- `data/README.md` — data format and file descriptions

**Admin API** (`api/routes/admin.py`):
- `GET /api/admin/health` — index document count, service status
- `GET /api/admin/diagnose` — field-level hit counts and mapping inspection
- `POST /api/admin/enrich` — grow the color/material taxonomy and trigger a
  real reindex; see "Enrichment Flywheel" below (gated by
  `ENABLE_ENRICHMENT_TOOL`, default off)
- Protected by same-origin check + (SessionMiddleware or Admin Token auth)

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

### Attribute Detection (Color & Material) and Brand Normalization

**Problem:** Raw color/material text has high variance ("grey" vs "gray",
"chrome" as a material with no dedicated field). Users expect "black" to
match all black variants, and a genuinely new variant term (a color/material
word the taxonomy hasn't seen yet) to be teachable without a code deploy.

**Solution:** Detection happens **during Lucille ingest**, not as a
post-ingest pass, driven by a taxonomy stored in OpenSearch — not a
committed file:

1. **`AttributeDetectorStage.java`** — one generic, parameterized Lucille
   stage (config param: `attributeType`). Scans `chunk_text`
   (title + description + bullet points) for known variants via a
   longest-match-first, word-boundary regex built from the taxonomy, and
   writes `product_<type>` (raw match, dual-mapped text field) and
   `product_<type>_primary`/`_secondary` (canonical, keyword). The pipeline
   config carries one distinct stage instance per attribute type currently
   registered (`detectColor`, `detectMaterial`) — both share the one Java
   class; a new attribute type gets a new stage instance automatically (see
   "Config Generation" below), zero new Java code.
   Sources its variant→canonical lookup from OpenSearch at `start()`
   (`agentic_hybrid_search_attribute_mappings` index, via
   `AttributeMappingStore` on the Python side) — no bundled-file fallback;
   logs a warning and produces no fields for that run if OpenSearch is
   unreachable.
2. **`BrandNormalizerStage.java`** — a small, separate, fixed transform
   (case folding, generic-placeholder consolidation like "Unknown"/"N/A").
   Not a discovered taxonomy, no OpenSearch dependency, always present.
3. **Output fields** (added to every document): `product_color_primary`/
   `_secondary`, `product_material_primary`/`_secondary` (both keyword, for
   exact filtering), `product_brand_normalized` (keyword).

**Impact** (measured against the current discovery-built taxonomies —
102 color variants, 34 material variants): `product_color_primary`
populated on 70.5% of products, `product_material_primary` on 44.7%,
`product_brand_normalized` on 96.4%. Deterministic detection (rules-only
regex match, no AI calls at ingest time) — reproducible, auditable. Raw
fields preserved — no data loss.

**Config Generation** (`config_generator.py`) — `products.conf` is no
longer a static committed file. `generate_products_conf()` renders the
full Lucille HOCON pipeline (fixed prelude/epilogue + one
`AttributeDetectorStage` block per attribute type currently registered in
OpenSearch) to `lucille-esci/conf/products.generated.conf`
(gitignored). `scripts/lucille_ingest.sh` regenerates this file
immediately before every run, so a reindex always reflects whatever
attribute types exist in OpenSearch *at that moment* — including one the
live enrichment flywheel (below) just registered.

### Enrichment Flywheel — Agent-Triggered Taxonomy Growth

**Problem:** Detection only recognizes variants already in the taxonomy.
A genuinely new term ("chrome" as a material, "camel" as a color) needs a
way to get added without a code deploy or manual data migration.

**Mechanism:**
1. `attribute_filter` intent extracts a color/material term via
   `_extract_attributes()`. Color's fallback for an unresolved term is a
   hard exact-match filter; material's is a soft `multi_match` against
   `title`/`chunk_text` — deliberately softer, since the same code path
   also has to handle non-material feature words ("waterproof", "noise
   canceling") that a hard filter would wrongly exclude.
2. If the query genuinely returns nothing, `agent_node` offers the LLM a
   `trigger_enrichment(attribute_type, variant, canonical)` tool (a real
   `@tool`, bound via a manual two-call loop — bind → invoke → if the LLM
   calls it, execute + append a `ToolMessage` → invoke again without
   tools for the final response). Gated by `ENABLE_ENRICHMENT_TOOL`
   (default off).
3. The tool calls `enrichment_service.enrich_attribute(...)`: classify (or
   use the LLM-supplied canonical directly) → write the mapping to
   OpenSearch → additively ensure the index mapping has the
   `product_<type>` fields → regenerate `products.generated.conf` →
   trigger `scripts/lucille_ingest.sh` as a real subprocess (~15-20s for
   9,618 products — a genuine full reindex, not a scoped patch).
4. A follow-up identical query now resolves via the grown taxonomy.

**The gap-detection signal has two OR'd conditions** in `agent_node`:
documents were retrieved but scored poorly even after a quality-gate
retry (`quality_gate_retried and max_relevance < threshold`), OR an
`attribute_filter` query's hard filter excluded everything on the very
first pass (`intent == "attribute_filter" and not retrieved_documents`).
The second condition exists because `quality_gate_node` deliberately
never retries a zero-document first pass (adjusting alpha can't fix an
exclusionary filter) — without it, the tool would never be offered for
exactly the scenario it exists to fix.

**Color and material trigger this differently in practice.** Color's
hard fallback filter, combined with color/brand being excluded from the
retriever's filter-relaxation safety net (below), reliably produces a
genuine zero-document result for an unrecognized term — this is provably
verified live. Material has two independent layers protecting against
ever returning zero documents (the soft `multi_match` fallback above, plus
filter relaxation), so no material term — however rare in the corpus —
reliably triggers the gap signal through natural conversation; growing
the material taxonomy is instead demonstrated via `POST
/api/admin/enrich` directly (see `docs/integration/rest-api.md`), which
exercises the identical `enrich_attribute` mechanism.

**Filter relaxation** (`main.py` retriever, pre-existing, unrelated to the
enrichment flywheel but load-bearing for the asymmetry above): when an
`attribute_filter`/`refinement` query's fully-filtered result count is
under 3, the retriever automatically retries without `multi_match`
filters (material, size) and keeps the relaxed results only if they
outnumber the original — `match` filters (color, brand) are never
relaxed, since the user named those explicitly. This is why a material
term with even zero corpus occurrences still returns results after
relaxation, while a color term does not.

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

### Adding a New Attribute Type (beyond color/material)

The detection stage and config generation are already generic — a third
type needs no new Java code and no hand-edited Lucille config:

1. Add a canonical seed vocabulary (`_CANONICAL_SEEDS_BY_TYPE` in
   `attribute_discovery.py`), then seed the taxonomy via
   `AttributeMappingStore.seed_from_discovery(...)` (or
   `bulk_discover` against real `chunk_text` for a from-scratch build).
   The next `lucille_ingest.sh` run picks it up automatically —
   `config_generator.py` queries OpenSearch for registered attribute
   types and emits a new `AttributeDetectorStage` block for it.
2. Add a filter block to `_extract_attributes()` in `main.py` for the new
   type — decide up front whether it needs color's hard-filter semantics
   (rare/exact terms) or material's soft-filter + relaxation semantics
   (see "Enrichment Flywheel" above); this is a deliberate per-type
   choice, not something to default to one or the other.
3. Add the new type's field to `vector_store.py`'s `_build_multi_match`
   boost list to give it BM25 scoring weight — not automatic (a
   deliberate, documented limitation to avoid an extra OpenSearch
   round-trip per query for two known types).
4. The `trigger_enrichment` tool and `/api/admin/enrich` already accept
   any `attribute_type` string — no changes needed there.

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
9. **Grows its own catalog taxonomy** — when it recognizes a real color/
   material gap, it can trigger a live reindex to teach the system a new
   term, not just adjust how it searches (see "Enrichment Flywheel")

Every stage is testable, extensible, and documented. The system is designed for e-commerce product discovery but generalizes to any RAG use case.
