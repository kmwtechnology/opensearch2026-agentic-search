/**
 * MessageList - Displays chat messages with auto-scroll.
 */

import { useEffect, useRef, useMemo, useState } from 'react'
import { useChatStore } from '../../stores/chatStore'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { nodeStyle } from '../NarratorPanel/nodeStyle'
import { Message } from './Message'

// Mirror of pipeline_nodes.py's _CORRECTION_SIGNAL_PHRASES. The backend runs
// this same cheap keyword gate before it will even offer the correction tool,
// so without it here EVERY refinement/follow_up turn claims a tag dispute is
// being evaluated — e.g. arc 1 turn 2 ("only size 10") would show "Checking
// whether a tag needs correcting" while the backend went straight to answer
// generation. That is the #106 failure mode (a specific, confident, wrong
// label on ordinary latency), so the status text has to respect the same gate.
// Keep in sync with the backend list; a drift here costs a mislabelled status
// card, never a wrong answer.
const CORRECTION_SIGNAL_PHRASES = [
  "that's not",
  'thats not',
  "that isn't",
  'that is not',
  "isn't really",
  "isn't actually",
  "doesn't look",
  'does not look',
  'not really',
  'actually',
  'mistag',
  'miscategor',
  'incorrectly tagged',
  'wrong color',
  'should be tagged',
  'tagged wrong',
  "that's wrong",
  'thats wrong',
  'not correct',
]

function looksLikeCorrection(userQuery: string | undefined): boolean {
  if (!userQuery) return false
  const q = userQuery.toLowerCase()
  return CORRECTION_SIGNAL_PHRASES.some((phrase) => q.includes(phrase))
}

export function MessageList() {
  const { messages, streamingContent, isProcessing } = useChatStore()
  const { currentNode, steps } = useObservabilityStore()
  // Live sub-step detail the backend already emits — embedding the query,
  // running the two searches, fusing them, scoring each candidate. Without
  // these the panel sits on one label for ten seconds and looks stuck.
  const searchProgressMessage = useObservabilityStore((s) => s.searchProgressMessage)
  const rerankerProgressMessage = useObservabilityStore((s) => s.rerankerProgressMessage)
  const rerankerProgress = useObservabilityStore((s) => s.rerankerProgress)
  const intentClassification = useObservabilityStore((s) => s.intentClassification)
  const queryEvaluation = useObservabilityStore((s) => s.queryEvaluation)
  const qualityGate = useObservabilityStore((s) => s.qualityGate)
  const searchCandidates = useObservabilityStore((s) => s.searchCandidates)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // Elapsed seconds for the in-progress status. The model can spend ten-plus
  // seconds composing before its first token arrives, and a status line that
  // holds one label for that long reads as a hung app — a ticking number is
  // the difference between "working" and "stuck" (#103).
  const [elapsed, setElapsed] = useState(0)
  const scrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Mirrors the gates in pipeline_nodes.py's agent_node that decide whether
  // the agent's first model call is a genuine tool-offer/correction check,
  // versus skipping straight to the real answer call: a correction check
  // only runs on refinement/follow_up turns, and an enrichment check only
  // runs when retrieval came back empty (attribute_filter with zero
  // candidates) or the quality gate retried and still scored below the
  // relevance floor. Most turns hit neither gate, so unconditionally
  // labelling the pre-token wait "Checking whether a tool is needed" was
  // misleading on the common case — a demo turn spent the whole wait on
  // ordinary answer-generation latency with no tool check in flight (#106).
  // This is a frontend-only approximation (no backend event marks gate
  // eligibility yet), not a byte-for-byte replay of the backend condition.
  //
  // Returns WHICH gate is actually in flight (or null if none), so the
  // status line can say WHY a tool check is happening instead of just THAT
  // one is (#142 — "it just jumps to reingestion without telling the user
  // why"). Order matters: mirrors the backend's own check order (correction
  // signal first, then the two enrichment-gap conditions).
  type ToolCheckReason = 'correction' | 'zero-result-filter' | 'low-score-retry'
  const getToolCheckReason = (): ToolCheckReason | null => {
    const intent = intentClassification?.intent
    if (
      (intent === 'refinement' || intent === 'follow_up') &&
      looksLikeCorrection(intentClassification?.user_query)
    ) {
      return 'correction'
    }
    if (intent === 'attribute_filter' && searchCandidates.length === 0) return 'zero-result-filter'
    if (qualityGate?.triggered && qualityGate.max_score < 0.1) return 'low-score-retry'
    return null
  }

  // Headline per tool-check reason (#142) — distinct from the generic
  // "Checking whether a tool is needed" this replaces, so the SAME wait
  // reads differently for "you disputed a tag" (color correction, Arc 2)
  // vs. "nothing matched this filter" (a gap — waterproof or, in
  // principle, an unmapped color) rather than one label covering both.
  const TOOL_CHECK_HEADLINE: Record<ToolCheckReason, string> = {
    correction: 'Checking whether a tag needs correcting',
    'zero-result-filter': 'Checking whether the catalog is missing this attribute',
    'low-score-retry': 'Checking whether the catalog is missing something',
  }

  // Map node IDs to user-friendly display names
  const getNodeDisplayName = (node: string): string => {
    // Same vocabulary as the narrator panel, so the chat and the right-hand
    // column describe the same step in the same words.
    const toolCheckReason = getToolCheckReason()
    const names: Record<string, string> = {
      intent_classifier: 'Working out what you asked',
      query_evaluator: 'Deciding how literally to read it',
      retriever: 'Searching the catalog',
      reranker: 'Re-reading the best candidates',
      quality_gate: 'Checking the results are good enough',
      // Split deliberately — see getCurrentStepSummary. The agent node makes
      // a second, tool-offer model call only when getToolCheckReason() is
      // non-null; otherwise it skips straight to the answer call, so the
      // label must reflect which case this turn is in (#106).
      agent: streamingContent
        ? 'Writing the answer'
        : toolCheckReason
          ? TOOL_CHECK_HEADLINE[toolCheckReason]
          : 'Thinking through the answer',
      llm_judge: 'Checking the answer against the sources',
    }
    return names[node] || 'Working'
  }

  // Most recent applied-filter summary the retriever reported (e.g. "color:
  // yellow", "waterproof: waterproof") — used to name what came up empty or
  // mis-mapped, instead of leaving the reader to guess.
  const getLastFilterSummary = (): string | null => {
    for (let i = steps.length - 1; i >= 0; i--) {
      for (let j = steps[i].events.length - 1; j >= 0; j--) {
        const event = steps[i].events[j]
        if (event.type === 'opensearch_query' && event.filter_summary) {
          return event.filter_summary
        }
      }
    }
    return null
  }

  // A second line of detail under the stage name, so something visibly moves
  // for the whole wait rather than one static label.
  const getCurrentStepSummary = (): string | null => {
    // Live progress beats anything derived after the fact.
    if (currentNode === 'reranker') {
      if (rerankerProgress > 0) {
        return `${rerankerProgressMessage || 'Scoring candidates'} — ${Math.round(rerankerProgress * 100)}%`
      }
      return rerankerProgressMessage || 'Scoring each candidate against your question'
    }
    if (currentNode === 'retriever' && searchProgressMessage) {
      return searchProgressMessage
    }

    if (currentNode === 'query_evaluator' && intentClassification?.intent) {
      return `Read as "${intentClassification.intent}"`
    }
    // The agent node's first model call only exists when getToolCheckReason()
    // is non-null \u2014 see getNodeDisplayName. When it does run, its tokens are
    // suppressed on purpose (INTERNAL_LLM_TAG), because they are the model
    // reasoning out loud, not the reply, and only when that resolves does the
    // visible answer begin. When it's not eligible, the wait is ordinary
    // answer-generation latency (#106).
    if (currentNode === 'agent') {
      if (!streamingContent) {
        const reason = getToolCheckReason()
        if (!reason) return 'Composing a response from the retrieved matches'
        // #142: name the actual condition instead of a generic "checking" \u2014
        // this is the one place a shopper sees BEFORE the agent decides
        // whether to write to the catalog, so it's the one place that has
        // to say why, not just that.
        if (reason === 'correction') {
          return "You may be disputing a tag from an earlier answer \u2014 deciding whether to correct it."
        }
        if (reason === 'zero-result-filter') {
          const filter = getLastFilterSummary()
          return filter
            ? `No products matched ${filter} \u2014 deciding whether to teach the catalog this term.`
            : 'No products matched that filter \u2014 deciding whether the catalog is missing this term.'
        }
        return 'Nothing scored well even after retrying \u2014 deciding whether this is a catalog gap.'
      }
      if (queryEvaluation) {
        return `Using the top matches at \u03b1 ${queryEvaluation.alpha.toFixed(2)}`
      }
    }

    if (!currentNode || !steps.length) return null
    const currentStep = steps.find((s) => s.node === currentNode)
    if (!currentStep || !currentStep.events.length) return null

    const latestEvent = currentStep.events[currentStep.events.length - 1]
    if (latestEvent.type === 'hybrid_search_result') {
      return `Found ${latestEvent.candidate_count} candidates`
    }
    if (latestEvent.type === 'opensearch_query' && latestEvent.filter_summary) {
      return `Filtering on ${latestEvent.filter_summary}`
    }
    return null
  }

  // State is only ever set from the interval callback — setState directly in
  // an effect body trips react-hooks/set-state-in-effect, which CI fails on.
  // The first tick lands 100ms in, so the counter effectively starts at zero
  // without needing an explicit reset.
  const elapsedStartRef = useRef<number | null>(null)
  useEffect(() => {
    if (!isProcessing) {
      elapsedStartRef.current = null
      return
    }
    elapsedStartRef.current = Date.now()
    const id = window.setInterval(() => {
      const startedAt = elapsedStartRef.current
      if (startedAt !== null) setElapsed((Date.now() - startedAt) / 1000)
    }, 100)
    return () => window.clearInterval(id)
  }, [isProcessing])

  // Auto-scroll to bottom on new messages (throttled to ~60fps with requestAnimationFrame)
  useEffect(() => {
    // Cancel any pending scroll request
    if (scrollTimeoutRef.current) {
      cancelAnimationFrame(scrollTimeoutRef.current)
    }

    // Schedule scroll on next animation frame (throttles to ~60fps)
    scrollTimeoutRef.current = requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    })

    // Cleanup on unmount or when dependencies change
    return () => {
      if (scrollTimeoutRef.current) {
        cancelAnimationFrame(scrollTimeoutRef.current)
      }
    }
  }, [messages, streamingContent])

  // Show streaming content in the last message if it's an assistant message (memoized)
  const displayMessages = useMemo(() => {
    const withStreaming = messages.map((msg, index) => {
      if (
        index === messages.length - 1 &&
        msg.role === 'assistant' &&
        msg.isStreaming &&
        streamingContent
      ) {
        return { ...msg, content: streamingContent }
      }
      return msg
    })
    // Drop a trailing assistant bubble that has nothing in it yet.
    //
    // One is created the moment generation starts, but the first token can be
    // seconds away — and an empty bubble also SUPPRESSED the status line
    // below, so the whole retrieval-and-rerank phase showed as a blank box
    // with a blinking cursor and no explanation (#103). Now the status stays
    // up until there is actually something to show.
    const last = withStreaming[withStreaming.length - 1]
    if (last && last.role === 'assistant' && last.isStreaming && !last.content) {
      return withStreaming.slice(0, -1)
    }
    return withStreaming
  }, [messages, streamingContent])

  if (messages.length === 0) {
    // Deliberately almost empty (#103). This used to be a feature tour —
    // a product blurb, four intent categories and eight sample queries. On a
    // projected demo that is a wall of 16px text the audience reads instead
    // of listening, and every word of it is either said out loud by the
    // presenter or already shown in the demo header.
    return (
      <div className="flex h-full items-center justify-center px-6">
        <p className="text-center text-[length:var(--text-stage-lead)] font-semibold text-[var(--color-stage-ink-soft)]">
          Ask a question to begin.
        </p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-4 py-4 space-y-4" role="log" aria-live="polite" aria-label="Chat messages">
      {displayMessages.map((message) => (
        <Message key={message.id} message={message} />
      ))}

      {/* Show typing indicator when processing but no streaming content yet */}
      {isProcessing && !streamingContent && (() => {
        /* The pipeline runs intent -> evaluate -> search -> rerank -> gate
           BEFORE a single token is generated, which is most of the wait. Show
           the stage, a live detail line, and the SAME icon and color the
           narrator uses for that stage — so the two columns read as one
           system describing one moment. */
        const style = nodeStyle(currentNode)
        const { Icon } = style
        const detail = getCurrentStepSummary()
        return (
          <div
            className="flex items-center gap-4 rounded-2xl border-2 px-6 py-4"
            style={{ borderColor: style.fg, backgroundColor: style.tint }}
            aria-live="polite"
            aria-label="Agent processing"
          >
            <span
              className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border-2 bg-white"
              style={{ borderColor: style.fg }}
              aria-hidden="true"
            >
              <Icon style={{ color: style.fg }} strokeWidth={2.5} size={24} />
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span
                className="text-[1.5rem] font-bold leading-tight"
                style={{ color: style.fg }}
              >
                {currentNode ? getNodeDisplayName(currentNode) : 'Thinking'}
              </span>
              {detail && (
                <span className="text-[1.375rem] font-medium leading-snug text-[var(--color-stage-ink-muted)]">
                  {detail}
                </span>
              )}
            </span>
            <span className="ml-auto flex flex-shrink-0 items-center gap-3">
              <span
                className="font-mono text-[1.375rem] font-semibold tabular-nums"
                style={{ color: style.fg }}
              >
                {elapsed.toFixed(1)}s
              </span>
              <span
                className="h-3.5 w-3.5 animate-pulse rounded-full"
                style={{ backgroundColor: style.fg }}
                aria-hidden="true"
              />
            </span>
          </div>
        )
      })()}

      <div ref={messagesEndRef} />
    </div>
  )
}
