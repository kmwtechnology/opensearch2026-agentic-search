/**
 * SearchDetails - Shows search candidates and reranking results.
 */

import { useState } from 'react'
import { useObservabilityStore } from '../../../stores/observabilityStore'
import { FileText, ArrowUp, ArrowDown, Minus, ChevronDown, ChevronUp, Loader2, ExternalLink, Filter, Eye } from 'lucide-react'
import clsx from 'clsx'
import type { OpenSearchQueryEvent, RerankerResultEvent } from '../../../types/events'
import { DslViewerModal } from '../DslViewerModal'

interface SearchDetailsProps {
  /**
   * Which pipeline step is rendering this view.
   * - `retriever` (default): always show pre-rerank candidates — even after
   *   reranking completes — so the card represents what the retriever produced.
   * - `reranker`: show the reranked document list (post-LLM scoring).
   */
  mode?: 'retriever' | 'reranker'
}

export function SearchDetails({ mode = 'retriever' }: SearchDetailsProps = {}) {
  const { searchCandidates, rerankedDocuments, searchStatus, rerankerStatus, steps } = useObservabilityStore()
  const [expandedDocs, setExpandedDocs] = useState<Set<number>>(new Set())
  const [hybridDslOpen, setHybridDslOpen] = useState(false)
  const [retryDslOpen, setRetryDslOpen] = useState(false)

  // The retriever step now emits multiple opensearch_query events (one per
  // query type). Pick the hybrid event for the main query banner; the
  // BM25 baseline shows up on PipelineSummaryCard, and the quality-gate
  // retry surfaces below as a second banner when present.
  const retrieverStep = steps.find(s => s.node === 'retriever')
  const opensearchEvents = (retrieverStep?.events ?? []).filter(
    (e): e is OpenSearchQueryEvent => e.type === 'opensearch_query'
  )
  // Treat events without an explicit query_type as legacy hybrid for
  // back-compat with replays from before the multi-emit change.
  const opensearchQueryEvent = opensearchEvents.find(
    e => (e.query_type ?? 'hybrid') === 'hybrid'
  )
  const retryQueryEvent = opensearchEvents.find(e => e.query_type === 'quality_gate_retry')

  // Which reranker actually scored this query — used to describe it
  // accurately below instead of assuming one (#87).
  const rerankerStep = steps.find(s => s.node === 'reranker')
  const rerankerResultEvent = (rerankerStep?.events ?? []).find(
    (e): e is RerankerResultEvent => e.type === 'reranker_result'
  )
  const rerankerType = rerankerResultEvent?.reranker_type

  // Toggle document expansion
  const toggleDocExpansion = (index: number) => {
    setExpandedDocs((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(index)) {
        newSet.delete(index)
      } else {
        newSet.add(index)
      }
      return newSet
    })
  }

  // The retriever step always shows the raw search candidates (pre-rerank); the
  // reranker step shows the reranked, scored list once available.
  const documents = mode === 'reranker' && rerankedDocuments.length > 0 ? rerankedDocuments : null
  const candidates = searchCandidates

  // Show waiting message only if nothing is happening and no results
  if (!documents && candidates.length === 0 && searchStatus === 'idle' && rerankerStatus === 'idle') {
    return (
      <div className="text-[1.375rem] text-[var(--color-stage-ink-soft)]">
        Waiting for search results...
      </div>
    )
  }

  return (
    <div className="space-y-4 min-w-0 w-full">
      {/* OpenSearch Query Details - Show filters and query modifications */}
      {opensearchQueryEvent && (
        <div className="rounded-lg bg-white border border-[#9A3412] p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Filter className="w-4 h-4 text-[#9A3412] flex-shrink-0" />
              <span className="text-[1.25rem] font-semibold text-[#9A3412]">OpenSearch Query</span>
            </div>
            {opensearchQueryEvent.body && (
              <button
                onClick={() => setHybridDslOpen(true)}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[1.25rem] text-[#9A3412]/80 hover:text-[#9A3412] hover:bg-white border-2 border-[#9A3412] transition-colors"
                title="View hybrid query DSL"
                aria-label="View hybrid OpenSearch query DSL"
              >
                <Eye className="w-3.5 h-3.5" />
                DSL
              </button>
            )}
          </div>

          <div className="space-y-2 text-[1.25rem] text-[var(--color-stage-ink-muted)]">
            <div>
              <span className="text-[var(--color-stage-ink-soft)]">Intent:</span>{' '}
              <span className="text-[#9A3412]">{opensearchQueryEvent.intent}</span>
            </div>
            <div>
              <span className="text-[var(--color-stage-ink-soft)]">Alpha:</span>{' '}
              <span className="text-[#9A3412]">{(opensearchQueryEvent.alpha * 100).toFixed(0)}%</span>
            </div>
            {opensearchQueryEvent.filter_summary && (
              <div>
                <span className="text-[var(--color-stage-ink-soft)]">Filters Applied:</span>{' '}
                <span className="text-[#9A3412] font-mono">{opensearchQueryEvent.filter_summary}</span>
              </div>
            )}
            <div className="pt-1">
              <span className="text-[var(--color-stage-ink-soft)]">Query:</span>
              <div className="mt-1 p-2 rounded bg-[var(--color-stage-raised)] text-[var(--color-stage-ink-muted)] break-words text-[1.25rem]">
                {opensearchQueryEvent.query}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Quality-gate retry — only shown when the gate fired a second pass */}
      {retryQueryEvent && (
        <div className="rounded-lg bg-white border border-[#9A3412] p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Filter className="w-4 h-4 text-[#9A3412] flex-shrink-0" />
              <span className="text-[1.25rem] font-semibold text-[#9A3412]">Quality-Gate Retry</span>
            </div>
            {retryQueryEvent.body && (
              <button
                onClick={() => setRetryDslOpen(true)}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[1.25rem] text-[#9A3412]/80 hover:text-[#9A3412] hover:bg-white border-2 border-[#9A3412] transition-colors"
                title="View retry query DSL"
                aria-label="View quality-gate retry OpenSearch query DSL"
              >
                <Eye className="w-3.5 h-3.5" />
                DSL
              </button>
            )}
          </div>
          <div className="text-[1.25rem] text-[var(--color-stage-ink-muted)]">
            <span className="text-[var(--color-stage-ink-soft)]">Alpha (after retry):</span>{' '}
            <span className="text-[#9A3412]">{(retryQueryEvent.alpha * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}

      <DslViewerModal
        isOpen={hybridDslOpen}
        title="Hybrid query DSL"
        subtitle={`Intent: ${opensearchQueryEvent?.intent ?? '—'} · alpha ${((opensearchQueryEvent?.alpha ?? 0) * 100).toFixed(0)}%`}
        body={opensearchQueryEvent?.body ?? null}
        index={opensearchQueryEvent?.index}
        params={opensearchQueryEvent?.params}
        onClose={() => setHybridDslOpen(false)}
      />
      <DslViewerModal
        isOpen={retryDslOpen}
        title="Quality-gate retry DSL"
        subtitle={`alpha ${((retryQueryEvent?.alpha ?? 0) * 100).toFixed(0)}%`}
        body={retryQueryEvent?.body ?? null}
        index={retryQueryEvent?.index}
        params={retryQueryEvent?.params}
        onClose={() => setRetryDslOpen(false)}
      />

      {/* Search status banner — retriever card only. Label reflects whether
          hybrid retrieval ran or whether the `hybrid` toggle forced pure BM25. */}
      {mode === 'retriever' && (() => {
        const hybridOn = opensearchQueryEvent?.optimizations?.hybrid !== false
        const searchLabel = hybridOn ? 'Hybrid search' : 'Lexical (BM25) search'
        if (searchStatus === 'running') {
          return (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border-2 border-[#5B21B6] border border-[#5B21B6] text-[1.375rem]">
              <Loader2 className="w-4 h-4 text-[#5B21B6] animate-spin" />
              <span className="text-[#5B21B6]">{searchLabel} in progress</span>
            </div>
          )
        }
        if (searchStatus === 'done') {
          return (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border-2 border-[#5B21B6] border border-[#5B21B6] text-[1.375rem]">
              <span className="text-[#5B21B6]">✓</span>
              <span className="text-[#5B21B6]">{searchLabel} complete</span>
            </div>
          )
        }
        return null
      })()}

      {/* Reranker status banner — reranker card only. */}
      {mode === 'reranker' && rerankerStatus === 'running' && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border-2 border-[#3730A3] border border-[#3730A3] text-[1.375rem]">
          <Loader2 className="w-4 h-4 text-[#3730A3] animate-spin" />
          <span className="text-[#3730A3]">Reranking results</span>
        </div>
      )}

      {mode === 'reranker' && rerankerStatus === 'done' && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border-2 border-[#3730A3] border border-[#3730A3] text-[1.375rem]">
          <span className="text-[#3730A3]">✓</span>
          <span className="text-[#3730A3]">Reranking complete</span>
        </div>
      )}
      {/* Show reranked documents if available */}
      {documents && documents.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">Reranked Results</span>
            <span className="text-[1.25rem] text-[#5B21B6]">
              {documents.length} documents
            </span>
          </div>

          <div className="space-y-2">
            {documents.map((doc, index) => {
              const isExpanded = expandedDocs.has(index)

              return (
                <div
                  key={index}
                  className="bg-[var(--color-stage-raised)] rounded-lg p-3 space-y-2 min-w-0"
                >
                  {/* Header with rank and score */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className="w-6 h-6 flex-shrink-0 rounded bg-white border-2 border-[#5B21B6] text-[#5B21B6] flex items-center justify-center text-[1.25rem] font-medium">
                        {doc.rank}
                      </span>
                      <FileText className="w-4 h-4 flex-shrink-0 text-[var(--color-stage-ink-soft)]" />
                      {doc.url ? (
                        <a
                          href={doc.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[1.375rem] text-[#1E40AF] break-all min-w-0 inline-flex items-center gap-1"
                        >
                          {doc.url}
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      ) : (
                        <span className="text-[1.375rem] text-[var(--color-stage-ink-muted)] break-all min-w-0">
                          {doc.source}
                        </span>
                      )}
                    </div>

                    {/* Rank change indicator */}
                    <div className="flex items-center gap-2">
                      {doc.rank_change !== 0 && (
                        <span
                          className={clsx(
                            'flex items-center text-[1.25rem]',
                            doc.rank_change > 0 ? 'text-[#065F46]' : 'text-[#991B1B]'
                          )}
                        >
                          {doc.rank_change > 0 ? (
                            <>
                              <ArrowUp className="w-3 h-3" />
                              {doc.rank_change}
                            </>
                          ) : (
                            <>
                              <ArrowDown className="w-3 h-3" />
                              {Math.abs(doc.rank_change)}
                            </>
                          )}
                        </span>
                      )}
                      {doc.rank_change === 0 && (
                        <span className="flex items-center text-[1.25rem] text-[var(--color-stage-ink-soft)]">
                          <Minus className="w-3 h-3" />
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Score bar — raw reranker score (0.0–1.0). The fill width
                      stays in % since CSS widths are percent-based, but the
                      label shows the unmodified score so it lines up with the
                      OpenSearch retrieval scores shown elsewhere. */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[1.25rem]">
                      <span className="text-[var(--color-stage-ink-soft)]">Reranker Score</span>
                      <span className="text-[#5B21B6] font-mono">{doc.score.toFixed(3)}</span>
                    </div>
                    <div className="score-bar">
                      <div
                        className="score-bar-fill bg-gradient-to-r from-purple-600 to-purple-400"
                        style={{ width: `${Math.max(0, Math.min(1, doc.score)) * 100}%` }}
                      />
                    </div>
                  </div>

                  {/* Snippet - collapsed view */}
                  {!isExpanded && (
                    <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] line-clamp-2">
                      {doc.snippet}
                    </p>
                  )}

                  {/* Full content - expanded view */}
                  {isExpanded && (
                    <div className="max-h-48 overflow-y-auto rounded bg-[var(--color-stage-raised)] p-3 border border-[var(--color-stage-border)]">
                      <div className="text-[1.25rem] text-[var(--color-stage-ink-muted)] space-y-2">
                        {doc.snippet && <p className="whitespace-pre-wrap">{doc.snippet}</p>}
                      </div>
                    </div>
                  )}

                  {/* Toggle button */}
                  <button
                    onClick={() => toggleDocExpansion(index)}
                    className="w-full flex items-center justify-center gap-1 text-[1.25rem] text-[#5B21B6] hover:text-[#5B21B6] hover:bg-white border-2 border-[#5B21B6] rounded py-1 transition-colors"
                  >
                    {isExpanded ? (
                      <>
                        <ChevronUp className="w-3 h-3" />
                        View less
                      </>
                    ) : (
                      <>
                        <ChevronDown className="w-3 h-3" />
                        View more
                      </>
                    )}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Show raw candidates if no reranked results */}
      {!documents && candidates.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">Search Candidates</span>
            <span className="text-[1.25rem] text-[#5B21B6]">
              {candidates.length} found
            </span>
          </div>

          <div className="space-y-2 max-h-60 overflow-y-auto">
            {candidates.slice(0, 6).map((candidate, index) => (
              <div
                key={index}
                className="bg-[var(--color-stage-raised)] rounded-lg p-2 text-[1.25rem] min-w-0"
              >
                <div className="flex items-center gap-2 mb-1 min-w-0">
                  <FileText className="w-3 h-3 flex-shrink-0 text-[var(--color-stage-ink-soft)]" />
                  <span className="text-[var(--color-stage-ink-muted)] break-all min-w-0">
                    {candidate.source}
                  </span>
                </div>
                <p className="text-[var(--color-stage-ink-soft)] line-clamp-2">
                  {candidate.snippet}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Explanation */}
      <div className="text-[1.25rem] text-[var(--color-stage-ink-soft)] border-t border-[var(--color-stage-border)] pt-3">
        <p>
          <strong>Hybrid search</strong> combines BM25 (keyword) and vector similarity.
          {rerankerType === 'cross-encoder' ? (
            <>
              {' '}The <strong>reranker</strong> (local cross-encoder) then scores
              each document for relevance offline, with no added API latency.
            </>
          ) : rerankerType ? (
            <>
              {' '}The <strong>reranker</strong> (Gemini) then scores each document
              for relevance using LLM-based semantic scoring.
            </>
          ) : (
            <> The <strong>reranker</strong> then scores each document for relevance.</>
          )}
        </p>
      </div>
    </div>
  )
}
