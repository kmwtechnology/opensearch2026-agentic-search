import { IntentClassificationEvent, QueryExpansionEvent } from '../../../types/events'
import clsx from 'clsx'

interface IntentClassifierDetailsProps {
  event?: IntentClassificationEvent
  queryExpansion?: QueryExpansionEvent | null
}

export function IntentClassifierDetails({ event, queryExpansion }: IntentClassifierDetailsProps) {
  if (!event) {
    return (
      <div className="text-[1.375rem] text-[var(--color-stage-ink-soft)] animate-pulse">
        Classifying intent…
      </div>
    )
  }

  // Determine confidence level for visual feedback
  const confidence = event.confidence ?? 1.0
  const confidencePercent = (confidence * 100).toFixed(0)
  const isLowConfidence = confidence < 0.7

  return (
    <div className="space-y-3 text-[1.375rem] text-[var(--color-stage-ink)]">
      {/* Intent with badge */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-[var(--color-stage-ink)]">Intent:</span>
        <span className={clsx(
          'px-2 py-0.5 rounded text-[1.25rem] font-medium',
          event.intent === 'question' && 'bg-white border-2 border-[#1E40AF] text-[#1E40AF]',
          event.intent === 'summary' && 'bg-white border-2 border-[#5B21B6] text-[#5B21B6]',
          event.intent === 'follow_up' && 'bg-white border-2 border-[#155E75] text-[#155E75]',
          event.intent === 'clarify' && 'bg-white border-2 border-[#9A3412] text-[#9A3412]',
          event.intent === 'greeting' && 'bg-white border-2 border-[#065F46] text-[#065F46]',
          !['question', 'summary', 'follow_up', 'clarify', 'greeting'].includes(event.intent) && 'bg-white border-2 border-[#4A463F] text-[var(--color-stage-ink-soft)]'
        )}>
          {event.intent}
        </span>
      </div>

      {/* Confidence score with bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-[var(--color-stage-ink)]">Confidence:</span>
          <span className={clsx(
            'text-[1.25rem]',
            isLowConfidence ? 'text-[#9A3412]' : 'text-[#065F46]'
          )}>
            {confidencePercent}%
          </span>
        </div>
        <div className="h-1.5 bg-[var(--color-stage-raised)] rounded-full overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all',
              isLowConfidence ? 'bg-[#9A3412]' : 'bg-[#065F46]'
            )}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
        {isLowConfidence && (
          <p className="text-[1.25rem] text-[#9A3412]/80">
            Low confidence may trigger clarification
          </p>
        )}
      </div>

      {/* Reasoning */}
      <div>
        <span className="font-semibold text-[var(--color-stage-ink)]">Reason:</span>
        <p className="mt-1 text-[var(--color-stage-ink-soft)]">{event.reasoning}</p>
      </div>

      {/* Query */}
      <div>
        <span className="font-semibold text-[var(--color-stage-ink)]">Query:</span>
        <p className="mt-1 text-[var(--color-stage-ink-muted)]">{event.user_query || '—'}</p>
      </div>

      {/* Query Expansion (if present) */}
      {queryExpansion && (
        <div className="mt-3 p-2 rounded-lg bg-white border-2 border-[#155E75] border border-[#155E75]">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[#155E75] font-semibold text-[1.25rem]">QUERY EXPANDED</span>
          </div>
          <div className="space-y-1 text-[1.25rem]">
            <div>
              <span className="text-[var(--color-stage-ink-soft)]">Original:</span>
              <span className="ml-2 text-[var(--color-stage-ink-muted)]">{queryExpansion.original_query}</span>
            </div>
            <div>
              <span className="text-[var(--color-stage-ink-soft)]">Expanded:</span>
              <span className="ml-2 text-[#155E75]">{queryExpansion.expanded_query}</span>
            </div>
            <div className="text-[var(--color-stage-ink-soft)] mt-1">
              {queryExpansion.expansion_reason}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
