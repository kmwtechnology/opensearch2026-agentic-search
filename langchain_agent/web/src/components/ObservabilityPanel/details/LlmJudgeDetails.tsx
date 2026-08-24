/**
 * Step-level details for the llm_judge node.
 *
 * Mirrors what the Pipeline Quality Summary card already renders, just at
 * the per-step level so collapsing/reopening the LLM Judge step keeps a
 * meaningful summary visible.
 */

import { useObservabilityStore } from '../../../stores/observabilityStore'
import { useOptimizationsStore } from '../../../stores/optimizationsStore'
import type {
  FlaggedClaim,
  GenerationJudgment,
  HallucinationCategory,
  ObservabilityStep,
} from '../../../types/events'

const RETRY_WORTHY_CATEGORIES: ReadonlySet<HallucinationCategory> = new Set([
  'fabrication',
  'cross_product_bleed',
])

function countByTier(flags: readonly FlaggedClaim[]): {
  hallucinated: number
  overreached: number
} {
  let hallucinated = 0
  let overreached = 0
  for (const f of flags) {
    if (RETRY_WORTHY_CATEGORIES.has(f.category)) hallucinated += 1
    else overreached += 1
  }
  return { hallucinated, overreached }
}

function fmt(n: number, digits = 2): string {
  return n.toFixed(digits)
}

const VERDICT_TONE: Record<
  GenerationJudgment['verdict'],
  { label: string; chip: string }
> = {
  llm_better: {
    label: 'LLM judged BETTER',
    chip: 'bg-emerald-900/40 text-emerald-200 border-emerald-700/50',
  },
  tied: {
    label: 'Tied',
    chip: 'bg-gray-800/60 text-gray-200 border-gray-600',
  },
  llm_worse: {
    label: 'LLM judged WORSE',
    chip: 'bg-rose-900/40 text-rose-200 border-rose-700/50',
  },
}

export function LlmJudgeDetails({ step }: { step?: ObservabilityStep }) {
  const summary = useObservabilityStore((s) => s.pipelineSummary)
  const isExecuting = useObservabilityStore((s) => s.isExecuting)
  const optimizations = useOptimizationsStore((s) => s.optimizations)
  const judgment = summary?.generation
  const original = summary?.original_generation
  const retried = !!summary?.hallucination_retry_used

  // Flash-prevention: the llm_judge step finishes BEFORE the
  // PipelineSummaryEvent is emitted (the event is sent at the very end of
  // process_message after the graph stream closes). For ~1-2s the step is
  // "complete" but summary?.generation is still null. Treat the entire
  // window where the agent is still executing as "in progress" so we don't
  // briefly flash a "no result" message.
  if (!judgment) {
    if (step?.status === 'running' || isExecuting) {
      return (
        <div className="text-sm text-gray-400 italic">
          Judging… on a clean response this is ~1–2s. If hallucinations get
          flagged, an auto-correction retry kicks in and the total can run
          20–30s.
        </div>
      )
    }
    const llmOn = optimizations.llm
    const judgeOn = optimizations.llm_judge
    if (!llmOn) {
      return (
        <div className="text-sm text-gray-500">
          Judge needs <code>llm</code> on (no synthesized response to compare).
        </div>
      )
    }
    if (!judgeOn) {
      return (
        <div className="text-sm text-gray-500">
          Judge toggle off — turn on <code>llm_judge</code> for the next query.
        </div>
      )
    }
    return (
      <div className="text-sm text-gray-500">
        No judge result captured for this turn. Send a fresh query.
      </div>
    )
  }

  // Step view — compact one-line summary. Full justification, scores, and
  // hallucinations live in the Pipeline Quality Summary card below to avoid
  // duplicating the same content twice in the panel.
  const tone = VERDICT_TONE[judgment.verdict]
  const faithDelta =
    original && retried ? judgment.faithfulness - original.faithfulness : null

  return (
    <div className="space-y-1 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border whitespace-nowrap ${tone.chip}`}
        >
          {tone.label}
        </span>
        {retried && (
          <span
            className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border bg-amber-900/40 text-amber-200 border-amber-700/50"
            title={
              original
                ? `Auto-corrected after the original response was flagged. Faithfulness ${fmt(original.faithfulness)} → ${fmt(judgment.faithfulness)}.`
                : 'Auto-corrected after the original response was flagged.'
            }
          >
            🔁 Auto-corrected
            {faithDelta !== null && Math.abs(faithDelta) >= 0.005 && (
              <span className="ml-1 tabular-nums">
                {fmt(original!.faithfulness)} → {fmt(judgment.faithfulness)}
              </span>
            )}
          </span>
        )}
        {judgment.hallucinations.length > 0 && (() => {
          const { hallucinated, overreached } = countByTier(judgment.hallucinations)
          if (hallucinated > 0 && overreached > 0) {
            return (
              <>
                <span
                  className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border bg-rose-900/40 text-rose-200 border-rose-700/50"
                  title="Fabrication / cross-product bleed — retry-worthy."
                >
                  {hallucinated} hallucinated
                </span>
                <span
                  className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border bg-amber-900/40 text-amber-200 border-amber-700/50"
                  title="Inference / overreach — surfaced only, no retry."
                >
                  {overreached} overreached
                </span>
              </>
            )
          }
          if (hallucinated > 0) {
            return (
              <span
                className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border bg-rose-900/40 text-rose-200 border-rose-700/50"
                title="Fabrication / cross-product bleed — retry-worthy."
              >
                {hallucinated} flagged
              </span>
            )
          }
          return (
            <span
              className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border bg-amber-900/40 text-amber-200 border-amber-700/50"
              title="Inference / overreach — surfaced only, no retry."
            >
              {overreached} overreached
            </span>
          )
        })()}
      </div>
      <p className="text-xs text-gray-500">
        Full breakdown in the Pipeline Quality Summary card below.
      </p>
    </div>
  )
}
