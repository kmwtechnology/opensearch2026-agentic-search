/**
 * ObservabilityPanel - Real-time visualization of agent execution.
 * Shows steps with full observability.
 */

import { RefreshCw } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { HistoricalSnapshotCard } from './HistoricalSnapshotCard'
import { PipelineSummaryCard } from './PipelineSummaryCard'
import { StepsList } from './StepsList'
import { SearchOptimizationDetails } from './SearchOptimizationDetails'

export function ObservabilityPanel() {
  const { isExecuting, steps, enrichmentTriggered } = useObservabilityStore()

  return (
    <div className="flex flex-col w-full min-w-0 h-full bg-[var(--color-stage-raised)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-stage-border)] flex-shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-[var(--color-stage-ink)]" style={{fontSize:"var(--text-stage-label)"}}>Observability</h2>
          {isExecuting && (
            <span className="node-badge node-badge-running">
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse mr-1.5" />
              Active
            </span>
          )}
        </div>
      </div>

      {/* Enrichment flywheel banner — PROJECTOR OPTIMIZED. Always visible
          (not gated behind expanding a step) the moment trigger_enrichment
          fires this turn, so a live re-index isn't just a silent wait. */}
      {enrichmentTriggered && (
        <div className="flex items-center gap-3 px-4 py-3 bg-emerald-500/15 border-b-2 border-emerald-400 flex-shrink-0">
          <RefreshCw
            className={`w-5 h-5 text-emerald-300 flex-shrink-0 ${isExecuting ? 'animate-spin' : ''}`}
          />
          <div className="min-w-0">
            <div className="text-[1.375rem] font-semibold text-emerald-200">
              Catalog Enrichment Triggered — live re-index {isExecuting ? 'in progress' : 'complete'}
            </div>
            <div className="text-[1.25rem] text-emerald-300/90 truncate">
              {enrichmentTriggered.attribute_type} &ldquo;{enrichmentTriggered.variant}&rdquo;
              {enrichmentTriggered.canonical && <> → resolved to &ldquo;{enrichmentTriggered.canonical}&rdquo;</>}
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-h-0 min-w-0 overflow-hidden">
        <div className="h-full w-full overflow-y-auto">
          {/* Search Optimizations Info - Always visible */}
          <div className="px-4 pt-4">
            <SearchOptimizationDetails />
          </div>

          {/* Execution Steps */}
          <div className="mt-4">
            <StepsList />
          </div>

          {/* Hydrated snapshot when revisiting a historical conversation (#22) */}
          <div className="mt-4">
            <HistoricalSnapshotCard />
          </div>

          {/* End-of-pipeline retrieval-quality summary */}
          <div className="mt-4">
            <PipelineSummaryCard />
          </div>
        </div>
      </div>

      {/* Footer with step count */}
      <div className="px-4 py-2 border-t border-[var(--color-stage-border)] text-[1.25rem] text-[var(--color-stage-ink-soft)] flex-shrink-0">
        {steps.length} step{steps.length !== 1 ? 's' : ''} recorded
      </div>
    </div>
  )
}
