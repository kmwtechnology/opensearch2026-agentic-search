/**
 * ObservabilityPanel - Real-time visualization of agent execution.
 * Shows steps with full observability.
 */

import { useObservabilityStore } from '../../stores/observabilityStore'
import { HistoricalSnapshotCard } from './HistoricalSnapshotCard'
import { PipelineSummaryCard } from './PipelineSummaryCard'
import { StepsList } from './StepsList'
import { SearchOptimizationDetails } from './SearchOptimizationDetails'

export function ObservabilityPanel() {
  const { isExecuting, steps } = useObservabilityStore()

  return (
    <div className="flex flex-col w-full min-w-0 h-full bg-gray-900/50">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-100">Observability</h2>
          {isExecuting && (
            <span className="node-badge node-badge-running">
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse mr-1.5" />
              Active
            </span>
          )}
        </div>
      </div>

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
      <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-400 flex-shrink-0">
        {steps.length} step{steps.length !== 1 ? 's' : ''} recorded
      </div>
    </div>
  )
}
