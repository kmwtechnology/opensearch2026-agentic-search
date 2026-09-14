/**
 * StepCard - Expandable card showing details of a single execution step.
 */

import { ChevronDown, ChevronRight, Clock, RefreshCw } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type {
  AgentEvent,
  IntentClassificationEvent,
  ObservabilityStep,
  SummaryEvent,
  QualityGateEvent,
  EnrichmentTriggeredEvent,
  RerankerResultEvent,
} from '../../types/events'
import { QueryEvaluatorDetails } from './details/QueryEvaluatorDetails'
import { SearchDetails } from './details/SearchDetails'
import { LLMAgentDetails } from './details/LLMAgentDetails'
import { IntentClassifierDetails } from './details/IntentClassifierDetails'
import { SummaryDetails } from './details/SummaryDetails'
import { LlmJudgeDetails } from './details/LlmJudgeDetails'
import clsx from 'clsx'

interface StepCardProps {
  step: ObservabilityStep
  index: number
}

// Node display configuration — PROJECTOR OPTIMIZED
const nodeConfig: Record<
  string,
  { label: string; color: string; bgColor: string; accent: string }
> = {
  query_evaluator: {
    label: 'Query Evaluator',
    color: 'text-[#1E40AF]',
    bgColor: 'bg-white border-[#1E40AF]', accent: '#1E40AF',
  },
  agent: {
    label: 'LLM Agent',
    color: 'text-[#155E75]',
    bgColor: 'bg-white border-[#155E75]', accent: '#155E75',
  },
  retriever: {
    label: 'Knowledge Search',
    color: 'text-[#5B21B6]',
    bgColor: 'bg-white border-[#5B21B6]', accent: '#5B21B6',
  },
  reranker: {
    // Overridden below once we know the actual reranker_type for this step
    // (#87) — this is only the fallback before that event arrives.
    label: 'Reranker',
    color: 'text-[#3730A3]',
    bgColor: 'bg-white border-[#3730A3]', accent: '#3730A3',
  },
  quality_gate: {
    label: 'Quality Gate',
    color: 'text-[#9A3412]',
    bgColor: 'bg-white border-[#9A3412]', accent: '#9A3412',
  },
  intent_classifier: {
    label: 'Intent Classifier',
    color: 'text-[#065F46]',
    bgColor: 'bg-white border-[#065F46]', accent: '#065F46',
  },
}

export function StepCard({ step, index }: StepCardProps) {
  const { expandedSteps, toggleStepExpanded } = useObservabilityStore()
  const isExpanded = expandedSteps.has(step.id)

  const enrichmentEvent = step.events.find(isEnrichmentTriggeredEvent)

  const baseConfig = enrichmentEvent
    ? {
        label: 'LLM Agent',
        color: 'text-[#065F46]',
        bgColor: 'bg-white border-[#065F46]', accent: '#065F46',
      }
    : nodeConfig[step.node] || {
        label: step.node,
        color: 'text-[var(--color-stage-ink-soft)]',
        bgColor: 'bg-white border-[var(--color-stage-border)]', accent: 'var(--color-stage-border)',
      }

  // The reranker's label depends on which reranker actually ran this turn —
  // never assume Gemini/LLM-based when the (default) local cross-encoder is
  // configured (#87). Spread into a fresh object rather than mutating
  // baseConfig, which for known nodes is a direct reference into the
  // shared, module-level nodeConfig map.
  let config = baseConfig
  if (!enrichmentEvent && step.node === 'reranker') {
    const rerankerResultEvent = step.events.find(
      (e): e is RerankerResultEvent => e.type === 'reranker_result'
    )
    if (rerankerResultEvent?.reranker_type === 'cross-encoder') {
      config = { ...baseConfig, label: 'Cross-Encoder Reranker' }
    } else if (rerankerResultEvent?.reranker_type) {
      config = { ...baseConfig, label: 'LLM Reranker' }
    }
  }

  const statusColors = {
    idle: 'bg-[#4A463F]',
    running: 'bg-[#1E40AF] animate-pulse',
    complete: 'bg-[#065F46]',
    error: 'bg-[#991B1B]',
  }

  return (
    <div
      className={clsx(
        'rounded-lg border-2 transition-all overflow-hidden',
        config.bgColor,
        step.status === 'running' && 'ring-4 ring-[#1E40AF]/30'
      )}
      // A thick left edge in the stage's hue. Identifies the stage at a glance
      // without putting a saturated wash behind the text, which is what made
      // these cards hard to read projected.
      style={{ borderLeftWidth: 10, borderLeftColor: config.accent }}
    >
      {/* Header - always visible — PROJECTOR OPTIMIZED */}
      <button
        onClick={() => toggleStepExpanded(step.id)}
        className="w-full flex items-center gap-3 px-4 py-4 text-left"
      >
        {/* Expand icon */}
        <div className="flex-shrink-0 text-[var(--color-stage-ink-soft)]">
          {isExpanded ? (
            <ChevronDown className="w-5 h-5" />
          ) : (
            <ChevronRight className="w-5 h-5" />
          )}
        </div>

        {/* Step number */}
        <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[var(--color-stage-raised)] flex items-center justify-center text-[1.375rem] font-medium text-[var(--color-stage-ink)]">
          {index + 1}
        </div>

        {/* Status indicator */}
        <div className={clsx('w-3 h-3 rounded-full', statusColors[step.status])} />

        {/* Node name + summary */}
        <div className="flex-1 min-w-0 truncate flex items-center gap-2">
          <span className={clsx('font-medium text-[var(--text-stage-body)]', config.color)}>
            {config.label}
          </span>
          {enrichmentEvent ? (
            <span className="ml-1 inline-flex items-center gap-1.5 text-[1.375rem] font-medium text-[#065F46]">
              <RefreshCw className={clsx('w-4 h-4', step.status === 'running' && 'animate-spin')} />
              Enrichment: {enrichmentEvent.attribute_type} &ldquo;{enrichmentEvent.variant}&rdquo;
              {enrichmentEvent.canonical && <> → &ldquo;{enrichmentEvent.canonical}&rdquo;</>}
            </span>
          ) : (
            step.node !== 'intent_classifier' && step.summary && (
              <span className="text-[1.375rem] text-[var(--color-stage-ink-muted)]">
                {step.summary}
              </span>
            )
          )}
        </div>

        {/* Duration */}
        {step.durationMs !== undefined && (
          <div className="flex-shrink-0 flex items-center gap-1 text-[1.375rem] text-[var(--color-stage-ink-muted)]">
            <Clock className="w-4 h-4" />
            {step.durationMs < 1000
              ? `${Math.round(step.durationMs)}ms`
              : `${(step.durationMs / 1000).toFixed(1)}s`}
          </div>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-1 border-t border-[var(--color-stage-border)] min-w-0 overflow-hidden">
          <StepDetails step={step} />
        </div>
      )}
    </div>
  )
}

function StepDetails({ step }: { step: ObservabilityStep }) {
  const { queryExpansion, qualityGate } = useObservabilityStore()

  switch (step.node) {
    case 'query_evaluator':
      return <QueryEvaluatorDetails />

    case 'retriever':
      return <SearchDetails mode="retriever" />

    case 'reranker':
      return <SearchDetails mode="reranker" />

    case 'agent':
      return <LLMAgentDetails step={step} />

    case 'intent_classifier': {
      const intentEvent = step.events.find(isIntentClassificationEvent)
      return <IntentClassifierDetails event={intentEvent} queryExpansion={queryExpansion} />
    }

    case 'quality_gate': {
      const gateEvent = step.events.find(isQualityGateEvent)
      return <QualityGateDetails event={gateEvent ?? qualityGate} />
    }

    case 'summary': {
      const summaryEvent = step.events.find(isSummaryEvent)
      return <SummaryDetails event={summaryEvent} status={step.status} />
    }

    case 'llm_judge':
      return <LlmJudgeDetails step={step} />

    default:
      return (
        <div className="text-[1.375rem] text-[var(--color-stage-ink-soft)]">
          No details available for this step.
        </div>
      )
  }
}

function isIntentClassificationEvent(event: AgentEvent): event is IntentClassificationEvent {
  return event.type === 'intent_classification'
}

function isEnrichmentTriggeredEvent(event: AgentEvent): event is EnrichmentTriggeredEvent {
  return event.type === 'enrichment_triggered'
}

function isSummaryEvent(event: AgentEvent): event is SummaryEvent {
  return event.type === 'summary_generated'
}

function isQualityGateEvent(event: AgentEvent): event is QualityGateEvent {
  return event.type === 'quality_gate'
}

// Inline QualityGateDetails component
function QualityGateDetails({ event }: { event?: QualityGateEvent | null }) {
  if (!event) {
    return (
      <div className="text-[1.375rem] text-[var(--color-stage-ink-soft)] animate-pulse">
        Evaluating result quality...
      </div>
    )
  }

  return (
    <div className="space-y-3 text-[1.375rem] text-[var(--color-stage-ink)]">
      {/* Triggered status */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-[var(--color-stage-ink)]">Status:</span>
        <span className={clsx(
          'px-2 py-0.5 rounded text-[1.25rem] font-medium',
          event.triggered
            ? 'bg-white border-2 border-[#9A3412] text-[#9A3412]'
            : 'bg-white border-2 border-[#4A463F] text-[var(--color-stage-ink-soft)]'
        )}>
          {event.triggered ? 'Retry Triggered' : 'Passed'}
        </span>
      </div>

      {/* Max score with bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-[var(--color-stage-ink)]">Max Reranker Score:</span>
          <span className={clsx(
            'text-[1.25rem] font-mono',
            event.max_score < event.threshold ? 'text-[#9A3412]' : 'text-[#065F46]'
          )}>
            {event.max_score.toFixed(3)}
          </span>
        </div>
        <div className="relative h-1.5 bg-[var(--color-stage-raised)] rounded-full overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all',
              event.max_score < event.threshold ? 'bg-[#9A3412]' : 'bg-[#065F46]'
            )}
            style={{ width: `${event.max_score * 100}%` }}
          />
          {/* Threshold marker */}
          <div
            className="absolute top-0 h-full w-0.5 bg-yellow-400"
            style={{ left: `${event.threshold * 100}%` }}
            title={`Threshold: ${event.threshold.toFixed(3)}`}
          />
        </div>
        <div className="flex justify-between text-[1.25rem] text-[var(--color-stage-ink-soft)]">
          <span className="font-mono">Threshold: {event.threshold.toFixed(3)}</span>
        </div>
      </div>

      {/* Alpha adjustment */}
      {event.triggered && event.new_alpha != null && (
        <div className="p-2 rounded-lg bg-white border-2 border-[#9A3412] border border-[#9A3412]">
          <div className="flex items-center gap-2 text-[1.25rem]">
            <span className="text-[var(--color-stage-ink-soft)]">Alpha adjusted:</span>
            <span className="text-[var(--color-stage-ink-muted)]">{event.original_alpha.toFixed(2)}</span>
            <span className="text-[#9A3412]">→</span>
            <span className="text-[#9A3412] font-medium">{event.new_alpha.toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Reason */}
      <div>
        <span className="font-semibold text-[var(--color-stage-ink)]">Reason:</span>
        <p className="mt-1 text-[var(--color-stage-ink-soft)]">{event.reason}</p>
      </div>
    </div>
  )
}
