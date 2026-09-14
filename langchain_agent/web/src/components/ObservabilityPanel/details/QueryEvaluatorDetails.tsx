/**
 * QueryEvaluatorDetails - Shows query analysis and alpha (hybrid search) selection.
 */

import { useObservabilityStore } from '../../../stores/observabilityStore'
import clsx from 'clsx'

export function QueryEvaluatorDetails() {
  const { queryEvaluation } = useObservabilityStore()

  if (!queryEvaluation) {
    return (
      <div className="text-[1.375rem] text-[var(--color-stage-ink-soft)]">
        Waiting for query evaluation...
      </div>
    )
  }

  const { alpha, query_analysis, search_strategy } = queryEvaluation

  // Calculate position on the scale (0 = lexical, 1 = semantic)
  const scalePosition = alpha * 100

  return (
    <div className="space-y-4 min-w-0 w-full">
      {/* Search strategy badge */}
      <div className="flex items-center gap-2">
        <span className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">Strategy:</span>
        <span
          className={clsx(
            'px-2 py-0.5 rounded-full text-[1.25rem] font-medium',
            search_strategy === 'lexical-heavy' && 'bg-white border-2 border-[#9A3412] text-[#9A3412]',
            search_strategy === 'balanced' && 'bg-white border-2 border-[#5B21B6] text-[#5B21B6]',
            search_strategy === 'semantic-heavy' && 'bg-white border-2 border-[#1E40AF] text-[#1E40AF]'
          )}
        >
          {search_strategy}
        </span>
      </div>

      {/* Alpha scale visualization */}
      <div className="space-y-2">
        {/* Scale labels - Standard convention: 0=lexical, 1=semantic */}
        <div className="flex justify-between text-[1.25rem] text-[var(--color-stage-ink-soft)]">
          <span>Lexical (BM25)</span>
          <span>Semantic (Vector)</span>
        </div>

        <div className="relative h-3 bg-[var(--color-stage-raised)] rounded-full overflow-hidden">
          {/* Gradient background - amber (lexical) to blue (semantic) */}
          <div
            className="absolute inset-0"
            style={{
              background: 'linear-gradient(to right, #f59e0b, #8b5cf6, #3b82f6)',
              opacity: 0.3,
            }}
          />

          {/* Position indicator */}
          <div
            className="absolute top-0 bottom-0 w-3 -ml-1.5 bg-white rounded-full shadow-lg"
            style={{ left: `${scalePosition}%` }}
          />
        </div>

        <div className="text-center text-[1.375rem]">
          <span className="font-bold text-[var(--color-stage-ink)]">
            {(alpha * 100).toFixed(0)}%
          </span>
          <span className="text-[var(--color-stage-ink-soft)] ml-1">semantic weight</span>
        </div>
      </div>

      {/* Analysis reasoning */}
      <div className="space-y-1">
        <span className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">Analysis:</span>
        <p className="text-[1.375rem] text-[var(--color-stage-ink-muted)] bg-[var(--color-stage-raised)] rounded p-2">
          {query_analysis}
        </p>
      </div>

      {/* Explanation */}
      <div className="text-[1.25rem] text-[var(--color-stage-ink-soft)] border-t border-[var(--color-stage-border)] pt-3">
        <p>
          <strong>Alpha</strong> controls the hybrid search balance.
          Lower values (α→0) favor exact keyword matching (BM25), while higher values
          (α→1) favor semantic similarity (vector embeddings).
        </p>
      </div>
    </div>
  )
}
