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
  QualityGateEvent,
  QueryExpansionEvent,
  QueryEvaluationEvent,
  RerankerResultEvent,
} from '../../types/events'

/** Which pipeline stage a line came from — drives colour and icon. */
export type NarratorNode =
  | 'intent_classifier'
  | 'query_evaluator'
  | 'retriever'
  | 'reranker'
  | 'quality_gate'
  | 'agent'
  | 'enrichment'

/**
 * 'moment' lines get oversized, full-width treatment. Reserved for the three
 * things that carry the demo: a quality-gate retry, a judge verdict, and the
 * taxonomy correction sequence. Everything else is a 'step'.
 */
export type NarratorWeight = 'step' | 'moment'

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
    text: `Leaned ${strategy} — weighting meaning over exact words at α ${e.alpha.toFixed(2)}.`,
    weight: 'step',
  }
}

function expansionLine(e: QueryExpansionEvent): NarratorLine | null {
  // A no-op expansion is noise; only narrate a genuine rewrite.
  if (!e.expanded_query || e.expanded_query === e.original_query) return null
  return {
    id: `expand-${e.timestamp}`,
    node: 'retriever',
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
      : `Searched the catalog, blending keyword matching with meaning.${filters}`,
    weight: 'step',
  }
}

function rerankerLine(e: RerankerResultEvent): NarratorLine {
  const top = e.results?.[0]
  const score = top ? ` Best match scores ${top.score.toFixed(2)}.` : ''
  return {
    id: `rerank-${e.timestamp}`,
    node: 'reranker',
    label: 'Reranker',
    text: e.reranking_changed_order
      ? `Re-read every candidate against the question and changed the order.${score}`
      : `Re-read every candidate against the question; the order already held up.${score}`,
    weight: 'step',
  }
}

function qualityGateLine(e: QualityGateEvent): NarratorLine {
  if (e.triggered) {
    return {
      id: `gate-${e.timestamp}`,
      node: 'quality_gate',
      label: 'Quality Gate',
      // Deliberately about the loop firing, not about the retry scoring
      // better — with a deterministic cross-encoder it usually does not.
      text:
        `The results weren't good enough — best match ${e.max_score.toFixed(2)} ` +
        `against a bar of ${e.threshold.toFixed(2)}. Searching again with ` +
        `different settings.`,
      weight: 'moment',
    }
  }
  return {
    id: `gate-${e.timestamp}`,
    node: 'quality_gate',
    label: 'Quality Gate',
    text: `Passed the quality bar — ${e.max_score.toFixed(2)} against ${e.threshold.toFixed(2)}.`,
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
      return {
        ...base,
        label: 'Catalog Update',
        text: `Rebuilding the catalog so every product picks up the corrected ${e.attribute_type}.`,
      }
    case 'complete': {
      // corrected_from is the whole point: it separates fixing a wrong tag
      // from learning a new word.
      const what = e.corrected_from
        ? `“${e.variant}” was tagged ${e.corrected_from} — it now reads ${e.canonical}.`
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
    default:
      return null
  }
}

/**
 * The visible tail of the narration.
 *
 * Capped so the panel never scrolls — a presenter should not have to chase a
 * line that has slid off the bottom. Enrichment lines supersede earlier
 * enrichment lines rather than stacking, so the lifecycle reads as one thing
 * progressing instead of four separate announcements.
 */
// Four, not five. Measured against a real 1920x1080 window: browser chrome
// eats ~200px, leaving ~870px of viewport, and five lines at projector type
// clipped the oldest one behind overflow-hidden — silently, which is the
// worst way to lose it. Four fits with room to spare even in a window, and
// fills the panel properly in fullscreen.
export const MAX_VISIBLE_LINES = 4

export function visibleLines(lines: NarratorLine[]): NarratorLine[] {
  const collapsed: NarratorLine[] = []
  for (const line of lines) {
    if (line.node === 'enrichment') {
      const priorIndex = collapsed.findIndex((l) => l.node === 'enrichment')
      if (priorIndex !== -1) {
        collapsed[priorIndex] = line
        continue
      }
    }
    collapsed.push(line)
  }
  return collapsed.slice(-MAX_VISIBLE_LINES)
}
