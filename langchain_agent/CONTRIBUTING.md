# Contributing — Extension Guide

This guide explains how to extend the Agentic Hybrid Search agent with new features. Follow these patterns to maintain consistency and avoid breaking existing functionality.

**Prerequisites**: Read `ARCHITECTURE.md` first to understand the pipeline, state management, and observable events.

---

## Adding a New Intent

**Scenario**: You want to add a new intent type (e.g., `product_alert` — "notify me when X is on sale").

### Step 1: Implement Keyword Patterns (Fast-Path)

In `pipeline/pipeline_nodes.py`, find `_build_intent_prompt()` docstring and intent list. Add your intent:

```python
# In intent_classifier_node docstring and _build_intent_prompt()
INTENTS = [
    "search",
    "comparison",
    "attribute_filter",
    "refinement",
    "follow_up",
    "summary",
    "product_alert",  # NEW
]

# In _classify_intent_keyword_fastpath()
def _classify_intent_keyword_fastpath(query: str) -> tuple[str, float, bool]:
    """
    Fast keyword-based intent classification.
    """
    # ... existing intents ...
    
    # NEW: product_alert
    product_alert_patterns = [
        r'\b(notify|alert|remind|tell)\b.*\b(when|if|cheaper|sale|stock|available)',
        r'\b(set.*alert|create.*notification)\b',
    ]
    if any(re.search(pat, query, re.I) for pat in product_alert_patterns):
        return ("product_alert", 0.95, True)  # High confidence, found pattern
    
    # ... rest of fallback ...
```

### Step 2: Update Query Evaluator Fast-Path

In `query_evaluator_node()`, add default α for the new intent:

```python
# In query_evaluator_node()
INTENT_ALPHA_DEFAULTS = {
    "comparison": 0.60,
    "attribute_filter": 0.25,
    "refinement": 0.35,
    "product_alert": 0.4,  # NEW: balanced (exact product + concept)
}
```

### Step 3: Add Graph Edge

In `build_graph()`, add conditional edge if needed:

```python
# If product_alert needs special routing (e.g., to a notification service):
def route_product_alert(state: CustomAgentState) -> str:
    if state.get("intent") == "product_alert":
        return "alert_setup_node"  # custom node
    return "retriever"

graph.add_conditional_edges("query_evaluator", route_product_alert)
```

### Step 4: Add Tests

Create `tests/unit/intent/test_intent_classifier.py` test case:

```python
def test_product_alert_keyword_fast_path():
    """Product alert should classify on keyword pattern."""
    intent, conf, found = _classify_intent_keyword_fastpath("notify me when headphones go on sale")
    assert intent == "product_alert"
    assert conf > 0.9
    assert found is True

def test_product_alert_llm_fallback():
    """LLM should classify product_alert even without exact keywords."""
    intent, conf = _classify_intent_llm("let me know if this gets cheaper")
    assert intent == "product_alert"
```

### Step 5: Update Documentation

- Add to `main.py` docstring: intent definitions
- Add to `ARCHITECTURE.md` Intent Classifier section
- Update `README.md` Example Queries with product_alert example

---

## Adding a New Pipeline Node

**Scenario**: You want to add a `sentiment_analyzer` node that scores user satisfaction (0–1) and stores it for future personalization.

### Step 1: Define State Fields

In `core/agent_state.py`, add fields for your node:

```python
class CustomAgentState(TypedDict, total=False):
    # ... existing fields ...
    
    # Sentiment Analysis
    user_sentiment_score: float  # 0.0–1.0 (0=negative, 0.5=neutral, 1.0=positive)
    sentiment_reasoning: str
```

### Step 2: Implement Node Function

In `pipeline/pipeline_nodes.py` (`PipelineNodesMixin`; graph wiring stays in `main.py`):

```python
async def sentiment_analyzer_node(state: CustomAgentState) -> Dict[str, Any]:
    """
    Analyze user sentiment from last message.
    
    Reads the most recent user message and scores satisfaction (0.0–1.0).
    Stores score for personalization and feedback loops.
    
    Args:
        state: Agent state with messages
        
    Returns:
        Dictionary with user_sentiment_score and sentiment_reasoning
    """
    messages = state.get("messages", [])
    if not messages:
        return {"user_sentiment_score": 0.5, "sentiment_reasoning": "no messages"}
    
    last_user_msg = messages[-2].content if len(messages) >= 2 else ""
    
    prompt = f"""Rate user satisfaction in the last message (0.0–1.0):
0.0 = very dissatisfied, frustrated
0.5 = neutral, no strong opinion
1.0 = very satisfied, happy

Message: {last_user_msg}

Return JSON: {{"score": 0.8, "reasoning": "..."}}"""
    
    result = self.sentiment_llm.invoke(prompt)
    
    _emit_event_from_sync(
        SentimentAnalysisEvent(
            score=result["score"],
            reasoning=result["reasoning"],
            timestamp=time.time()
        ),
        node="sentiment_analyzer"
    )
    
    return {
        "user_sentiment_score": result["score"],
        "sentiment_reasoning": result["reasoning"]
    }
```

### Step 3: Wire into Graph

In `build_graph()`:

```python
graph.add_node("sentiment_analyzer", sentiment_analyzer_node)

# After agent completes, analyze sentiment
graph.add_edge("agent", "sentiment_analyzer")
# Note: no outgoing edges (sentiment_analyzer is terminal)
```

### Step 4: Add Observable Event

In `api/schemas/events.py`:

```python
from pydantic import BaseModel, Field

class SentimentAnalysisEvent(BaseModel):
    """User sentiment analysis complete."""
    score: float = Field(ge=0.0, le=1.0, description="User satisfaction (0–1)")
    reasoning: str = Field(description="Why this score")
    timestamp: float = Field(description="Unix timestamp")
    node: str = "sentiment_analyzer"
```

In `web/src/types/events.ts`:

```typescript
interface SentimentAnalysisEvent extends BaseEvent {
  type: 'SentimentAnalysisEvent';
  score: number;
  reasoning: string;
  timestamp: number;
  node: 'sentiment_analyzer';
}
```

### Step 5: Update Frontend Store

In `web/src/stores/observabilityStore.ts`:

```typescript
case 'SentimentAnalysisEvent':
  addStep({
    id: 'sentiment_analyzer',
    name: 'Sentiment Analysis',
    status: 'complete',
    sentiment_score: event.score,
    reasoning: event.reasoning,
  });
  break;
```

### Step 6: Add UI Rendering

In `web/src/components/ObservabilityPanel/StepCard.tsx`:

```tsx
const nodeConfig: Record<string, StepConfig> = {
  // ... existing ...
  sentiment_analyzer: {
    label: '💭 Sentiment',
    bgColor: 'bg-purple-500/20 border-purple-500/50',
    details: (step) => (
      <div className="text-sm">
        <p>Score: {(step.sentiment_score * 100).toFixed(0)}%</p>
        <p className="text-gray-300">{step.reasoning}</p>
      </div>
    ),
  },
};
```

### Step 7: Test

```bash
# Unit test (mocked sentiment LLM)
PYTHONPATH=. pytest tests/unit/test_sentiment_analyzer.py -v

# Integration test (real LLM)
PYTHONPATH=. pytest tests/integration/test_sentiment_analyzer.py -v

# Manual: check observability panel for sentiment step
./scripts/start.sh
# → http://localhost:5173, send message, verify sentiment card appears
```

---

## Swapping the LLM Provider

**Scenario**: Replace Google Gemini with OpenAI GPT-4o.

### Step 1: Update Dependencies

```bash
pip install openai
# (or update pyproject.toml, requirements.txt)
```

### Step 2: Update core/config.py

```python
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google")  # NEW
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")  # Changed from gemini
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-small")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "gpt-4o-mini")
QUERY_EVAL_MODEL = os.getenv("QUERY_EVAL_MODEL", "gpt-4o-mini")
```

### Step 3: Update main.py

```python
# At top of file, conditional import
if config.LLM_PROVIDER == "google":
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(model=config.LLM_MODEL, temperature=0)
elif config.LLM_PROVIDER == "openai":
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model=config.LLM_MODEL, temperature=0)
else:
    raise ValueError(f"Unsupported LLM provider: {config.LLM_PROVIDER}")
```

### Step 4: Update embeddings

In `retrieval/vector_store.py`:

```python
from langchain_openai import OpenAIEmbeddings

if config.EMBEDDINGS_MODEL.startswith("text-embedding"):
    embeddings = OpenAIEmbeddings(model=config.EMBEDDINGS_MODEL)
else:
    # Fallback to Gemini
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    embeddings = GoogleGenerativeAIEmbeddings(model=config.EMBEDDINGS_MODEL)
```

### Step 5: Update reranker

In `retrieval/reranker.py`:

```python
from langchain_openai import ChatOpenAI

class GeminiReranker:
    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model_name = model_name
        # Switch from ChatGoogleGenerativeAI
        self.llm = ChatOpenAI(model=model_name, temperature=0)
```

### Step 6: Test

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
PYTHONPATH=. pytest tests/unit/test_intent_classifier.py -v
PYTHONPATH=. python3 setup.py  # Validate API connection
```

---

## Adding a New Attribute Type (beyond color/material)

**Scenario**: Add a third detected/filterable product attribute (e.g. `size`,
`pattern`) to the taxonomy-driven attribute detection + enrichment flywheel.

The detection stage and Lucille config generation are already generic —
this needs **no new Java code and no hand-edited pipeline config**:

### Step 1: Seed the taxonomy

Add a canonical seed vocabulary entry to `_CANONICAL_SEEDS_BY_TYPE` in
`retrieval/attribute_discovery.py`, then seed it into OpenSearch — either
`AttributeMappingStore.seed_from_discovery(...)` for a small hand-curated
set, or `bulk_discover(...)` against real `chunk_text` for a from-scratch
build (see `scripts/rebuild_attribute_taxonomies.py` for the pattern).
For color and material specifically this is already wired end-to-end:
`make seed-taxonomy` locally, or the `seed_taxonomy` input on the
`Re-Index OpenSearch` workflow for the hosted cluster, runs discovery
between two products passes (`lucille_ingest.sh --seed-taxonomy`).
Extend `rebuild_attribute_taxonomies.py` with the new type's canonicals
if it should be part of that seed.

### Step 2: Wire query-time filtering

Add a filter block to `_extract_attributes()` in `pipeline/pipeline_nodes.py` for the new
type. Decide up front whether it needs a **hard** exact-match fallback
(like color — reliable, but excludes non-taxonomy terms outright) or a
**soft** lexical `multi_match` fallback (like material — protects
legitimate non-taxonomy words, but subject to filter relaxation and can't
reliably drive a live-conversation enrichment trigger). This is a
deliberate per-type design choice — see `ARCHITECTURE.md`'s "Enrichment
Flywheel" section for why color and material differ here.

### Step 3: Add BM25 scoring weight

Add the new field to `retrieval/vector_store.py`'s `_build_multi_match` boost list.
Not automatic — a documented tradeoff to avoid an extra OpenSearch
round-trip per query for a small, known set of attribute types.

### Step 4: Test

```bash
PYTHONPATH=. pytest tests/unit/test_attribute_discovery.py -v
PYTHONPATH=. pytest tests/integration/test_config_generator_live.py -v
bash scripts/lucille_ingest.sh --skip-judgments   # confirm the new
                                                    # detectX stage appears
                                                    # in products.generated.conf
```

The `trigger_enrichment` tool and `POST /api/admin/enrich` already accept
any `attribute_type` string — no changes needed there.

---

## Adding an Observable Event

**Scenario**: Add real-time latency tracking for each node.

### Step 1: Define Event in Backend

In `api/schemas/events.py`:

```python
class NodeLatencyEvent(BaseModel):
    """Latency of a pipeline node."""
    node: str = Field(description="Node name")
    latency_ms: float = Field(ge=0, description="Execution time in milliseconds")
    timestamp: float = Field(description="Unix timestamp")
```

### Step 2: Define Event in Frontend

In `web/src/types/events.ts`:

```typescript
interface NodeLatencyEvent extends BaseEvent {
  type: 'NodeLatencyEvent';
  node: string;
  latency_ms: number;
  timestamp: number;
}
```

### Step 3: Emit from Nodes

In `pipeline/pipeline_nodes.py`, wrap node functions with timing:

```python
async def timed_node(node_func, state):
    start = time.time()
    result = await node_func(state)
    elapsed_ms = (time.time() - start) * 1000
    _emit_event_from_sync(
        NodeLatencyEvent(
            node=node_func.__name__,
            latency_ms=elapsed_ms,
            timestamp=start
        ),
        node=node_func.__name__
    )
    return result
```

### Step 4: Accumulate in Frontend Store

In `web/src/stores/observabilityStore.ts`:

```typescript
case 'NodeLatencyEvent':
  // Store latency for analytics/display
  observabilityState.latencies[event.node] = event.latency_ms;
  break;
```

### Step 5: Visualize

In ObservabilityPanel, add latency badge to each step:

```tsx
<span className="text-xs text-gray-400">
  {step.latency_ms}ms
</span>
```

---

## Testing Your Changes

### Unit Tests (No External Services)

```bash
PYTHONPATH=. pytest tests/unit/ -v
```

Good for testing nodes in isolation, mocked LLM/vector DB.

### Integration Tests (Postgres + OpenSearch Required)

```bash
docker compose up -d
PYTHONPATH=. pytest tests/integration/ -v
```

Tests nodes together with real services.

### E2E Tests (Full System)

```bash
PYTHONPATH=. pytest tests/e2e/ -v
```

Test against a running local backend (`CLOUD_RUN_URL` env var, despite the
name, just points at whatever backend URL you're testing; defaults to
`http://localhost:8000`).

### Manual Testing Checklist

- [ ] Trigger new intent with test query
- [ ] Verify correct α assigned and retrieved results improve
- [ ] Check observable events appear in frontend panel
- [ ] Verify new node outputs are persisted in PostgreSQL checkpoint
- [ ] Test error cases (missing documents, LLM timeout, etc.)
- [ ] Run `make lint` (includes flake8 + mypy) to catch regressions

---

## Code Style & Best Practices

### Naming Conventions

- **Nodes**: snake_case, end with `_node` (e.g., `sentiment_analyzer_node`)
- **Events**: PascalCase, end with `Event` (e.g., `SentimentAnalysisEvent`)
- **State fields**: snake_case (e.g., `user_sentiment_score`)

### Docstring Requirements

Every public function must have:

- One-line summary (what it does)
- **Args** section with types and descriptions
- **Returns** section with return type and description
- **Raises** section if exceptions are raised
- **Example** code block showing typical usage

### Structured Logging

Use structlog for JSON logging:

```python
logger.info(
    "node_complete",
    node="sentiment_analyzer",
    latency_ms=125.3,
    state_updated=["user_sentiment_score"]
)
```

### Type Hints

Always use type hints:

```python
async def my_node(state: CustomAgentState) -> Dict[str, Any]:
    ...
```

### Avoid Breaking Changes

When modifying:

- **State fields**: Add optional fields (never remove)
- **Event schemas**: Add fields with defaults, never remove
- **API routes**: Versioning (`/v1/chat`, `/v2/chat`)
- **Config variables**: Provide defaults, announce deprecations

---

## Troubleshooting

### Import Errors

```text
ModuleNotFoundError: No module named 'config'
```

Always set `PYTHONPATH=.` when running scripts:

```bash
bash scripts/lucille_ingest.sh
PYTHONPATH=. pytest tests/
```

### WebSocket Event Deserialization Fails

Symptom: Frontend shows `TypeError: Cannot read property 'node' of undefined`

**Fix**: Ensure event schema in `api/schemas/events.py` matches TypeScript type in `web/src/types/events.ts`. Check field names, types, and required/optional status.

### Node Hangs or Times Out

Symptom: Agent stalls after a certain node

**Fix**:

1. Check `QUERY_EVAL_TIMEOUT_MS`, `LINK_VERIFICATION_TIMEOUT_MS` in config
2. Add `asyncio.timeout()` to long-running operations
3. Use LangSmith tracing to profile which node is slow
4. Consider async/parallel execution if multiple independent operations

### Quality Gate Infinite Retry

Symptom: Quality gate keeps retrying, never reaches agent

**Fix**: Quality gate has max 1 retry. If still seeing issues:

1. Check `QUALITY_GATE_THRESHOLD` (default 0.50) — may be too strict
2. Verify reranker is returning sensible scores (not all 0.0 or 1.0)
3. Try adjusting α bounds in quality gate retry logic

---

## Contribution Workflow

1. Fork the repo (or create a feature branch)
2. Make changes, test locally
3. Run `make lint` (includes flake8 + mypy)
4. Write unit/integration tests
5. Create pull request with description
6. Request review (especially for new nodes/events)
7. Address feedback, retest
8. Merge to `main` — local-only demo, no deploy step

---

## Getting Help

- **Architecture questions**: Read `ARCHITECTURE.md`, check docstrings
- **LangGraph questions**: Consult [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- **Debugging**: Enable `LANGSMITH_API_KEY` for tracing at <https://smith.langchain.com>
- **Tests failing**: Check `tests/README.md` for test-specific guidance
