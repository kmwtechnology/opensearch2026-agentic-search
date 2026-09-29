/**
 * PipelineSummaryCard
 *
 * Renders the end-of-pipeline summary emitted as `PipelineSummaryEvent`: a
 * self-referential confidence proxy (top-1 reranker score, score gap, score
 * variance, rank-change count), the LLM-as-judge generation row, and a
 * per-stage latency table.
 *
 * The card is silent when no PipelineSummaryEvent has been received
 * (e.g. pipeline still running, summary intent, or first load).
 */

import { useState } from 'react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type {
  ConfidenceLabel,
  FlaggedClaim,
  GenerationJudgment,
  GenerationVerdict,
  HallucinationCategory,
  LatencyStage,
  PipelineSummaryEvent,
} from '../../types/events'

const CATEGORY_TONE: Record<
  HallucinationCategory,
  { label: string; chip: string; tooltip: string }
> = {
  fabrication: {
    label: 'Fabrication',
    chip: 'bg-white border-2 border-[#9F1239] text-[#9F1239] border-[#9F1239]',
    tooltip:
      'Outright wrong fact (e.g. "Made in USA" when the product\'s FACTS say nothing of the sort). Triggers auto-correction retry.',
  },
  cross_product_bleed: {
    label: 'Cross-product bleed',
    chip: 'bg-white border-2 border-[#9F1239] text-[#9F1239] border-[#9F1239]',
    tooltip:
      'A fact transferred from one retrieved product to a different one. Triggers auto-correction retry.',
  },
  inference: {
    label: 'Inference',
    chip: 'bg-white border-2 border-[#9A3412] text-[#9A3412] border-[#9A3412]',
    tooltip:
      'Paraphrase or over-claim from the source. Surfaced for review but does NOT trigger the ~20s retry.',
  },
  overreach: {
    label: 'Overreach',
    chip: 'bg-white border-2 border-[#9A3412] text-[#9A3412] border-[#9A3412]',
    tooltip:
      'A general claim beyond what is grounded. Surfaced for review but does NOT trigger the ~20s retry.',
  },
}

const RETRY_WORTHY_CATEGORIES: ReadonlySet<HallucinationCategory> = new Set([
  'fabrication',
  'cross_product_bleed',
])

function partitionFlags(flags: readonly FlaggedClaim[]): {
  hallucinated: FlaggedClaim[]
  overreached: FlaggedClaim[]
} {
  const hallucinated: FlaggedClaim[] = []
  const overreached: FlaggedClaim[] = []
  for (const f of flags) {
    if (RETRY_WORTHY_CATEGORIES.has(f.category)) hallucinated.push(f)
    else overreached.push(f)
  }
  return { hallucinated, overreached }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n: number | null | undefined, digits = 3): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

function fmtMs(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${Math.round(n)}ms`
}

const STAGE_LABEL: Record<LatencyStage['stage'], string> = {
  hybrid: 'Hybrid (vec+BM25)',
  reranked: 'Reranked',
}

const VERDICT_TONE: Record<GenerationVerdict, { chip: string; label: string }> = {
  llm_better: {
    chip: 'bg-white border-2 border-[#065F46] text-[#065F46] border-[#065F46]',
    label: 'LLM judged BETTER',
  },
  tied: {
    chip: 'bg-[var(--color-stage-raised)]/60 text-[var(--color-stage-ink)] border-[var(--color-stage-border)]',
    label: 'Tied',
  },
  llm_worse: {
    chip: 'bg-white border-2 border-[#9F1239] text-[#9F1239] border-[#9F1239]',
    label: 'LLM judged WORSE',
  },
}

const CONFIDENCE_TONE: Record<ConfidenceLabel, { dot: string; chip: string; text: string }> = {
  high: {
    dot: 'bg-emerald-400',
    chip: 'bg-white border-2 border-[#065F46] text-[#065F46] border-[#065F46]',
    text: 'text-[#065F46]',
  },
  medium: {
    dot: 'bg-amber-400',
    chip: 'bg-white border-2 border-[#9A3412] text-[#9A3412] border-[#9A3412]',
    text: 'text-[#9A3412]',
  },
  low: {
    dot: 'bg-[#9F1239]',
    chip: 'bg-white border-2 border-[#9F1239] text-[#9F1239] border-[#9F1239]',
    text: 'text-[#9F1239]',
  },
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCell({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5 text-center min-w-0">
      <span className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)] truncate" title={hint}>
        {label}
      </span>
      <span className="font-mono text-[1.375rem] text-[var(--color-stage-ink)] tabular-nums" title={hint}>
        {value}
      </span>
    </div>
  )
}

function LatencyTable({ rows }: { rows: LatencyStage[] }) {
  return (
    <div className="space-y-1">
      <div className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)] px-1">
        Stage latency
      </div>
      <div className="rounded-md border border-[var(--color-stage-border)] overflow-x-auto">
        <table className="w-full text-[1.25rem] table-fixed">
          <thead className="bg-[var(--color-stage-raised)]/60 text-[var(--color-stage-ink-soft)]">
            <tr>
              <th className="text-left px-2 py-1.5 font-normal w-[60%]">Stage</th>
              <th className="text-right px-2 py-1.5 font-normal w-[40%]">Latency</th>
            </tr>
          </thead>
          <tbody className="bg-[var(--color-stage-surface)]/40">
            {rows.map((row) => (
              <tr key={row.stage} className="border-t border-[var(--color-stage-border)]/40">
                <td className="px-2 py-1.5 text-[var(--color-stage-ink)] truncate" title={STAGE_LABEL[row.stage]}>
                  {STAGE_LABEL[row.stage]}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-[var(--color-stage-ink-muted)] tabular-nums">
                  {fmtMs(row.latency_ms)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function PipelineSummaryCard() {
  const summary = useObservabilityStore((s) => s.pipelineSummary)
  const [expanded, setExpanded] = useState(true)

  if (!summary) return null

  return (
    <div className="px-4 pb-4">
      <div className="rounded-lg border border-[var(--color-stage-border)] bg-[var(--color-stage-surface)]/60">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center justify-between w-full px-4 py-3 text-left"
          aria-expanded={expanded}
        >
          <div className="flex items-center gap-2">
            <span className="text-[1.375rem] font-semibold text-[var(--color-stage-ink)]">Pipeline Summary</span>
            <SummaryBadge summary={summary} />
          </div>
          <span className="text-[var(--color-stage-ink-soft)] text-[1.25rem]">{expanded ? '▾' : '▸'}</span>
        </button>
        {expanded && (
          <div className="px-4 pb-4 space-y-3">
            <p className="text-[1.25rem] text-[var(--color-stage-ink-muted)] leading-relaxed">
              Self-referential reranker confidence for{' '}
              <span className="text-[var(--color-stage-ink)] font-medium">"{summary.query}"</span>.
              <span className="text-[var(--color-stage-ink-soft)]"> (A heuristic over reranker scores, not an offline relevance metric.)</span>
            </p>
            <ConfidenceCard summary={summary} />
            {summary.generation && (
              <GenerationCard
                judgment={summary.generation}
                retried={!!summary.hallucination_retry_used}
                original={summary.original_generation}
              />
            )}
            <LatencyTable rows={summary.latency} />
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryBadge({ summary }: { summary: PipelineSummaryEvent }) {
  const tone = CONFIDENCE_TONE[summary.confidence.confidence_label]
  return (
    <span
      className={`text-[1.25rem] uppercase tracking-wide px-2 py-0.5 rounded-full border ${tone.chip}`}
    >
      proxy · {summary.confidence.confidence_label} confidence
    </span>
  )
}

function ConfidenceCard({ summary }: { summary: PipelineSummaryEvent }) {
  const c = summary.confidence
  const tone = CONFIDENCE_TONE[c.confidence_label]
  return (
    <div className="rounded-md border border-[var(--color-stage-border)] bg-[var(--color-stage-raised)]/40 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${tone.dot}`} />
        <span className={`text-[1.375rem] font-medium ${tone.text}`}>
          {c.confidence_label[0].toUpperCase() + c.confidence_label.slice(1)} confidence
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCell
          label="Top-1 score"
          value={fmt(c.top1_score, 3)}
          hint="Highest reranker score across the result set"
        />
        <MetricCell
          label="Top-1 gap"
          value={fmt(c.score_gap, 3)}
          hint="Difference between top-1 and top-2 — bigger is more decisive"
        />
        <MetricCell
          label="Variance"
          value={fmt(c.score_variance, 4)}
          hint="Score spread across top-k — wider is more discriminative"
        />
        <MetricCell
          label="Rank churn"
          value={`${c.rank_changes_count}`}
          hint="How many top-10 positions changed pre/post reranker"
        />
      </div>
    </div>
  )
}

function GenerationCard({
  judgment,
  retried,
  original,
}: {
  judgment: GenerationJudgment
  retried?: boolean
  original?: GenerationJudgment | null
}) {
  const tone = VERDICT_TONE[judgment.verdict]
  return (
    <div className="space-y-2">
      {/* Title + verdict chip wrap to two lines on narrow panels. */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-[1.25rem] uppercase tracking-wide text-[var(--color-stage-ink-soft)]">
          Generation (LLM-as-judge)
        </span>
        <div className="flex items-center gap-1.5 flex-wrap">
          {retried && (
            <span
              className="text-[1.25rem] uppercase tracking-wide px-2 py-0.5 rounded-full border whitespace-nowrap bg-white border-2 border-[#9A3412] text-[#9A3412] border-[#9A3412]"
              title={`Auto-corrected: faithfulness ${original?.faithfulness?.toFixed(2) ?? '?'} → ${judgment.faithfulness.toFixed(2)}`}
            >
              🔁 Auto-corrected
            </span>
          )}
          <span
            className={`text-[1.25rem] uppercase tracking-wide px-2 py-0.5 rounded-full border whitespace-nowrap ${tone.chip}`}
          >
            {tone.label}
          </span>
        </div>
      </div>
      <div className="rounded-md border border-[var(--color-stage-border)] bg-[var(--color-stage-raised)]/40 p-3 space-y-2.5">
        <p className="text-[1.25rem] text-[var(--color-stage-ink)] leading-snug italic break-words">
          “{judgment.pairwise_justification}”
        </p>
        {/* 2 cols by default → tighter packing on narrow panels; 4 cols at sm+
            so wide panels still get a single row. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-2">
          <MetricCell
            label="Faithful"
            value={fmt(judgment.faithfulness, 2)}
            hint="1.0 = every claim grounded in retrieved docs (no hallucinations)"
          />
          <MetricCell
            label="Relevance"
            value={fmt(judgment.answer_relevance, 2)}
            hint="How well the response addresses the user's query intent"
          />
          <MetricCell
            label="Citations"
            value={fmt(judgment.citation_accuracy, 2)}
            hint="If the response cites products, the citations match what it says about them"
          />
          <MetricCell
            label="Coverage"
            value={fmt(judgment.context_utilization, 2)}
            hint="Fraction of retrieved products meaningfully referenced"
          />
        </div>
        {judgment.hallucinations.length > 0 && (() => {
          const { hallucinated, overreached } = partitionFlags(judgment.hallucinations)
          const headerLabel =
            hallucinated.length > 0 && overreached.length > 0
              ? `${hallucinated.length} hallucinated / ${overreached.length} overreached`
              : hallucinated.length > 0
                ? `Hallucinations flagged (${hallucinated.length})`
                : `Overreaches flagged (${overreached.length})`
          const headerTone = hallucinated.length > 0 ? 'text-[#9F1239]' : 'text-[#9A3412]'
          return (
            <div className="border-t border-[var(--color-stage-border)] pt-2 space-y-1.5">
              <span
                className={`text-[1.25rem] uppercase tracking-wide ${headerTone}`}
                title="Red = fabrication / cross-product bleed (retry-worthy). Amber = inference / overreach (surfaced only, no retry)."
              >
                {headerLabel}
              </span>
              <ul className="text-[1.25rem] list-none space-y-1.5 break-words">
                {judgment.hallucinations.map((h, i) => {
                  const tone = CATEGORY_TONE[h.category]
                  const itemColor = RETRY_WORTHY_CATEGORIES.has(h.category)
                    ? 'text-[#9F1239]'
                    : 'text-[#9A3412]/90'
                  return (
                    <li key={i} className={itemColor}>
                      <span className="flex items-start gap-1.5">
                        <span
                          className={`flex-none text-[1.25rem] uppercase tracking-wide px-1.5 py-0.5 rounded-full border whitespace-nowrap ${tone.chip}`}
                          title={tone.tooltip}
                        >
                          {tone.label}
                        </span>
                        <span className="leading-snug">{h.claim}</span>
                      </span>
                      {h.reasoning && (
                        <span className="block ml-[6.5rem] text-[1.25rem] text-[var(--color-stage-ink-soft)] italic leading-snug">
                          {h.reasoning}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
