# Contributing — Extension Guide

This guide explains how to extend the Agentic Hybrid Search agent with new features. Follow these patterns to maintain consistency and avoid breaking existing functionality.

**Prerequisites**: Read `ARCHITECTURE.md` first to understand the pipeline, state management, and observable events.

---

## Adding a New Intent

**Scenario**: You want to add a new intent type (e.g., `product_alert` — "notify me when X is on sale").

### Step 1: Implement Keyword Patterns (Fast-Path)

In `main.py`, find `_build_intent_prompt()` docstring and intent list. Add your intent:

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

In `agent_state.py`, add fields for your node:

```python
class CustomAgentState(TypedDict, total=False):
    # ... existing fields ...
    
    # Sentiment Analysis
    user_sentiment_score: float  # 0.0–1.0 (0=negative, 0.5=neutral, 1.0=positive)
    sentiment_reasoning: str
```

### Step 2: Implement Node Function

In `main.py` (or dedicated file if large):

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

## Adding a New Content Format

**Scenario**: You want to add `podcast_script` format (1500-word conversational script for audio production).

### Step 1: Add Content Type to `config`

In `content_generators.py`, update `get_content_params()`:

```python
def get_content_params(content_type: str) -> dict:
    params_map = {
        # ... existing ...
        "podcast_script": {
            "target_length": 1500,
            "tone": "conversational",
            "retrieval_depth": 2,
            "temperature": 0.7,  # More creative than tutorial, less than blog
            "retrieval_k": 10,
            "retrieval_fetch_k": 40,
            "description": "Conversational podcast script with host/guest dialogue (~1500 words)",
        },
    }
    return params_map.get(content_type, params_map["comprehensive_docs"])
```

### Step 2: Implement Generator Function

In `content_generators.py`:

```python
async def generate_podcast_script(
    query: str,
    documents: List[Document],
    params: dict,
) -> Tuple[str, int, int]:
    """
    Generate a podcast script in conversational dialogue format.
    
    Args:
        query: Topic/title for the podcast episode
        documents: Retrieved product/topic documents
        params: Generation parameters from get_content_params()
    
    Returns:
        (script_content, word_count, character_count)
    """
    # Format documents for context
    doc_context = "\n---\n".join([
        f"Title: {doc.metadata.get('title', 'Untitled')}\n{doc.page_content[:500]}"
        for doc in documents[:5]
    ])
    
    prompt = f"""Write a podcast script for a 30-minute episode on "{query}".
Format as dialogue between Host and Guest. Include:
- Hook (first 2 minutes)
- Main discussion (20 minutes, 2-3 main points)
- Listener Q&A (5 minutes)
- Outro

Keep conversational tone, include transitions, and [SOUND_EFFECT] markers.

Context documents:
{doc_context}

Target: ~{params['target_length']} words"""
    
    content = ""
    async for chunk in self.llm.astream(prompt):
        content += chunk
        _emit_event_from_sync(
            PodcastProgressEvent(
                word_count=len(content.split()),
                character_count=len(content),
                progress_pct=(len(content) / (params['target_length'] * 6)) * 100,
            ),
            node="content_writer"
        )
    
    return content, len(content.split()), len(content)
```

### Step 3: Add to Content Type Classifier

In `main.py` content_writer node, add podcast_script routing:

```python
def _classify_content_type(query: str) -> str:
    """Classify user request to content format."""
    # ... existing ...
    
    podcast_patterns = [
        r'\b(podcast|audio|script|dialogue)\b',
        r'\b(record|episode|host|guest)\b',
    ]
    if any(re.search(pat, query, re.I) for pat in podcast_patterns):
        return "podcast_script"
    
    return "comprehensive_docs"  # fallback
```

### Step 4: Add Observable Event

In `api/schemas/events.py`:

```python
class PodcastProgressEvent(BaseModel):
    """Podcast script generation progress."""
    word_count: int = Field(description="Current word count")
    character_count: int = Field(description="Current character count")
    progress_pct: float = Field(ge=0, le=100, description="Estimated % complete")
    node: str = "content_writer"
```

In `web/src/types/events.ts`:

```typescript
interface PodcastProgressEvent extends BaseEvent {
  type: 'PodcastProgressEvent';
  word_count: number;
  character_count: number;
  progress_pct: number;
  node: 'content_writer';
}
```

### Step 5: Update Frontend

In `web/src/stores/observabilityStore.ts`:

```typescript
case 'PodcastProgressEvent':
  updateStep('content_writer', {
    word_count: event.word_count,
    progress: event.progress_pct / 100,
  });
  break;
```

In `web/src/components/ObservabilityPanel/StepCard.tsx`:

```tsx
nodeConfig.content_writer = {
  label: '✍️ Content Writer',
  // ... existing ...
  progressBar: step.progress,
  details: (step) => (
    <div className="text-sm">
      {step.word_count} words | {step.progress_pct?.toFixed(0)}% complete
    </div>
  ),
};
```

### Step 6: Test

```bash
# Unit test
PYTHONPATH=. pytest tests/unit/test_content_generators.py::test_podcast_script -v

# Manual
./scripts/start.sh
# → "Write a podcast script about wireless headphones"
# → Verify PodcastProgressEvent emitted in observability panel
```

---

## Swapping the LLM Provider

**Scenario**: Replace Google Gemini with OpenAI GPT-4o.

### Step 1: Update Dependencies

```bash
pip install openai
# (or update pyproject.toml, requirements.txt)
```

### Step 2: Update config.py

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

In `vector_store.py`:

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

In `reranker.py`:

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

In `main.py`, wrap node functions with timing:

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
CLOUD_RUN_URL=https://... API_KEY=... PYTHONPATH=. pytest tests/e2e/ -v
```

Test against deployed Cloud Run instance.

### Manual Testing Checklist

- [ ] Trigger new intent with test query
- [ ] Verify correct α assigned and retrieved results improve
- [ ] Check observable events appear in frontend panel
- [ ] Verify new node outputs are persisted in PostgreSQL checkpoint
- [ ] Test error cases (missing documents, LLM timeout, etc.)
- [ ] Run `make lint`, `make type-check` to catch regressions

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
PYTHONPATH=. python ingest_esci_products.py
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
3. Run `make lint` and `make type-check`
4. Write unit/integration tests
5. Create pull request with description
6. Request review (especially for new nodes/events)
7. Address feedback, retest
8. Merge to `main` → auto-deploy to Cloud Run via GitHub Actions

---

## Getting Help

- **Architecture questions**: Read `ARCHITECTURE.md`, check docstrings
- **LangGraph questions**: Consult [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- **Debugging**: Enable `LANGSMITH_API_KEY` for tracing at <https://smith.langchain.com>
- **Tests failing**: Check `tests/README.md` for test-specific guidance
