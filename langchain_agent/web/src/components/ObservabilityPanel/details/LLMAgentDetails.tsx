/**
 * LLMAgentDetails - Display LLM agent execution details including reasoning, tool calls, and responses
 */

import { RefreshCw } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type {
  LLMReasoningChunkEvent,
  LLMResponseChunkEvent,
  ToolCallEvent,
  EnrichmentTriggeredEvent,
  ObservabilityStep,
} from '../../../types/events'

/**
 * Pre-process markdown content to fix common issues from LLM output.
 */
function preprocessMarkdown(content: string): string {
  return content
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/(?<!\\)\\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
}

interface LLMAgentDetailsProps {
  step: ObservabilityStep
}

export function LLMAgentDetails({ step }: LLMAgentDetailsProps) {
  // Use the step passed directly from the parent, not from global state
  const agentStep = step

  if (!agentStep) {
    return (
      <div className="text-sm text-gray-500">
        No agent execution data available
      </div>
    )
  }

  // Extract different event types from the step's events
  const reasoningChunks = agentStep.events.filter(
    (e) => e.type === 'llm_reasoning_chunk'
  ) as LLMReasoningChunkEvent[]

  const responseChunks = agentStep.events.filter(
    (e) => e.type === 'llm_response_chunk'
  ) as LLMResponseChunkEvent[]

  const toolCalls = agentStep.events.filter(
    (e) => e.type === 'tool_call'
  ) as ToolCallEvent[]

  const enrichmentEvent = agentStep.events.find(
    (e) => e.type === 'enrichment_triggered'
  ) as EnrichmentTriggeredEvent | undefined

  // Combine response chunks into full response
  const fullResponse = responseChunks.map((c) => c.content).join('')
  const fullReasoning = reasoningChunks.map((c) => c.content).join('')

  return (
    <div className="space-y-4 text-sm min-w-0 w-full">
      {/* Enrichment flywheel — shown first and distinctly, not buried among
          the generic Tool Calls list. This is the "agent fixes the catalog,
          not just the query" moment the demo centers on. */}
      {enrichmentEvent && (
        <div className="flex items-start gap-3 rounded-lg border-2 border-emerald-400 bg-emerald-500/15 p-3">
          <RefreshCw
            className={`w-5 h-5 text-emerald-300 flex-shrink-0 mt-0.5 ${
              agentStep.status === 'running' ? 'animate-spin' : ''
            }`}
          />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-emerald-200">
              Catalog Enrichment Triggered
            </div>
            <div className="text-xs text-emerald-100 mt-1">
              Recognized <span className="font-mono">{enrichmentEvent.attribute_type}</span> gap:
              {' '}&ldquo;{enrichmentEvent.variant}&rdquo;
              {enrichmentEvent.canonical && (
                <> resolved to canonical bucket &ldquo;{enrichmentEvent.canonical}&rdquo;</>
              )}
            </div>
            <div className="text-xs text-emerald-300/90 mt-1">
              {agentStep.status === 'running' ? (
                'Writing the new mapping and re-indexing the catalog live (~15-20s)...'
              ) : enrichmentEvent.duration_seconds != null ? (
                <>
                  New mapping written; catalog re-indexed —{' '}
                  <span className="font-mono">
                    {enrichmentEvent.docs_processed != null &&
                      `${enrichmentEvent.docs_processed} products in `}
                    {enrichmentEvent.duration_seconds.toFixed(1)}s
                  </span>
                  . This query — and future ones — now resolve it.
                </>
              ) : (
                'New mapping written; catalog re-indexed. This query — and future ones — now resolve it.'
              )}
            </div>
          </div>
        </div>
      )}

      {/* Reasoning Section */}
      {fullReasoning && (
        <div>
          <div className="text-xs font-medium text-gray-400 mb-2">LLM Reasoning</div>
          <div className="bg-gray-900/50 rounded border border-gray-700/30 p-3 text-xs text-gray-300 max-h-48 overflow-y-auto leading-relaxed whitespace-pre-wrap break-words">
            {fullReasoning}
          </div>
        </div>
      )}

      {/* Tool Calls Section */}
      {toolCalls.length > 0 && (
        <div>
          <div className="text-xs font-medium text-gray-400 mb-2">
            Tool Calls ({toolCalls.length})
          </div>
          <div className="space-y-2">
            {toolCalls.map((toolCall, idx) => (
              <div
                key={idx}
                className="bg-purple-500/5 border border-purple-500/20 rounded p-3"
              >
                <div className="text-xs font-medium text-purple-400 mb-2">
                  {toolCall.tool_name}
                </div>
                <div className="bg-black/30 rounded p-2 font-mono text-xs text-gray-300 max-h-24 overflow-y-auto break-words">
                  {JSON.stringify(toolCall.tool_args, null, 2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Response Section */}
      {fullResponse && (
        <div>
          <div className="text-xs font-medium text-gray-400 mb-2">
            Response ({fullResponse.length} chars)
          </div>
          <div className="bg-gray-900/50 rounded border border-gray-700/30 p-3 text-xs text-gray-300 max-h-64 overflow-y-auto leading-relaxed prose prose-invert prose-xs max-w-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // Compact styling for observability panel
                h1: ({ children }) => <h1 className="text-sm font-bold text-white mt-2 mb-1">{children}</h1>,
                h2: ({ children }) => <h2 className="text-xs font-bold text-white mt-2 mb-1">{children}</h2>,
                h3: ({ children }) => <h3 className="text-xs font-semibold text-gray-200 mt-1 mb-1">{children}</h3>,
                p: ({ children }) => <p className="mb-2 text-xs">{children}</p>,
                pre: ({ children }) => <pre className="bg-black/40 rounded p-2 overflow-x-auto text-xs my-2">{children}</pre>,
                code: ({ className, children, ...props }) => {
                  const isInline = !className
                  return isInline ? (
                    <code className="bg-gray-700 px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
                  ) : (
                    <code className={className} {...props}>{children}</code>
                  )
                },
                a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">{children}</a>,
                ul: ({ children }) => <ul className="list-disc list-inside my-1 ml-2 text-xs">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal list-inside my-1 ml-2 text-xs">{children}</ol>,
                li: ({ children }) => <li className="text-xs">{children}</li>,
                table: ({ children }) => <div className="overflow-x-auto my-2"><table className="w-full border-collapse text-xs">{children}</table></div>,
                thead: ({ children }) => <thead className="bg-gray-800">{children}</thead>,
                th: ({ children }) => <th className="px-2 py-1 text-left text-xs font-semibold border border-gray-700">{children}</th>,
                td: ({ children }) => <td className="px-2 py-1 text-xs border border-gray-700">{children}</td>,
                blockquote: ({ children }) => <blockquote className="border-l-2 border-gray-600 pl-2 italic text-gray-400 my-2 text-xs">{children}</blockquote>,
                hr: () => <hr className="my-2 border-gray-700" />,
              }}
            >
              {preprocessMarkdown(fullResponse)}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* Status Indicator */}
      <div className="text-xs text-gray-500 pt-2 border-t border-gray-700/30">
        {responseChunks.length > 0 && (
          <>
            <div>
              Response complete:{' '}
              {responseChunks[responseChunks.length - 1]?.is_complete ? '✓' : 'Streaming...'}
            </div>
          </>
        )}
        {reasoningChunks.length > 0 && (
          <div>
            Reasoning complete:{' '}
            {reasoningChunks[reasoningChunks.length - 1]?.is_complete ? '✓' : 'Processing...'}
          </div>
        )}
      </div>
    </div>
  )
}
