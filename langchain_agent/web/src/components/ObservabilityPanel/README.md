# ObservabilityPanel

[← components](../) | [← web/src](../../)

Real-time visualization of the LangGraph RAG pipeline: event stream, per-node metrics, DSL query viewer, and quality gates.

## Files

| File | Purpose |
|------|---------|
| `index.tsx` | Container component exposing the full observability panel |
| `StepsList.tsx` | Linear timeline of pipeline nodes with collapse/expand |
| `StepCard.tsx` | Individual node card showing elapsed time + status |
| `EventCard.tsx` | Event detail view (raw JSON, formatted payload) |
| `PipelineSummaryCard.tsx` | NDCG/MRR/Recall metrics + lift-per-100ms (emitted after `agent_complete`) |
| `SearchOptimizationDetails.tsx` | Hybrid BM25 + Reranked comparison cards with lift indicators |
| `HistoricalSnapshotCard.tsx` | Checkpoint snapshot view (if saved to LangGraph) |
| `RawEventInspector.tsx` | Raw event JSON dump for debugging |
| `DslViewerModal.tsx` | Full OpenSearch DSL query display (hybrid / BM25 baseline / quality-gate retry) |

## Subdirectories

- `details/` — Per-event type detail renderers (RerankerDetails, QueryDetails, etc.)
- `__tests__/` — Vitest tests for all components

## Store Dependencies

- `observabilityStore` — event stream, step timeline, snapshots
- `chatStore` — current thread ID
- `optimizationsStore` — toggle display modes (show metrics, raw events, etc.)

## Key Concepts

**Event Flow:** WebSocket receives typed events → `observabilityStore.addEvent()` → components re-render with new timeline step.

**Snapshots:** On `agent_complete`, the pipeline summary emits per-stage metrics. Component falls back to confidence-proxy scoring when no judgments exist.

**DSL Viewer:** Opens modal with OpenSearch query body + filters. Embeddings scrubbed to `<EMBEDDING_OMITTED_768_DIMS>` for display.

**Metrics:** NDCG@10, MRR, Recall@20, Precision@10 computed server-side; lifted (reranked vs BM25) values shown as percentages.
