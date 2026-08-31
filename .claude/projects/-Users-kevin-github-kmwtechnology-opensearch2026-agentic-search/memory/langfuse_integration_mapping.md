---
name: langfuse_integration_mapping
description: Agent graph structure, instrumentation points per node, Langfuse deployment options, Phase 1-3 roadmap
metadata:
  type: reference
---

# Langfuse Integration Mapping — Agent Graph & Instrumentation Points

## 1. Agent Graph Structure

The application uses **LangGraph StateGraph** with these 8 nodes:

```
intent_classifier 
    ↓ (reads messages)
query_evaluator 
    ↓ (reads user_query)
[summary, retriever, reranker, quality_gate] (parallel/sequential mix)
    ↓
agent 
    ↓
llm_judge (optional, post-agent)
    ↓
END
```

### Node Responsibilities & Instrumentation Points

| Node | Inputs | Outputs | LLM Calls | Latency | Cost Tracking |
|------|--------|---------|-----------|---------|---------------|
| **intent_classifier** | `messages` | `intent`, `confidence`, `user_query`, `reasoning` | 1× Gemini 3.1 Flash Lite (fast-path keyword match or LLM fallback) | 50-200ms | Classification tokens |
| **query_evaluator** | `user_query` | `alpha` (0.0-1.0), `query_analysis`, `query_evaluation_reason` | 0-1× Gemini 3.1 Flash Lite (depends on intent) | 50-200ms | Evaluation tokens (if called) |
| **retriever** | `user_query`, `alpha`, `optimizations` | `retrieved_documents`, `pre_rerank_documents`, `bm25_documents`, `stock_bm25_documents`, `bm25_latency_ms`, `retriever_latency_ms`, `judgments` | 0× (pure vector + BM25 via RRF fusion) | 100-500ms | Vector DB calls, BM25 calls |
| **reranker** | `retrieved_documents`, `user_query` | `reranked_documents`, `all_reranked_documents`, `reranker_max_score`, `reranker_latency_ms` | 1× Gemini 3.1 Flash Lite (cross-encoder scoring, batch) | 200-800ms | Reranking tokens |
| **quality_gate** | `reranker_max_score`, intent-specific thresholds | `quality_gate_retried`, `alpha_adjusted_value`, `quality_gate_reason`, may trigger retriever retry | 0× (pure logic) | <10ms | N/A |
| **summary** | All state fields | `summary_text` | 0× (if toggled off, just aggregates) | 0-100ms | Summary tokens (if LLM) |
| **agent** | `reranked_documents`, `messages`, full state | `AIMessage` with citations, `hallucination_retry_used=False` (reset) | 1× Gemini 3 Flash (generation, streaming) | 500ms-2s | Generation tokens (streaming) |
| **llm_judge** | `AIMessage`, state | `judgment` (hallucination flags), `corrected_response` (if auto-corrected) | 1× Gemini 3.1 Flash Lite (classification) | 200-400ms | Judge tokens (if retry triggered) |

---

## 2. Current Telemetry Infrastructure

### Structured Logging (structlog)
- **File**: `logging_config.py`
- **Setup**: JSON or console output, context variables (request_id, thread_id)
- **Limitation**: Logs are fire-and-forget, no trace aggregation or query-level correlation
- **Used in**: All nodes via `logger.info()`, error tracking via exceptions

### WebSocket Events (Real-Time Streaming)
- **File**: `api/schemas/events.py`
- **Status**: Fully defined Pydantic event types (NodeStartEvent, IntentClassificationEvent, etc.)
- **Limitation**: Events emitted to frontend only; no persistent storage or trace analysis

### LangSmith Integration (Stub)
- **File**: `config.py` (lines 516-523)
- **Status**: Optional via `LANGSMITH_API_KEY` env var
- **Current State**: Only sets tracing flag, no actual instrumentation in nodes

---

## 3. Langfuse Integration Strategy

### A. Self-Hosted Deployment (GCP)

**Architecture Options:**

1. **Option 1: Cloud Run + Cloud SQL** (Recommended for simplicity)
   - Deploy Langfuse Docker image to Cloud Run
   - Use Cloud SQL PostgreSQL for traces
   - Accessible via HTTPS with IAM/API key auth
   - Both local dev & production connect to same instance

2. **Option 2: GKE Deployment**
   - More complex but scales better
   - Use GKE workload identity for auth
   - PostgreSQL via Cloud SQL

3. **Option 3: Local Docker + GCP Bridge**
   - Langfuse in local Docker container
   - For local dev only; production uses Cloud Run

**Recommended: Option 1** (balance of simplicity & scalability)

### B. Python SDK Integration Points

**Core Flow:**

```python
from langfuse import Langfuse
from langfuse.decorators import observe

# Initialize at app startup
langfuse_client = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),  # GCP Cloud Run URL or local
)

# Decorate agent class OR individual nodes
class EcommerceSearchAgent:
    @observe(name="intent_classifier", input_keys=["messages"])
    def intent_classifier_node(self, state):
        # Automatic: traces input, output, latency, LLM tokens
        # Manual: add cost, custom metrics
        ...
```

**Alternative: Callback Handler Approach** (more control, lower overhead)

```python
# Hook into LangGraph's callback system
class LangfuseTraceCallback:
    def on_node_start(self, node_name, input):
        self.trace = langfuse_client.trace(name=node_name)
        self.span = self.trace.span(...)
    
    def on_node_end(self, node_name, output, latency):
        self.span.end(output=output)
```

### C. Cost Attribution Per Node

**Token Counting:**
- **Intent Classifier**: ~50-200 tokens (classification only)
- **Query Evaluator**: ~50-150 tokens (if LLM call made)
- **Reranker**: ~500-1000 tokens (batch reranking, N documents × N tokens/doc)
- **Agent**: ~1000-3000 tokens (generation + streaming)
- **LLM Judge**: ~100-300 tokens (if hallucination detected)

---

## 4. Phase 1-3 Roadmap

### Phase 1: Minimal Setup (3 days)
- Deploy Langfuse to GCP Cloud Run via Terraform module
- Add callback handler to agent graph
- Wire environment variables
- **Deliverable**: Execution graphs visible in Langfuse UI

### Phase 2: Node-Level Instrumentation (5 days)
- Decorate each of 8 nodes individually
- Custom cost tracking per LLM call + per DB call
- Latency breakdown (bm25, vector, reranker, etc.)
- Build custom cost/latency dashboard
- **Deliverable**: Per-node cost attribution + latency visibility

### Phase 3: Evaluation Loop (1 week)
- Annotation Queues for human evaluation
- LLM-as-Judge hallucination detection (5-10% sampling)
- Link to ESCI ground-truth judgments
- Code evaluator for citation validation
- **Deliverable**: Human annotation loop active, evals feed to quality gate

---

## 5. Environment Variables & Config

### New Langfuse Config (config.py additions)

```python
# Langfuse self-hosted credentials
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3000")  # GCP Cloud Run URL in prod

# Trace sampling (% of requests to trace)
LANGFUSE_SAMPLE_RATE = float(os.getenv("LANGFUSE_SAMPLE_RATE", "1.0"))

# Which nodes to trace
LANGFUSE_TRACE_NODES = os.getenv("LANGFUSE_TRACE_NODES", "all").split(",")  # or "classifier,retriever,agent"
```

---

## 6. Files to Modify / Create

### Modifications
1. **`config.py`** — Add Langfuse env vars
2. **`main.py`** — Add Langfuse client init, integrate callback handler
3. **`api/main.py`** — Register Langfuse client in FastAPI startup
4. **`.env.example`** — Document new env vars

### New Files (Phase 2+)
1. **`langfuse_integration.py`** — LangfuseClient wrapper, decorators, cost calculation
2. **`langfuse_utils.py`** — Token counting, trace sampling, batch event publishing
3. **`docker-compose.langfuse.yml`** — Local dev Langfuse + PostgreSQL (optional)
