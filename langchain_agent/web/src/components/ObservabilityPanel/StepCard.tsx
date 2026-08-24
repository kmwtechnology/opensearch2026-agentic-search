/**
 * StepCard - Expandable card showing details of a single execution step.
 */

import { ChevronDown, ChevronRight, Clock } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type {
  AgentEvent,
  IntentClassificationEvent,
  ObservabilityStep,
  SummaryEvent,
  QualityGateEvent,
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
const nodeConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  query_evaluator: {
    label: 'Query Evaluator',
    color: 'text-blue-300',
    bgColor: 'bg-blue-500/20 border-blue-500/50',
  },
  agent: {
    label: 'LLM Agent',
    color: 'text-cyan-300',
    bgColor: 'bg-cyan-500/20 border-cyan-500/50',
  },
  retriever: {
    label: 'Knowledge Search',
    color: 'text-violet-300',
    bgColor: 'bg-violet-500/20 border-violet-500/50',
  },
  reranker: {
    label: 'LLM Reranker',
    color: 'text-indigo-300',
    bgColor: 'bg-indigo-500/20 border-indigo-500/50',
  },
  quality_gate: {
    label: 'Quality Gate',
    color: 'text-orange-300',
    bgColor: 'bg-orange-500/20 border-orange-500/50',
  },
  intent_classifier: {
    label: 'Intent Classifier',
    color: 'text-emerald-300',
    bgColor: 'bg-emerald-500/20 border-emerald-500/50',
  },
}

export function StepCard({ step, index }: StepCardProps) {
  const { expandedSteps, toggleStepExpanded } = useObservabilityStore()
  const isExpanded = expandedSteps.has(step.id)

  const config = nodeConfig[step.node] || {
    label: step.node,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10 border-gray-500/30',
  }

  const statusColors = {
    idle: 'bg-gray-500',
    running: 'bg-blue-500 animate-pulse',
    complete: 'bg-emerald-500',
    error: 'bg-red-500',
  }

  return (
    <div
      className={clsx(
        'rounded-lg border transition-all',
        config.bgColor,
        step.status === 'running' && 'ring-2 ring-blue-500/50'
      )}
    >
      {/* Header - always visible — PROJECTOR OPTIMIZED */}
      <button
        onClick={() => toggleStepExpanded(step.id)}
        className="w-full flex items-center gap-3 px-4 py-4 text-left"
      >
        {/* Expand icon */}
        <div className="flex-shrink-0 text-gray-500">
          {isExpanded ? (
            <ChevronDown className="w-5 h-5" />
          ) : (
            <ChevronRight className="w-5 h-5" />
          )}
        </div>

        {/* Step number */}
        <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center text-sm font-medium text-gray-200">
          {index + 1}
        </div>

        {/* Status indicator */}
        <div className={clsx('w-3 h-3 rounded-full', statusColors[step.status])} />

        {/* Node name + summary */}
        <div className="flex-1 min-w-0 truncate">
          <span className={clsx('font-medium text-base', config.color)}>
            {config.label}
          </span>
          {step.node !== 'intent_classifier' && step.summary && (
            <span className="ml-2 text-sm text-gray-300">
              {step.summary}
            </span>
          )}
        </div>

        {/* Duration */}
        {step.durationMs !== undefined && (
          <div className="flex-shrink-0 flex items-center gap-1 text-sm text-gray-300">
            <Clock className="w-4 h-4" />
            {step.durationMs < 1000
              ? `${Math.round(step.durationMs)}ms`
              : `${(step.durationMs / 1000).toFixed(1)}s`}
          </div>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-1 border-t border-gray-700/50 min-w-0 overflow-hidden">
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
        <div className="text-sm text-gray-500">
          No details available for this step.
        </div>
      )
  }
}

function isIntentClassificationEvent(event: AgentEvent): event is IntentClassificationEvent {
  return event.type === 'intent_classification'
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
      <div className="text-sm text-gray-400 animate-pulse">
        Evaluating result quality...
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm text-gray-100">
      {/* Triggered status */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-gray-200">Status:</span>
        <span className={clsx(
          'px-2 py-0.5 rounded text-xs font-medium',
          event.triggered
            ? 'bg-orange-500/20 text-orange-400'
            : 'bg-gray-500/20 text-gray-400'
        )}>
          {event.triggered ? 'Retry Triggered' : 'Passed'}
        </span>
      </div>

      {/* Max score with bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-gray-200">Max Reranker Score:</span>
          <span className={clsx(
            'text-xs font-mono',
            event.max_score < event.threshold ? 'text-orange-400' : 'text-green-400'
          )}>
            {event.max_score.toFixed(3)}
          </span>
        </div>
        <div className="relative h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all',
              event.max_score < event.threshold ? 'bg-orange-500' : 'bg-green-500'
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
        <div className="flex justify-between text-xs text-gray-500">
          <span className="font-mono">Threshold: {event.threshold.toFixed(3)}</span>
        </div>
      </div>

      {/* Alpha adjustment */}
      {event.triggered && event.new_alpha != null && (
        <div className="p-2 rounded-lg bg-orange-500/10 border border-orange-500/30">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-400">Alpha adjusted:</span>
            <span className="text-gray-300">{event.original_alpha.toFixed(2)}</span>
            <span className="text-orange-400">→</span>
            <span className="text-orange-300 font-medium">{event.new_alpha.toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Reason */}
      <div>
        <span className="font-semibold text-gray-200">Reason:</span>
        <p className="mt-1 text-gray-400">{event.reason}</p>
      </div>
    </div>
  )
}
