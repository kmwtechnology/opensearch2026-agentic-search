import { useObservabilityStore } from '../../stores/observabilityStore'

const formatLatency = (ms: number | undefined): string => {
  if (ms === undefined || ms === null) return '—'
  return `${ms.toFixed(0)} ms`
}

const formatNumber = (n: number | null | undefined, digits = 2): string => {
  if (n === null || n === undefined) return '—'
  return n.toFixed(digits)
}

export function HistoricalSnapshotCard() {
  const { historicalSnapshot, isExecuting, steps } = useObservabilityStore()

  // Only render when we have snapshot data AND the panel isn't actively
  // streaming a fresh run. Live execution always wins.
  if (!historicalSnapshot || !historicalSnapshot.has_data || isExecuting || steps.length > 0) {
    return null
  }

  const s = historicalSnapshot
  const lat = s.latency || {}

  return (
    <div className="px-4">
      <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-[1.375rem] font-semibold text-[var(--color-stage-ink)]">Last Run Snapshot</h3>
          <span className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">from checkpoint</span>
        </div>

        {s.user_query && (
          <div>
            <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)] mb-1">Query</div>
            <div className="text-[1.375rem] text-[var(--color-stage-ink)]">{s.user_query}</div>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-[1.375rem]">
          {s.intent && (
            <div>
              <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)]">Intent</div>
              <div className="text-[var(--color-stage-ink)]">
                {s.intent}
                {s.intent_confidence !== null && (
                  <span className="text-[var(--color-stage-ink-soft)] ml-2">
                    ({(s.intent_confidence * 100).toFixed(0)}%)
                  </span>
                )}
              </div>
            </div>
          )}
          {s.alpha !== null && (
            <div>
              <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)]">Alpha</div>
              <div className="text-[var(--color-stage-ink)]">{formatNumber(s.alpha, 2)}</div>
            </div>
          )}
          {s.reranker_max_score !== null && (
            <div>
              <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)]">Reranker Max</div>
              <div className="text-[var(--color-stage-ink)]">{formatNumber(s.reranker_max_score, 3)}</div>
            </div>
          )}
          {s.quality_gate_retried !== null && (
            <div>
              <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)]">Quality Gate</div>
              <div className="text-[var(--color-stage-ink)]">
                {s.quality_gate_retried ? 'Retried' : 'Passed'}
              </div>
            </div>
          )}
        </div>

        {s.query_analysis && (
          <div>
            <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)] mb-1">Analysis</div>
            <div className="text-[1.25rem] text-[var(--color-stage-ink)] leading-relaxed">{s.query_analysis}</div>
          </div>
        )}

        {Object.keys(lat).length > 0 && (
          <div>
            <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)] mb-1">Latency</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-[1.25rem] text-[var(--color-stage-ink)]">
              {lat.bm25_latency_ms !== undefined && (
                <div>BM25: <span className="text-[var(--color-stage-ink)]">{formatLatency(lat.bm25_latency_ms)}</span></div>
              )}
              {lat.retriever_latency_ms !== undefined && (
                <div>Retriever: <span className="text-[var(--color-stage-ink)]">{formatLatency(lat.retriever_latency_ms)}</span></div>
              )}
              {lat.reranker_latency_ms !== undefined && (
                <div>Reranker: <span className="text-[var(--color-stage-ink)]">{formatLatency(lat.reranker_latency_ms)}</span></div>
              )}
              {lat.stock_bm25_latency_ms !== undefined && (
                <div>Stock BM25: <span className="text-[var(--color-stage-ink)]">{formatLatency(lat.stock_bm25_latency_ms)}</span></div>
              )}
              {lat.judge_latency_ms !== undefined && lat.judge_latency_ms > 0 && (
                <div>Judge: <span className="text-[var(--color-stage-ink)]">{formatLatency(lat.judge_latency_ms)}</span></div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
