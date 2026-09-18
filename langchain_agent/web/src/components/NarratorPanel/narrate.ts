/**
 * Turn pipeline events into one plain sentence each (#103).
 *
 * The observability panel answers "what are all the numbers". This answers
 * "what just happened", for someone reading from the back of a room who will
 * see each line for a few seconds at most.
 *
 * Rules that shaped this:
 *  - MOST EVENTS MAP TO NOTHING. Returning null is the common case and the
 *    right one — a narrator that reports every token chunk is a log.
 *  - Reuse the backend's own human-readable fields rather than recomputing
 *    prose from raw numbers: `search_strategy` is validated against alpha
 *    server-side, `filter_summary` is already a sentence fragment, and
 *    `quality_gate.reason` is already formatted.
 *  - Never state something the data does not support. The quality-gate retry
 *    re-runs a deterministic cross-encoder and returns the same max score, so
 *    we say the loop fired, never that the second attempt scored better.
 */

import type {
  AgentEvent,
  EnrichmentTriggeredEvent,
  IntentClassificationEvent,
  OpenSearchQueryEvent,
  PipelineStageName,
  PipelineSummaryEvent,
  QualityGateEvent,
  QueryExpansionEvent,
  QueryEvaluationEvent,
  RerankerResultEvent,
} from '../../types/events'

/** Which pipeline stage a line came from — drives color and icon. */
export type NarratorNode =
  | 'intent_classifier'
  | 'query_evaluator'
  // The rewriter is its own stage, not part of the retriever, precisely so
  // collapsing one-line-per-stage cannot swallow it behind the search line.
  | 'query_rewriter'
  | 'retriever'
  | 'reranker'
  | 'quality_gate'
  | 'agent'
  | 'enrichment'
  | 'ground_truth'

/**
 * 'moment' lines get oversized, full-width treatment. Reserved for the three
 * things that carry the demo: a quality-gate retry, a judge verdict, and the
 * taxonomy correction sequence. Everything else is a 'step'.
 */
export type NarratorWeight = 'step' | 'moment'

/**
 * A small horizontal bar rendered beside a line, for the two numbers in this
 * pipeline that are positions on a range rather than bare values: where the
 * hybrid weighting sat between keywords and meaning, and where the best match
 * landed relative to the bar it had to clear.
 *
 * Deliberately DESCRIPTIVE, not a quality claim. An alpha gauge says how
 * literally the question was read; it does NOT say the results were better for
 * it. (Measured on the arc's own queries: at alpha 0.25 the first page of
 * "blue running shoes" includes blue jeans, and a pure-semantic run of the same
 * query returns five actual running shoes. The RERANKER is what removes the
 * jeans — so the gauge shows a setting, and the score gauge shows the outcome.)
 */
export interface NarratorGauge {
  kind: 'alpha' | 'score'
  /** 0..1, where the filled portion ends. */
  value: number
  /** 0..1 tick mark — the threshold on a score gauge. */
  marker?: number
  leftLabel: string
  rightLabel: string
  /** Short caption under the bar, e.g. "0.94 against a bar of 0.45". */
  caption: string
}

/** One stage's real ESCI-judged relevance, for the ground-truth reveal card. */
export interface GroundTruthStage {
  stage: PipelineStageName
  label: string
  ndcg10: number
  judgedCount: number
}

export interface NarratorLine {
  /** Stable within a turn, so React keys and de-duplication behave. */
  id: string
  node: NarratorNode
  /** Short stage label, e.g. "Quality Gate". */
  label: string
  /** The sentence. Plain language, no jargon the audience has not been given. */
  text: string
  weight: NarratorWeight
  /** Enrichment lifecycle phase, when this line is part of that sequence. */
  enrichment?: EnrichmentTriggeredEvent['status']
  /** Set on a correction so the panel can render the before/after pair. */
  correctedFrom?: string
  canonical?: string
  variant?: string
  docsProcessed?: number
  durationSeconds?: number
  reindexRunUrl?: string
  reindexMode?: string
  error?: string
  /** Optional bar rendered under the sentence. */
  gauge?: NarratorGauge
  /** Set when this is a ground-truth reveal — one entry per judged stage. */
  groundTruthStages?: GroundTruthStage[]
}

const INTENT_PHRASING: Record<string, string> = {
  search: 'a plain search',
  comparison: 'a comparison between named products',
  attribute_filter: 'a request filtered by a specific attribute',
  refinement: 'a refinement of the last turn',
  follow_up: 'a follow-up to the last turn',
  summary: 'a request to summarise the conversation',
}

function percent(value: number | undefined): string | null {
  if (value === undefined || value === null) return null
  return `${Math.round(value * 100)}%`
}

/**
 * Same buckets the backend uses to label `search_strategy`
 * (query_evaluator_node in pipeline_nodes.py) so the retriever's own sentence
 * agrees with the gauge above it instead of restating generic boilerplate
 * regardless of where alpha actually landed.
 */
function describeAlpha(alpha: number): string {
  if (alpha <= 0.15) return 'by exact words alone'
  if (alpha <= 0.4) return 'mostly by exact words'
  if (alpha <= 0.6) return 'by blending exact words and meaning evenly'
  if (alpha <= 0.75) return 'mostly by meaning'
  return 'by meaning alone'
}

function intentLine(e: IntentClassificationEvent): NarratorLine {
  const phrasing = INTENT_PHRASING[e.intent] ?? `intent "${e.intent}"`
  const confidence = percent(e.confidence)
  return {
    id: `intent-${e.timestamp}`,
    node: 'intent_classifier',
    label: 'Intent Classifier',
    text: confidence
      ? `Read this as ${phrasing} — ${confidence} confident.`
      : `Read this as ${phrasing}.`,
    weight: 'step',
  }
}

function evaluatorLine(e: QueryEvaluationEvent): NarratorLine {
  // search_strategy is the backend's own bucketing of alpha and is validated
  // against it server-side, so it can be trusted without re-deriving.
  const strategy = e.search_strategy?.replace('-', ' ') ?? 'balanced'
  return {
    id: `alpha-${e.timestamp}`,
    node: 'query_evaluator',
    label: 'Query Evaluator',
    // The gauge right below already shows "how literally" via its own
    // exact-words/meaning axis labels — restating the concept in words every
    // single turn was pure boilerplate, not something specific to this turn.
    text: `Leaned ${strategy}.`,
    weight: 'step',
    gauge: {
      kind: 'alpha',
      value: Math.max(0, Math.min(1, e.alpha)),
      leftLabel: 'exact words',
      rightLabel: 'meaning',
      caption: `α ${e.alpha.toFixed(2)} — ${strategy}`,
    },
  }
}

function expansionLine(e: QueryExpansionEvent): NarratorLine | null {
  // A no-op expansion is noise; only narrate a genuine rewrite.
  if (!e.expanded_query || e.expanded_query === e.original_query) return null
  return {
    id: `expand-${e.timestamp}`,
    node: 'query_rewriter',
    label: 'Query Rewriter',
    text: `Understood “${e.original_query}” as “${e.expanded_query}”.`,
    weight: 'step',
  }
}

function searchLine(e: OpenSearchQueryEvent): NarratorLine | null {
  // The retriever also issues a stock-BM25 query alongside the real hybrid
  // one, purely so the pipeline summary can report a baseline to compare
  // against. Narrating it produces two identical "Searched the catalog"
  // lines back to back, which reads as a bug to an audience — and burns two
  // of the five visible slots on one step.
  if (e.query_type === 'bm25_baseline') return null

  const isRetry = e.query_type === 'quality_gate_retry'
  const filters = e.filter_summary ? ` Filtered on ${e.filter_summary}.` : ''
  return {
    id: `search-${e.timestamp}`,
    node: 'retriever',
    label: 'Knowledge Search',
    text: isRetry
      ? `Searched the catalog again with the rebalanced settings.${filters}`
      : `Searched the catalog, ${describeAlpha(e.alpha)}.${filters}`,
    weight: 'step',
  }
}

function rerankerLine(e: RerankerResultEvent): NarratorLine {
  const top = e.results?.[0]
  const score = top ? ` Best match scores ${top.score.toFixed(2)}.` : ''
  // reranking_changed_order is coarse (true if ANY candidate moved); the
  // audience cares specifically about whether the #1 result changed, since
  // that's the one they see first. top.original_rank is the pre-rerank
  // position of whichever document now sits at rank 1.
  const topPromoted = Boolean(top && top.original_rank !== 1)
  const text = topPromoted
    ? `Re-read every candidate against the question and promoted a new top pick.${score}`
    : e.reranking_changed_order
      ? `Re-read every candidate against the question — the top pick held, but the rest reordered.${score}`
      : `Re-read every candidate against the question; the order already held up.${score}`
  return {
    id: `rerank-${e.timestamp}`,
    node: 'reranker',
    label: 'Reranker',
    text,
    weight: 'step',
  }
}

function qualityGateLine(e: QualityGateEvent): NarratorLine {
  if (e.triggered) {
    return {
      id: `gate-${e.timestamp}`,
      node: 'quality_gate',
      label: 'Quality Gate',
      // The retry now searches DEEPER (4x the candidate pool), not just at a
      // different alpha, so it genuinely can come back with a better match —
      // re-weighting alone provably could not. It is still not guaranteed:
      // a query with nothing good behind it fails both passes.
      text:
        `The results weren't good enough — best match ${e.max_score.toFixed(2)} ` +
        `against a bar of ${e.threshold.toFixed(2)}. Searching again, deeper ` +
        `into the ranking.`,
      weight: 'moment',
    }
  }
  // A max score of exactly zero means nothing was retrieved to score in the
  // first place — usually filters that matched no products. Reporting that as
  // "Passed the quality bar — 0.00 against 0.45" is worse than saying nothing:
  // it is visibly self-contradictory to an audience, and it claims a check
  // succeeded when it never ran. Observed live on DEMO.md's first query.
  if (e.max_score === 0) {
    return {
      id: `gate-${e.timestamp}`,
      node: 'quality_gate',
      label: 'Quality Gate',
      text: 'Nothing came back to score — no product matched those filters.',
      weight: 'step',
    }
  }

  // Three outcomes, not two — and `triggered` alone cannot tell them apart.
  // After a retry has been spent the gate emits triggered=false even when the
  // score is STILL under the bar, which is "this is the best available", not
  // "passed". Observed live: 0.34 against 0.45 announced as a pass.
  //
  // Comparing the two numbers we already have is both honest and robust; the
  // alternative is sniffing e.reason for the string "Accepted after retry".
  if (e.max_score < e.threshold) {
    return {
      id: `gate-${e.timestamp}`,
      node: 'quality_gate',
      label: 'Quality Gate',
      text:
        `Still under the bar after retrying — ${e.max_score.toFixed(2)} against ` +
        `${e.threshold.toFixed(2)}. Answering with the best available matches.`,
      weight: 'step',
    }
  }

  return {
    id: `gate-${e.timestamp}`,
    node: 'quality_gate',
    label: 'Quality Gate',
    text: 'Passed the quality bar.',
    gauge: {
      kind: 'score',
      value: Math.max(0, Math.min(1, e.max_score)),
      marker: Math.max(0, Math.min(1, e.threshold)),
      leftLabel: '0',
      rightLabel: '1',
      caption: `best match ${e.max_score.toFixed(2)} against a bar of ${e.threshold.toFixed(2)}`,
    },
    weight: 'step',
  }
}

function enrichmentLine(e: EnrichmentTriggeredEvent): NarratorLine {
  const base = {
    id: `enrich-${e.status}-${e.timestamp}`,
    node: 'enrichment' as const,
    enrichment: e.status,
    variant: e.variant,
    canonical: e.canonical,
    correctedFrom: e.corrected_from,
    docsProcessed: e.docs_processed,
    durationSeconds: e.duration_seconds,
    reindexRunUrl: e.reindex_run_url,
    reindexMode: e.reindex_mode,
    error: e.error,
    weight: 'moment' as const,
  }

  switch (e.status) {
    case 'started':
      // #142: name the reason BEFORE the reindex runs, not just the fact
      // that one is running — "it just jumps to reingestion without
      // telling the user why or what it's doing". corrected_from here is
      // the CURRENT mapping (if any), threaded through from the same
      // lookup the value judge already did — present means this variant is
      // mapped to something else today (a correction in progress); absent
      // means it isn't mapped at all yet (a genuine gap being filled).
      return {
        ...base,
        label: 'Catalog Update',
        text: e.corrected_from
          ? `“${e.variant}” is currently mapped to “${e.corrected_from}” — rewriting that and re-indexing the catalog live.`
          : // "tagged 'waterproof' as a waterproof" reads redundant when the
            // term and the attribute type are the same word (registering the
            // FIRST entry of a brand-new type) — drop the clause in that case.
            e.variant.toLowerCase() === e.attribute_type.toLowerCase()
            ? `No products are tagged “${e.variant}” yet — teaching the catalog this term and re-indexing live.`
            : `No products are tagged “${e.variant}” as a ${e.attribute_type} yet — teaching the catalog this term and re-indexing live.`,
      }
    case 'complete': {
      // corrected_from is the whole point: it separates fixing a wrong tag
      // from learning a new word. When variant === canonical (e.g. teaching
      // "waterproof" itself, not a synonym like "weatherproof"), "is now
      // understood as waterproof" reads as a tautology on a projector — say
      // it registered a new filterable attribute instead.
      // Lowercased on both sides to match format_enrichment_message's own
      // check (tools/enrichment_tool.py) and the 'started' branch above —
      // a model echoing the query's casing ("Waterproof") would otherwise
      // slip past this and print the tautology anyway.
      const what = e.corrected_from
        ? `“${e.variant}” was tagged ${e.corrected_from} — it now reads ${e.canonical}.`
        : e.variant.toLowerCase() === (e.canonical ?? '').toLowerCase()
          ? `“${e.variant}” is now a filterable attribute.`
          : `“${e.variant}” is now understood as ${e.canonical}.`
      const scale =
        e.docs_processed && e.duration_seconds
          ? ` Rebuilt ${e.docs_processed.toLocaleString()} products in ${e.duration_seconds.toFixed(1)}s.`
          : e.reindex_run_url
            ? ' Handed off to the cloud build — it finishes out of band.'
            : ''
      return {
        ...base,
        label: e.corrected_from ? 'Correction Applied' : 'Catalog Learned',
        text: `${what}${scale}`,
      }
    }
    case 'failed':
      return {
        ...base,
        label: 'Catalog Update Failed',
        text: `The catalog rebuild did not finish${e.error ? ` — ${e.error}` : ''}. The tag is unchanged.`,
      }
    case 'declined':
      return {
        ...base,
        label: 'Change Declined',
        text: `A second model reviewed the change and turned it down${e.error ? ` — ${e.error}` : ''}.`,
      }
  }
}

const GROUND_TRUTH_STAGE_LABELS: Record<PipelineStageName, string> = {
  stock_bm25: 'Stock BM25',
  bm25: 'Your BM25',
  hybrid: 'Hybrid',
  reranked: 'Reranked',
}

/**
 * The bonus scene's entire point: real ESCI-judged relevance instead of the
 * self-referential confidence proxy every other turn shows. Without this
 * case, `pipeline_summary` events silently narrate to nothing (the default
 * branch below) and the one thing the scene exists to prove never reaches
 * the panel the audience is actually watching — only the full F2 detail view,
 * which DEMO.md itself says is for Q&A, not the walkthrough (#130).
 */
function groundTruthLine(e: PipelineSummaryEvent): NarratorLine | null {
  if (!e.has_ground_truth) return null

  const stageOrder: PipelineStageName[] = ['stock_bm25', 'bm25', 'hybrid', 'reranked']
  const stages: GroundTruthStage[] = stageOrder
    .map((stage) => {
      const metrics = e[stage]
      if (!metrics) return null
      return {
        stage,
        label: GROUND_TRUTH_STAGE_LABELS[stage],
        ndcg10: metrics.ndcg10,
        judgedCount: metrics.judged_count,
      }
    })
    .filter((s): s is GroundTruthStage => s !== null)

  if (stages.length === 0) return null

  const best = stages[stages.length - 1]
  return {
    id: `ground-truth-${e.timestamp}`,
    node: 'ground_truth',
    label: 'Real Ground Truth',
    text: `Measured against real ESCI relevance judgments, not this system's own scoring — NDCG@10 climbs to ${best.ndcg10.toFixed(2)}.`,
    weight: 'moment',
    groundTruthStages: stages,
  }
}

/**
 * Map one event to at most one narrator line.
 *
 * Returning null means "not worth saying out loud", which is true of the
 * large majority of events on the wire.
 */
export function narrate(event: AgentEvent): NarratorLine | null {
  switch (event.type) {
    case 'intent_classification':
      return intentLine(event)
    case 'query_evaluation':
      return evaluatorLine(event)
    case 'query_expansion':
      return expansionLine(event)
    case 'opensearch_query':
      return searchLine(event)
    case 'reranker_result':
      return rerankerLine(event)
    case 'quality_gate':
      return qualityGateLine(event)
    case 'enrichment_triggered':
      return enrichmentLine(event)
    case 'pipeline_summary':
      return groundTruthLine(event)
    default:
      return null
  }
}

/**
 * Reduce a turn's events to the lines the panel shows.
 *
 * ONE LINE PER PIPELINE STAGE, in the order the stages first ran, latest
 * content winning. Two reasons:
 *
 *  - Nothing gets skipped. The previous version kept a sliding window of the
 *    most recent N lines, which silently dropped the earliest stages: a normal
 *    turn emits five or six narratable events, so "Intent Classifier" — the
 *    first thing a presenter explains — fell off the top before anyone saw it.
 *  - A quality-gate retry re-runs search and reranking, which under a
 *    sliding window pushed the whole first half of the turn out of view. Those
 *    repeats now update their existing line instead of appending a duplicate;
 *    the retry itself is still narrated, because the gate's own wording says
 *    so ("Still under the bar after retrying", "Searched the catalog again").
 *
 * The result is bounded by the number of pipeline stages, not by how many
 * events fired, so the panel cannot outgrow its height. Ordering by stage also
 * lets the audience follow the same top-to-bottom path as the architecture
 * diagram they were just shown.
 */
export const MAX_VISIBLE_LINES = 7

/**
 * How many pipeline lines survive alongside the enrichment card (#108).
 *
 * The enrichment moment is roughly four ordinary lines tall — a headline, the
 * WAS/NOW pair, and the re-run button. Seven lines plus that card overflows a
 * 1920x1080 viewport, and the panel does not scroll by design, so the card and
 * its button were rendered but unreachable: the arc's entire payoff sat below
 * the fold at exactly the resolution the demo is presented at. It only fit on
 * the larger development display, which is why it survived review.
 *
 * Dropping the earliest lines rather than shortening the card is deliberate.
 * The card IS the point of the turn; the stages above it are context the
 * presenter has already narrated by the time it appears.
 */
export const MAX_VISIBLE_LINES_WITH_MOMENT = 3

/**
 * Node types that render as a full-width card rather than an ordinary line,
 * and how many ordinary lines stay visible alongside each — enrichment keeps
 * 3, since the presenter is still narrating the pipeline context (the
 * quality-gate retry, the search that led here) right up to the moment the
 * card appears.
 *
 * ground_truth is NOT a moment here — it used to replace the step lines
 * entirely (cap 0), on the assumption it only ever fires in its own
 * dedicated single-turn bonus scene. That assumption turned out to be false:
 * `lookup_judgments()` runs on every query in every demo, so any exact-match
 * query — typed mid-Arc-1, mid-Arc-2, anywhere — can trigger it, and hiding
 * that turn's actual pipeline context whenever it did was surprising rather
 * than helpful. It now renders in its own tab (see NarratorPanel/index.tsx)
 * instead of competing with step lines for space, so it's filtered out here
 * and never enters the moment-capping logic at all.
 */
const MOMENT_LINE_CAPS: Partial<Record<NarratorNode, number>> = {
  enrichment: MAX_VISIBLE_LINES_WITH_MOMENT,
}
const MOMENT_NODES = new Set<NarratorNode>(Object.keys(MOMENT_LINE_CAPS) as NarratorNode[])

export function visibleLines(lines: NarratorLine[]): NarratorLine[] {
  const byNode = new Map<NarratorNode, NarratorLine>()
  for (const line of lines) {
    if (line.node === 'ground_truth') continue
    byNode.set(line.node, line)
  }
  // Map preserves insertion order, and a re-set key keeps its original
  // position — exactly the "first-seen order, latest content" we want.
  const deduped = [...byNode.values()]

  const moments = deduped.filter((l) => MOMENT_NODES.has(l.node))
  const moment = moments[moments.length - 1]
  if (!moment) {
    return deduped.slice(-MAX_VISIBLE_LINES)
  }

  const cap = MOMENT_LINE_CAPS[moment.node] ?? MAX_VISIBLE_LINES_WITH_MOMENT
  // Keep the card, and only the pipeline lines immediately preceding it.
  const rest = deduped.filter((l) => !MOMENT_NODES.has(l.node))
  return [...rest.slice(-cap), moment]
}
