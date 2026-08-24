import { IntentClassificationEvent, QueryExpansionEvent } from '../../../types/events'
import clsx from 'clsx'

interface IntentClassifierDetailsProps {
  event?: IntentClassificationEvent
  queryExpansion?: QueryExpansionEvent | null
}

export function IntentClassifierDetails({ event, queryExpansion }: IntentClassifierDetailsProps) {
  if (!event) {
    return (
      <div className="text-sm text-gray-400 animate-pulse">
        Classifying intent…
      </div>
    )
  }

  // Determine confidence level for visual feedback
  const confidence = event.confidence ?? 1.0
  const confidencePercent = (confidence * 100).toFixed(0)
  const isLowConfidence = confidence < 0.7

  return (
    <div className="space-y-3 text-sm text-gray-100">
      {/* Intent with badge */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-gray-200">Intent:</span>
        <span className={clsx(
          'px-2 py-0.5 rounded text-xs font-medium',
          event.intent === 'question' && 'bg-blue-500/20 text-blue-400',
          event.intent === 'summary' && 'bg-purple-500/20 text-purple-400',
          event.intent === 'follow_up' && 'bg-cyan-500/20 text-cyan-400',
          event.intent === 'clarify' && 'bg-yellow-500/20 text-yellow-400',
          event.intent === 'greeting' && 'bg-green-500/20 text-green-400',
          !['question', 'summary', 'follow_up', 'clarify', 'greeting'].includes(event.intent) && 'bg-gray-500/20 text-gray-400'
        )}>
          {event.intent}
        </span>
      </div>

      {/* Confidence score with bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-gray-200">Confidence:</span>
          <span className={clsx(
            'text-xs',
            isLowConfidence ? 'text-yellow-400' : 'text-green-400'
          )}>
            {confidencePercent}%
          </span>
        </div>
        <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all',
              isLowConfidence ? 'bg-yellow-500' : 'bg-green-500'
            )}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
        {isLowConfidence && (
          <p className="text-xs text-yellow-400/80">
            Low confidence may trigger clarification
          </p>
        )}
      </div>

      {/* Reasoning */}
      <div>
        <span className="font-semibold text-gray-200">Reason:</span>
        <p className="mt-1 text-gray-400">{event.reasoning}</p>
      </div>

      {/* Query */}
      <div>
        <span className="font-semibold text-gray-200">Query:</span>
        <p className="mt-1 text-gray-300">{event.user_query || '—'}</p>
      </div>

      {/* Query Expansion (if present) */}
      {queryExpansion && (
        <div className="mt-3 p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-cyan-400 font-semibold text-xs">QUERY EXPANDED</span>
          </div>
          <div className="space-y-1 text-xs">
            <div>
              <span className="text-gray-400">Original:</span>
              <span className="ml-2 text-gray-300">{queryExpansion.original_query}</span>
            </div>
            <div>
              <span className="text-gray-400">Expanded:</span>
              <span className="ml-2 text-cyan-300">{queryExpansion.expanded_query}</span>
            </div>
            <div className="text-gray-500 mt-1">
              {queryExpansion.expansion_reason}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
