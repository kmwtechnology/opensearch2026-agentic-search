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
          <h3 className="text-sm font-semibold text-gray-100">Last Run Snapshot</h3>
          <span className="text-xs text-gray-400">from checkpoint</span>
        </div>

        {s.user_query && (
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-400 mb-1">Query</div>
            <div className="text-sm text-gray-100">{s.user_query}</div>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {s.intent && (
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Intent</div>
              <div className="text-gray-100">
                {s.intent}
                {s.intent_confidence !== null && (
                  <span className="text-gray-400 ml-2">
                    ({(s.intent_confidence * 100).toFixed(0)}%)
                  </span>
                )}
              </div>
            </div>
          )}
          {s.alpha !== null && (
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Alpha</div>
              <div className="text-gray-100">{formatNumber(s.alpha, 2)}</div>
            </div>
          )}
          {s.reranker_max_score !== null && (
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Reranker Max</div>
              <div className="text-gray-100">{formatNumber(s.reranker_max_score, 3)}</div>
            </div>
          )}
          {s.quality_gate_retried !== null && (
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Quality Gate</div>
              <div className="text-gray-100">
                {s.quality_gate_retried ? 'Retried' : 'Passed'}
              </div>
            </div>
          )}
        </div>

        {s.query_analysis && (
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-400 mb-1">Analysis</div>
            <div className="text-xs text-gray-200 leading-relaxed">{s.query_analysis}</div>
          </div>
        )}

        {Object.keys(lat).length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-400 mb-1">Latency</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-200">
              {lat.bm25_latency_ms !== undefined && (
                <div>BM25: <span className="text-gray-100">{formatLatency(lat.bm25_latency_ms)}</span></div>
              )}
              {lat.retriever_latency_ms !== undefined && (
                <div>Retriever: <span className="text-gray-100">{formatLatency(lat.retriever_latency_ms)}</span></div>
              )}
              {lat.reranker_latency_ms !== undefined && (
                <div>Reranker: <span className="text-gray-100">{formatLatency(lat.reranker_latency_ms)}</span></div>
              )}
              {lat.stock_bm25_latency_ms !== undefined && (
                <div>Stock BM25: <span className="text-gray-100">{formatLatency(lat.stock_bm25_latency_ms)}</span></div>
              )}
              {lat.judge_latency_ms !== undefined && lat.judge_latency_ms > 0 && (
                <div>Judge: <span className="text-gray-100">{formatLatency(lat.judge_latency_ms)}</span></div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
