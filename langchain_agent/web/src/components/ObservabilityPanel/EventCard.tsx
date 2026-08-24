/**
 * EventCard - Individual event viewer with drill-down capability
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, Eye } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type { AgentEvent } from '../../types/events'
import clsx from 'clsx'
import { RawEventInspector } from './RawEventInspector'
import { DslViewerModal } from './DslViewerModal'

const QUERY_TYPE_LABEL: Record<string, string> = {
  hybrid: 'Hybrid',
  bm25_baseline: 'BM25 baseline',
  quality_gate_retry: 'Quality-gate retry',
}

interface EventCardProps {
  event: AgentEvent
  index: number
}

// Event type styling
const eventTypeConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  query_evaluation: {
    label: 'Query Evaluation',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/5 border-blue-500/20',
  },
  hybrid_search_start: {
    label: 'Search Start',
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/5 border-violet-500/20',
  },
  hybrid_search_result: {
    label: 'Search Results',
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/5 border-violet-500/20',
  },
  reranker_start: {
    label: 'Reranking',
    color: 'text-indigo-400',
    bgColor: 'bg-indigo-500/5 border-indigo-500/20',
  },
  reranker_result: {
    label: 'Reranking Results',
    color: 'text-indigo-400',
    bgColor: 'bg-indigo-500/5 border-indigo-500/20',
  },
  document_grading_start: {
    label: 'Grading Start',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/5 border-emerald-500/20',
  },
  document_grade: {
    label: 'Document Grade',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/5 border-emerald-500/20',
  },
  document_grading_summary: {
    label: 'Grading Summary',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/5 border-emerald-500/20',
  },
  query_transformation: {
    label: 'Query Transform',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/5 border-amber-500/20',
  },
  opensearch_query: {
    label: 'OpenSearch Query',
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/5 border-yellow-500/20',
  },
  llm_reasoning_start: {
    label: 'LLM Reasoning',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/5 border-cyan-500/20',
  },
  llm_reasoning_chunk: {
    label: 'Reasoning Chunk',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/5 border-cyan-500/20',
  },
  llm_response_start: {
    label: 'Response Start',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/5 border-cyan-500/20',
  },
  llm_response_chunk: {
    label: 'Response Chunk',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/5 border-cyan-500/20',
  },
  tool_call: {
    label: 'Tool Call',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/5 border-purple-500/20',
  },
  response_grading: {
    label: 'Response Grade',
    color: 'text-pink-400',
    bgColor: 'bg-pink-500/5 border-pink-500/20',
  },
  response_improvement: {
    label: 'Response Improve',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/5 border-orange-500/20',
  },
  agent_complete: {
    label: 'Agent Complete',
    color: 'text-green-400',
    bgColor: 'bg-green-500/5 border-green-500/20',
  },
  agent_error: {
    label: 'Agent Error',
    color: 'text-red-400',
    bgColor: 'bg-red-500/5 border-red-500/20',
  },
  node_start: {
    label: 'Node Start',
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/5 border-gray-500/20',
  },
  node_end: {
    label: 'Node End',
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/5 border-gray-500/20',
  },
}

export function EventCard({ event, index }: EventCardProps) {
  const { expandedEvents, toggleEventExpanded } = useObservabilityStore()
  const [showRaw, setShowRaw] = useState(false)
  const eventId = `${event.type}-${index}-${event.timestamp}`
  const isExpanded = expandedEvents.has(eventId)

  const config = eventTypeConfig[event.type] || {
    label: event.type,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/5 border-gray-500/20',
  }

  const timestamp = new Date(event.timestamp)
  const relativeTime = getRelativeTime(timestamp)

  return (
    <div
      className={clsx(
        'rounded border transition-all',
        config.bgColor
      )}
    >
      {/* Event header - always visible */}
      <div className="flex items-center gap-2 px-3 py-2 text-left text-xs">
        {/* Expand button */}
        <button
          onClick={() => toggleEventExpanded(eventId)}
          className="flex items-center gap-2 flex-1 hover:bg-white/5 transition-colors rounded px-1"
        >
          {/* Expand icon */}
          <div className="flex-shrink-0 text-gray-600">
            {isExpanded ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
          </div>

          {/* Event type */}
          <span className={clsx('font-medium', config.color)}>
            {config.label}
          </span>
        </button>

        {/* Time */}
        <span className="text-gray-600 flex-shrink-0">
          {relativeTime}
        </span>

        {/* Raw JSON toggle button */}
        <button
          onClick={() => setShowRaw(!showRaw)}
          className={clsx(
            'px-2 py-1 rounded text-xs font-mono transition-colors flex-shrink-0',
            showRaw
              ? 'bg-gray-400/20 border border-gray-400/40 text-gray-300'
              : 'bg-gray-600/10 border border-gray-600/30 text-gray-500 hover:bg-gray-600/20 hover:text-gray-400'
          )}
          title="Toggle raw JSON view"
        >
          {'{ }'} Raw
        </button>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-3 py-2 border-t border-gray-700/30 bg-black/20">
          {showRaw ? (
            <RawEventInspector events={[event]} />
          ) : (
            <EventDetails event={event} />
          )}
        </div>
      )}
    </div>
  )
}

function EventDetails({ event }: { event: AgentEvent }) {
  const eventType = event.type

  switch (eventType) {
    case 'query_evaluation':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Query:</span> {(event as any).query}</div>
          <div><span className="text-gray-500">Alpha:</span> {((event as any).alpha * 100).toFixed(0)}%</div>
          <div><span className="text-gray-500">Strategy:</span> {(event as any).search_strategy}</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-gray-500 text-xs mb-1">Analysis:</div>
            <div className="text-gray-400 text-xs leading-relaxed">{(event as any).query_analysis}</div>
          </div>
        </div>
      )

    case 'hybrid_search_start':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Query:</span> {(event as any).query}</div>
          <div><span className="text-gray-500">Alpha:</span> {((event as any).alpha * 100).toFixed(0)}%</div>
          <div><span className="text-gray-500">Fetch K:</span> {(event as any).fetch_k}</div>
        </div>
      )

    case 'document_grade':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Source:</span> {(event as any).source}</div>
          <div>
            <span className="text-gray-500">Relevant:</span>{' '}
            <span className={(event as any).relevant ? 'text-emerald-400' : 'text-red-400'}>
              {(event as any).relevant ? '✓ Yes' : '✗ No'}
            </span>
          </div>
          <div><span className="text-gray-500">Score:</span> {((event as any).score * 100).toFixed(0)}%</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-gray-500 text-xs mb-1">Reasoning:</div>
            <div className="text-gray-400 text-xs leading-relaxed">{(event as any).reasoning}</div>
          </div>
        </div>
      )

    case 'query_transformation':
      return (
        <div className="space-y-2 text-xs text-gray-300">
          <div><span className="text-gray-500">Iteration:</span> {(event as any).iteration} / {(event as any).max_iterations}</div>
          <div className="space-y-1">
            <div className="text-gray-500">Original Query:</div>
            <div className="bg-black/30 p-2 rounded text-gray-300 break-words">
              {(event as any).original_query}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-gray-500">Transformed Query:</div>
            <div className="bg-black/30 p-2 rounded text-gray-300 break-words">
              {(event as any).transformed_query}
            </div>
          </div>
          {(event as any).reasons && (event as any).reasons.length > 0 && (
            <div className="space-y-1">
              <div className="text-gray-500">Reasons:</div>
              <ul className="list-disc list-inside text-gray-400 space-y-0.5">
                {(event as any).reasons.map((reason: string, i: number) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )

    case 'opensearch_query': {
      const ev = event as any
      const queryType: string = ev.query_type ?? 'hybrid'
      const typeLabel = QUERY_TYPE_LABEL[queryType] ?? queryType
      return (
        <div className="space-y-2 text-xs text-gray-300">
          <div className="flex items-center justify-between gap-2">
            <div>
              <span className="text-gray-500">Type:</span>{' '}
              <span className="text-yellow-300">{typeLabel}</span>
            </div>
            {ev.body && (
              <DslViewerEyeButton
                title={`${typeLabel} query DSL`}
                subtitle={`Intent: ${ev.intent ?? '—'} · alpha ${((ev.alpha ?? 0) * 100).toFixed(0)}%`}
                body={ev.body}
                index={ev.index}
                params={ev.params}
              />
            )}
          </div>
          <div><span className="text-gray-500">Intent:</span> {ev.intent}</div>
          <div><span className="text-gray-500">Alpha:</span> {((ev.alpha ?? 0) * 100).toFixed(0)}%</div>
          <div className="space-y-1">
            <div className="text-gray-500">Query:</div>
            <div className="bg-black/30 p-2 rounded text-gray-300 break-words">
              {ev.query}
            </div>
          </div>
          {ev.filter_summary && (
            <div className="space-y-1">
              <div className="text-gray-500">Applied Filters:</div>
              <div className="bg-black/30 p-2 rounded text-yellow-300 font-mono">
                {ev.filter_summary}
              </div>
            </div>
          )}
        </div>
      )
    }

    case 'llm_response_chunk':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Complete:</span> {(event as any).is_complete ? 'Yes' : 'No'}</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-gray-500 text-xs mb-1">Content:</div>
            <div className="bg-black/30 p-2 rounded text-gray-300 text-xs max-h-32 overflow-y-auto break-words">
              {(event as any).content}
            </div>
          </div>
        </div>
      )

    case 'llm_reasoning_chunk':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Complete:</span> {(event as any).is_complete ? 'Yes' : 'No'}</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-gray-500 text-xs mb-1">Reasoning:</div>
            <div className="bg-black/30 p-2 rounded text-gray-300 text-xs max-h-32 overflow-y-auto break-words">
              {(event as any).content}
            </div>
          </div>
        </div>
      )

    case 'tool_call':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Tool:</span> {(event as any).tool_name}</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-gray-500 text-xs mb-1">Arguments:</div>
            <div className="bg-black/30 p-2 rounded text-gray-300 text-xs font-mono max-h-32 overflow-y-auto">
              {JSON.stringify((event as any).tool_args, null, 2)}
            </div>
          </div>
        </div>
      )

    case 'response_improvement':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Retry:</span> {(event as any).retry_count}</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-gray-500 text-xs mb-1">Feedback:</div>
            <div className="text-gray-400 text-xs leading-relaxed">{(event as any).feedback}</div>
          </div>
        </div>
      )

    case 'agent_error':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Recoverable:</span> {(event as any).recoverable ? 'Yes' : 'No'}</div>
          <div className="mt-2 pt-1 border-t border-gray-700/30">
            <div className="text-red-400 text-xs leading-relaxed">{(event as any).error}</div>
          </div>
        </div>
      )

    case 'reranker_result':
      return (
        <div className="space-y-1 text-xs text-gray-300">
          <div><span className="text-gray-500">Order Changed:</span> {(event as any).reranking_changed_order ? 'Yes' : 'No'}</div>
          <div><span className="text-gray-500">Results Count:</span> {(event as any).results?.length || 0}</div>
        </div>
      )

    default:
      return (
        <div className="text-xs text-gray-500">
          Raw event: <span className="font-mono text-gray-400">{JSON.stringify(event).substring(0, 100)}...</span>
        </div>
      )
  }
}

interface DslViewerEyeButtonProps {
  title: string
  subtitle?: string
  body: Record<string, unknown> | null | undefined
  index?: string
  params?: Record<string, string>
}

function DslViewerEyeButton({ title, subtitle, body, index, params }: DslViewerEyeButtonProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-yellow-300/80 hover:text-yellow-200 hover:bg-yellow-500/10 transition-colors"
        title="View OpenSearch DSL"
        aria-label={`View ${title}`}
      >
        <Eye className="w-3.5 h-3.5" />
        DSL
      </button>
      <DslViewerModal
        isOpen={open}
        title={title}
        subtitle={subtitle}
        body={body}
        index={index}
        params={params}
        onClose={() => setOpen(false)}
      />
    </>
  )
}

function getRelativeTime(date: Date): string {
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffS = Math.round(diffMs / 1000)

  if (diffS < 1) return 'now'
  if (diffS < 60) return `${diffS}s ago`
  if (diffS < 3600) return `${Math.round(diffS / 60)}m ago`
  return `${Math.round(diffS / 3600)}h ago`
}
