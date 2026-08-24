/**
 * PipelineSummaryCard
 *
 * Renders the end-of-pipeline retrieval-quality summary emitted as
 * `PipelineSummaryEvent`. Two layouts:
 *
 *  - Ground-truth: BM25 → Hybrid → Reranked metric progression with
 *    NDCG@10 / MRR / Recall@20 / Precision@10. Latency cost-benefit
 *    table at the bottom.
 *  - Fallback: self-referential confidence proxy (top-1 reranker score,
 *    score gap, score variance, rank-change count) plus the same
 *    latency table without lift numbers.
 *
 * The card is silent when no PipelineSummaryEvent has been received
 * (e.g. pipeline still running, summary intent, or first load).
 */

import { useState } from 'react'
import { Eye } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type {
  ConfidenceLabel,
  FlaggedClaim,
  GenerationJudgment,
  GenerationVerdict,
  HallucinationCategory,
  LatencyStage,
  OpenSearchQueryEvent,
  PipelineSummaryEvent,
  StageMetrics,
} from '../../types/events'
import { DslViewerModal } from './DslViewerModal'

const CATEGORY_TONE: Record<
  HallucinationCategory,
  { label: string; chip: string; tooltip: string }
> = {
  fabrication: {
    label: 'Fabrication',
    chip: 'bg-rose-900/40 text-rose-200 border-rose-700/50',
    tooltip:
      'Outright wrong fact (e.g. "Made in USA" when the product\'s FACTS say nothing of the sort). Triggers auto-correction retry.',
  },
  cross_product_bleed: {
    label: 'Cross-product bleed',
    chip: 'bg-rose-900/40 text-rose-200 border-rose-700/50',
    tooltip:
      'A fact transferred from one retrieved product to a different one. Triggers auto-correction retry.',
  },
  inference: {
    label: 'Inference',
    chip: 'bg-amber-900/40 text-amber-200 border-amber-700/50',
    tooltip:
      'Paraphrase or over-claim from the source. Surfaced for review but does NOT trigger the ~20s retry.',
  },
  overreach: {
    label: 'Overreach',
    chip: 'bg-amber-900/40 text-amber-200 border-amber-700/50',
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

function fmtLift(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n > 0) return `+${fmt(n, 3)}`
  return fmt(n, 3)
}

const STAGE_LABEL: Record<LatencyStage['stage'], string> = {
  stock_bm25: 'Stock BM25',
  bm25: 'Your BM25',
  hybrid: 'Hybrid (vec+BM25)',
  reranked: 'Reranked',
}

// Subset of optimization keys that reshape the BM25 multi_match query.
// When any of these are off, "Your BM25" reflects a degraded build vs Stock.
const BM25_TUNING_KEYS = ['fuzzy', 'synonyms', 'phonetic', 'phrase_boost', 'field_boost'] as const

const VERDICT_TONE: Record<GenerationVerdict, { chip: string; label: string }> = {
  llm_better: {
    chip: 'bg-emerald-900/40 text-emerald-200 border-emerald-700/50',
    label: 'LLM judged BETTER',
  },
  tied: {
    chip: 'bg-gray-800/60 text-gray-200 border-gray-600',
    label: 'Tied',
  },
  llm_worse: {
    chip: 'bg-rose-900/40 text-rose-200 border-rose-700/50',
    label: 'LLM judged WORSE',
  },
}

const CONFIDENCE_TONE: Record<ConfidenceLabel, { dot: string; chip: string; text: string }> = {
  high: {
    dot: 'bg-emerald-400',
    chip: 'bg-emerald-900/40 text-emerald-200 border-emerald-700/50',
    text: 'text-emerald-200',
  },
  medium: {
    dot: 'bg-amber-400',
    chip: 'bg-amber-900/40 text-amber-200 border-amber-700/50',
    text: 'text-amber-200',
  },
  low: {
    dot: 'bg-rose-400',
    chip: 'bg-rose-900/40 text-rose-200 border-rose-700/50',
    text: 'text-rose-200',
  },
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCell({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5 text-center min-w-0">
      <span className="text-[10px] uppercase tracking-wide text-gray-400 truncate" title={hint}>
        {label}
      </span>
      <span className="font-mono text-sm text-gray-100 tabular-nums" title={hint}>
        {value}
      </span>
    </div>
  )
}

function StageRow({
  name,
  stage,
  badge,
  rightAdornment,
}: {
  name: string
  stage: StageMetrics | null | undefined
  badge?: React.ReactNode
  rightAdornment?: React.ReactNode
}) {
  if (!stage) return null
  return (
    <div className="px-3 py-2 rounded-md bg-gray-800/40 border border-gray-700/50 space-y-1.5">
      {/* Title row — name + degradation badge on the left, judged-count chip on
          the right. flex-wrap so they stack on very narrow panels. */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-sm font-medium text-gray-100 flex items-center gap-1.5">
          {name}
          {badge}
        </span>
        <span className="flex items-center gap-2">
          {rightAdornment}
          <span
            className="text-[10px] uppercase tracking-wide text-gray-500 whitespace-nowrap"
            title={`${stage.judged_count} of the top-10 returned items had a ground-truth ESCI judgment`}
          >
            {stage.judged_count}/10 judged
          </span>
        </span>
      </div>
      {/* Metrics row — 4 evenly-sized cells. min-w-0 on the cells lets long
          numbers shrink with ellipsis instead of overflowing the card. */}
      <div className="grid grid-cols-4 gap-2">
        <MetricCell label="NDCG@10" value={fmt(stage.ndcg10, 3)} />
        <MetricCell label="MRR" value={fmt(stage.mrr, 3)} />
        <MetricCell label="R@20" value={fmt(stage.recall20, 3)} hint="Recall@20" />
        <MetricCell label="P@10" value={fmt(stage.precision10, 3)} hint="Precision@10" />
      </div>
    </div>
  )
}

function LatencyTable({ rows }: { rows: LatencyStage[] }) {
  const hasGroundTruth = rows.some((r) => r.ndcg !== null && r.ndcg !== undefined)
  return (
    <div className="space-y-1">
      <div className="text-[11px] uppercase tracking-wide text-gray-400 px-1">
        Latency cost-benefit
      </div>
      <div className="rounded-md border border-gray-700/50 overflow-x-auto">
        <table className="w-full text-xs table-fixed">
          <thead className="bg-gray-800/60 text-gray-400">
            <tr>
              <th className="text-left px-2 py-1.5 font-normal w-[44%]">Stage</th>
              <th className="text-right px-2 py-1.5 font-normal w-[18%]">Latency</th>
              {hasGroundTruth && (
                <>
                  <th className="text-right px-2 py-1.5 font-normal w-[18%]">NDCG</th>
                  <th
                    className="text-right px-2 py-1.5 font-normal w-[20%]"
                    title="Marginal NDCG lift per 100ms vs the previous stage"
                  >
                    Lift / 100ms
                  </th>
                </>
              )}
            </tr>
          </thead>
          <tbody className="bg-gray-900/40">
            {rows.map((row) => (
              <tr key={row.stage} className="border-t border-gray-700/40">
                <td className="px-2 py-1.5 text-gray-200 truncate" title={STAGE_LABEL[row.stage]}>
                  {STAGE_LABEL[row.stage]}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-gray-300 tabular-nums">
                  {fmtMs(row.latency_ms)}
                </td>
                {hasGroundTruth && (
                  <>
                    <td className="px-2 py-1.5 text-right font-mono text-gray-300 tabular-nums">
                      {fmt(row.ndcg, 3)}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                        row.ndcg_lift_per_100ms !== null &&
                        row.ndcg_lift_per_100ms !== undefined &&
                        row.ndcg_lift_per_100ms > 0
                          ? 'text-emerald-300'
                          : row.ndcg_lift_per_100ms !== null &&
                              row.ndcg_lift_per_100ms !== undefined &&
                              row.ndcg_lift_per_100ms < 0
                            ? 'text-rose-300'
                            : 'text-gray-400'
                      }`}
                    >
                      {fmtLift(row.ndcg_lift_per_100ms)}
                    </td>
                  </>
                )}
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
  const steps = useObservabilityStore((s) => s.steps)
  const [expanded, setExpanded] = useState(true)
  const [bm25DslOpen, setBm25DslOpen] = useState(false)

  if (!summary) return null

  // Locate the BM25 baseline DSL body emitted by the retriever node. The
  // event is keyed by query_type so it survives a request that emits
  // multiple opensearch_query events.
  const retrieverStep = steps.find((s) => s.node === 'retriever')
  const bm25Event = (retrieverStep?.events ?? []).find(
    (e): e is OpenSearchQueryEvent =>
      e.type === 'opensearch_query' && (e as OpenSearchQueryEvent).query_type === 'bm25_baseline',
  )

  return (
    <div className="px-4 pb-4">
      <div className="rounded-lg border border-gray-700 bg-gray-900/60">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center justify-between w-full px-4 py-3 text-left"
          aria-expanded={expanded}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-100">Pipeline Quality Summary</span>
            <SummaryBadge summary={summary} />
          </div>
          <span className="text-gray-400 text-xs">{expanded ? '▾' : '▸'}</span>
        </button>
        {expanded && (
          <div className="px-4 pb-4 space-y-3">
            <SummaryHeadline summary={summary} />
            {summary.has_ground_truth ? (
              <div className="space-y-2">
                <StageRow name="Stock BM25" stage={summary.stock_bm25} />
                <StageRow
                  name="Your BM25"
                  stage={summary.bm25}
                  badge={<DegradedBadge optimizations={summary.optimizations} />}
                  rightAdornment={
                    bm25Event?.body ? (
                      <button
                        onClick={() => setBm25DslOpen(true)}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-yellow-300/80 hover:text-yellow-200 hover:bg-yellow-500/10 transition-colors"
                        title="View BM25 baseline DSL"
                        aria-label="View BM25 baseline OpenSearch query DSL"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        DSL
                      </button>
                    ) : undefined
                  }
                />
                <StageRow name="Hybrid" stage={summary.hybrid} />
                <StageRow name="Reranked" stage={summary.reranked} />
              </div>
            ) : (
              <ConfidenceCard summary={summary} />
            )}
            {summary.generation && (
              <GenerationCard
                judgment={summary.generation}
                retried={!!summary.hallucination_retry_used}
                original={summary.original_generation}
              />
            )}
            <LatencyTable rows={summary.latency} />
            <FootnoteText summary={summary} />
          </div>
        )}
      </div>
      <DslViewerModal
        isOpen={bm25DslOpen}
        title="BM25 baseline DSL"
        subtitle="Pure lexical, optimization toggles applied"
        body={bm25Event?.body ?? null}
        index={bm25Event?.index}
        params={bm25Event?.params}
        onClose={() => setBm25DslOpen(false)}
      />
    </div>
  )
}

function SummaryBadge({ summary }: { summary: PipelineSummaryEvent }) {
  if (summary.has_ground_truth) {
    return (
      <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border bg-blue-900/40 text-blue-200 border-blue-700/50">
        ground truth
      </span>
    )
  }
  if (!summary.confidence) return null
  const tone = CONFIDENCE_TONE[summary.confidence.confidence_label]
  return (
    <span
      className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${tone.chip}`}
    >
      proxy · {summary.confidence.confidence_label} confidence
    </span>
  )
}

function SummaryHeadline({ summary }: { summary: PipelineSummaryEvent }) {
  if (summary.has_ground_truth) {
    return (
      <p className="text-xs text-gray-300 leading-relaxed">
        Offline IR metrics for{' '}
        <span className="text-gray-100 font-medium">"{summary.query}"</span> against ESCI
        ground-truth judgments. Higher is better; compare each stage to the BM25 baseline to see
        where the pipeline earns its latency.
      </p>
    )
  }
  return (
    <p className="text-xs text-gray-300 leading-relaxed">
      No ESCI ground truth for this query — falling back to self-referential reranker confidence.
      <span className="text-gray-500"> (These signals are not offline-truth NDCG.)</span>
    </p>
  )
}

function ConfidenceCard({ summary }: { summary: PipelineSummaryEvent }) {
  const c = summary.confidence
  if (!c) return null
  const tone = CONFIDENCE_TONE[c.confidence_label]
  return (
    <div className="rounded-md border border-gray-700/50 bg-gray-800/40 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${tone.dot}`} />
        <span className={`text-sm font-medium ${tone.text}`}>
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
        <span className="text-[11px] uppercase tracking-wide text-gray-400">
          Generation (LLM-as-judge)
        </span>
        <div className="flex items-center gap-1.5 flex-wrap">
          {retried && (
            <span
              className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border whitespace-nowrap bg-amber-900/40 text-amber-200 border-amber-700/50"
              title={`Auto-corrected: faithfulness ${original?.faithfulness?.toFixed(2) ?? '?'} → ${judgment.faithfulness.toFixed(2)}`}
            >
              🔁 Auto-corrected
            </span>
          )}
          <span
            className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border whitespace-nowrap ${tone.chip}`}
          >
            {tone.label}
          </span>
        </div>
      </div>
      <div className="rounded-md border border-gray-700/50 bg-gray-800/40 p-3 space-y-2.5">
        <p className="text-xs text-gray-200 leading-snug italic break-words">
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
          const headerTone = hallucinated.length > 0 ? 'text-rose-300' : 'text-amber-300'
          return (
            <div className="border-t border-gray-700/50 pt-2 space-y-1.5">
              <span
                className={`text-[11px] uppercase tracking-wide ${headerTone}`}
                title="Red = fabrication / cross-product bleed (retry-worthy). Amber = inference / overreach (surfaced only, no retry)."
              >
                {headerLabel}
              </span>
              <ul className="text-xs list-none space-y-1.5 break-words">
                {judgment.hallucinations.map((h, i) => {
                  const tone = CATEGORY_TONE[h.category]
                  const itemColor = RETRY_WORTHY_CATEGORIES.has(h.category)
                    ? 'text-rose-200/90'
                    : 'text-amber-200/90'
                  return (
                    <li key={i} className={itemColor}>
                      <span className="flex items-start gap-1.5">
                        <span
                          className={`flex-none text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full border whitespace-nowrap ${tone.chip}`}
                          title={tone.tooltip}
                        >
                          {tone.label}
                        </span>
                        <span className="leading-snug">{h.claim}</span>
                      </span>
                      {h.reasoning && (
                        <span className="block ml-[6.5rem] text-[11px] text-gray-400 italic leading-snug">
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

function DegradedBadge({ optimizations }: { optimizations: Record<string, boolean> }) {
  const off = BM25_TUNING_KEYS.filter((k) => optimizations[k] === false)
  if (off.length === 0) return null
  return (
    <span
      className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border bg-amber-900/40 text-amber-200 border-amber-700/50"
      title={`These BM25 optimizations are off: ${off.join(', ')}. "Your BM25" reflects the degraded build.`}
    >
      ⚠ {off.length} off
    </span>
  )
}

function FootnoteText({ summary }: { summary: PipelineSummaryEvent }) {
  if (summary.has_ground_truth) {
    return (
      <p className="text-[11px] text-gray-500 leading-snug">
        ESCI relevance scale: Exact=4.0, Substitute=1.0, Complement=0.1, Irrelevant=0.0.
        "Lift / 100ms" is the marginal NDCG gain divided by the marginal latency in 100ms units.
      </p>
    )
  }
  return (
    <p className="text-[11px] text-gray-500 leading-snug">
      Confidence is a heuristic over reranker scores when no ground truth exists. Ingest ESCI
      judgments (<code>bash scripts/lucille_ingest.sh</code>) to enable NDCG/MRR/Recall@20.
    </p>
  )
}
