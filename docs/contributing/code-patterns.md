# Code Patterns

Essential patterns and conventions for contributing to Agentic Hybrid Search.

**Parent:** [Contributing Guide](README.md)

---

## PYTHONPATH Requirement

All Python invocations from `langchain_agent/` must set `PYTHONPATH=.`:

```bash
# ✓ Correct
PYTHONPATH=. pytest tests/unit/
PYTHONPATH=. python main.py
PYTHONPATH=. black .

# ✗ Wrong — will fail with ModuleNotFoundError
pytest tests/unit/
python main.py
```

**Why:** Modules use bare imports like `from config import ...` instead of relative imports. Setting `PYTHONPATH=.` allows Python to resolve `config` as a module in the current directory.

**Set once per session:**
```bash
export PYTHONPATH=.
pytest tests/unit/
python main.py
```

---

## State Access

`CustomAgentState` is a `TypedDict` with `total=False`. Only `messages` is guaranteed to exist. Always use `.get()` with a default:

```python
# ✓ Correct
intent = state.get("intent")
confidence = state.get("confidence", 0.5)
alpha = state.get("alpha", 0.25)

# ✗ Wrong — KeyError if field doesn't exist
intent = state["intent"]
```

### State Fields by Pipeline Node

| Node | Adds |
|------|------|
| intent_classifier | `intent`, `confidence`, `user_query` |
| query_evaluator | `alpha`, `intent_description` |
| retriever | `retrieved_documents`, `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms` |
| reranker | `reranker_max_score`, `reranked_documents`, `reranker_latency_ms` |
| quality_gate | `quality_gate_retried`, `alpha_adjusted_value`, `quality_gate_threshold_used` |
| agent | `citations` (must be present in all return paths) |

**Example:**
```python
async def agent_node(state: CustomAgentState):
    intent = state.get("intent", "search")
    confidence = state.get("confidence", 0.5)
    retrieved_docs = state.get("retrieved_documents", [])
    
    # Do work...
    
    return {
        "citations": [...]  # Required: all paths must return citations
    }
```

---

## Exception Hierarchy

All custom exceptions inherit from `AgenticHybridSearchError` (defined in `exceptions.py`). Never catch bare `Exception`.

```python
from exceptions import (
    AgenticHybridSearchError,
    SearchTimeoutError,
    DocumentRetrievalError,
)

# ✓ Correct
try:
    results = retriever.search(query, timeout=5)
except SearchTimeoutError as e:
    logger.warning("Search timed out after 5s", exc_info=True)
    # Decide: retry with longer timeout, or fail
except DocumentRetrievalError as e:
    if e.recoverable:
        # Retry with fallback strategy
    else:
        # Don't retry; propagate
        raise
except AgenticHybridSearchError as e:
    # Catch-all for any other custom exception
    logger.error(f"Search failed: {e}")
    raise

# ✗ Wrong — silently hides bugs
except Exception:
    pass
```

### Exception Attributes

All `AgenticHybridSearchError` subclasses support:
- `recoverable: bool` — whether to retry the operation
- `message: str` — human-readable message
- `details: dict` — structured context (e.g., `{"timeout_ms": 5000, "query": "..."}`)

```python
try:
    evaluate_intent(query)
except SearchTimeoutError as e:
    if e.recoverable:
        logger.warning(f"Timeout ({e.details.get('timeout_ms')}ms), retrying...")
        # Retry
    else:
        raise
```

---

## LLM Content Blocks

Gemini returns list-of-content-blocks for certain fields. Use `_flatten_llm_content()` to convert to string:

```python
from main import _flatten_llm_content

# Gemini returns: [{"text": "Hello"}, {"text": " world"}]
response = llm.generate(prompt)
text = _flatten_llm_content(response)  # "Hello world"
```

**When to use:** Whenever you extract a string field from an LLM response (summarize, classify, extract).

---

## Event Parity

Backend events in `api/schemas/events.py` must match frontend types in `web/src/types/events.ts`.

### Rules

1. Every `event["type"]` literal in `api/schemas/events.py` must exist in the frontend enum
2. Every field in a backend event Pydantic model must exist in the frontend type
3. The `node` field must be identical on both sides

**Verification:**
```bash
PYTHONPATH=. pytest tests/unit/test_frontend_backend_event_parity.py -v
```

This test is run automatically in `make ci`.

### Example

**Backend (Python):**
```python
class SearchProgressEvent(BaseEvent):
    type: Literal["search_progress"]
    node: Literal["intent_classifier"]
    intent: str
    confidence: float
```

**Frontend (TypeScript):**
```typescript
type SearchProgressEvent = BaseEvent & {
  type: "search_progress";
  node: "intent_classifier";
  intent: string;
  confidence: number;
};
```

Both must match exactly. If you add a field to the backend, add it to the frontend too.

---

## Auth Patterns

Never wire new routes through the legacy `verify_api_key` middleware. It's dead code.

**✓ Correct:**
```python
from api.middleware.session_auth import verify_session
from api.middleware.origin_auth import verify_same_origin

@app.get("/api/conversations")
async def list_conversations(request: Request):
    verify_same_origin(request)
    verify_session(request)
    # Continue
```

**✗ Wrong:**
```python
from api.middleware.auth import verify_api_key  # Dead code

@app.get("/api/conversations")
async def list_conversations(request: Request):
    verify_api_key(request)  # This doesn't work; use verify_session
```

### Two-Layer Auth

1. **Same-origin check** (`verify_same_origin`) — validates Origin header against allow-list
2. **Session or admin token** (`verify_session` or `verify_admin_token`) — validates authentication credential

Both must pass for protected routes.

---

## Logging

Use structured logging via `logger` (from `logging_config.py`):

```python
import logging
logger = logging.getLogger(__name__)

# ✓ Correct
logger.warning("Search timed out", extra={"query": query, "timeout_ms": 5000})
logger.error("Database connection failed", exc_info=True)

# ✗ Wrong
print("Search timed out")  # No structure, lost in production
logger.warning(f"Timeout: {query}")  # Brittle string formatting
```

Log levels:
- `DEBUG` — verbose (function entry, state changes)
- `INFO` — milestone (request started, pipeline completed)
- `WARNING` — recoverable error (timeout, retry attempt)
- `ERROR` — unrecoverable error (database down, auth failed)

---

## Comments

Write comments for **why**, not **what**. Code should be self-documenting.

```python
# ✓ Correct — explains the non-obvious reasoning
# Gemini returns list-of-content-blocks; flatten to string for state
text = _flatten_llm_content(llm_response)

# ✗ Wrong — just repeats what the code does
# Flatten the LLM response
text = _flatten_llm_content(llm_response)

# ✗ Wrong — don't reference the current task
# Added for issue #42 — fix citations missing
return {"citations": [...]}
```

No docstrings for internal functions. Only add them for public APIs.

---

## No Over-Engineering

Don't add error handling, fallbacks, or abstractions for scenarios that can't happen. Trust internal code and framework guarantees.

```python
# ✓ Correct — only validate at system boundaries
query = request.json["message"]  # Validate user input
if not query:
    raise ValueError("Message required")

# But don't validate internally
alpha = state.get("alpha")  # Trust that retriever set it
# No need to check: if not isinstance(alpha, float)

# ✗ Wrong — over-protective
alpha = state.get("alpha")
if not isinstance(alpha, float):
    alpha = 0.25  # Unnecessary fallback
```

---

## Testing Patterns

See [Testing](testing.md) for the test pyramid. Key patterns:

- Unit tests: no external deps, fast, use mocks
- Integration tests: real PostgreSQL + OpenSearch, slower
- E2E tests: full system, deployed Cloud Run
- Smoke tests: regression suite before push

```python
# Unit test (fast, mocked)
def test_intent_classifier():
    result = classify_intent("Find wireless headphones")
    assert result["intent"] == "search"

# Integration test (real DB)
async def test_retriever_with_opensearch():
    # Uses real OpenSearch connection from conftest
    results = await retriever.search("wireless headphones")
    assert len(results) > 0

# E2E test (full system)
async def test_chat_end_to_end():
    # Uses live Cloud Run service
    response = await send_chat_message("wireless headphones")
    assert "headphones" in response["citations"][0]["title"]
```

---

For testing strategy, see [Testing](testing.md). For the PR process, see [PR Process](pr-process.md).
