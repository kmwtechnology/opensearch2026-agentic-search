/**
 * SearchOptimizationDetails - Displays and toggles the search optimizations
 * applied at retrieval time (hybrid search, fuzzy, synonyms, phonetic, phrase
 * boost, field boost, typeahead). State is held in `optimizationsStore` and
 * sent to the backend with each chat message.
 */

import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import clsx from 'clsx'
import {
  useOptimizationsStore,
  type OptimizationKey,
} from '../../stores/optimizationsStore'
import { useObservabilityStore } from '../../stores/observabilityStore'
import type { OpenSearchQueryEvent } from '../../types/events'

interface OptimizationDef {
  key: OptimizationKey
  name: string
  description: string
  icon: string
}

const OPTIMIZATIONS: OptimizationDef[] = [
  {
    key: 'hybrid',
    name: 'Hybrid Search',
    description: 'Combines semantic (vector) and lexical (BM25) search for best results',
    icon: '🔄',
  },
  {
    key: 'fuzzy',
    name: 'Fuzzy Matching',
    description: 'Tolerates spelling variations (e.g., "Sony" matches "Sonie")',
    icon: '🎯',
  },
  {
    key: 'synonyms',
    name: 'Synonym Expansion',
    description: 'Expands queries (e.g., "headphones" → "earphones/earbuds")',
    icon: '🔗',
  },
  {
    key: 'phonetic',
    name: 'Phonetic Matching',
    description: 'Finds phonetically similar terms (e.g., "Sennheiser")',
    icon: '🔊',
  },
  {
    key: 'phrase_boost',
    name: 'Phrase Boosting',
    description: 'Ranks exact phrases higher (e.g., "noise cancelling")',
    icon: '📝',
  },
  {
    key: 'field_boost',
    name: 'Field Boosting',
    description: 'Prioritizes matches in important fields (title, brand)',
    icon: '⭐',
  },
  {
    key: 'typeahead',
    name: 'Typeahead Autocomplete',
    description: 'Edge-ngram prefix suggestions as you type (title + brand)',
    icon: '⌨️',
  },
  {
    key: 'reranking',
    name: 'Cross-Encoder Reranking',
    description:
      'Rescores and reorders retrieved documents with a local cross-encoder model — no added API latency',
    icon: '🧮',
  },
  {
    key: 'llm',
    name: 'LLM Response Generation',
    description: 'Synthesizes a conversational answer; off → plain search-results list',
    icon: '🤖',
  },
  {
    key: 'llm_judge',
    name: 'LLM-as-Judge (Generation Quality)',
    description:
      'Pairwise judge of the synthesized response vs the raw list — adds Generation row to the Pipeline Quality Summary card. Requires LLM Response Generation. Adds ~1–2s.',
    icon: '⚖️',
  },
]

export function SearchOptimizationDetails() {
  const [isExpanded, setIsExpanded] = useState(false)
  const optimizations = useOptimizationsStore((s) => s.optimizations)
  const toggle = useOptimizationsStore((s) => s.toggle)
  const setAll = useOptimizationsStore((s) => s.setAll)

  // Master toggle state — "all on" only when every flag is on. Mixed state
  // also reads as off so the next click sets everything on (predictable).
  const allOn = Object.values(optimizations).every(Boolean)

  // Pull the optimizations actually applied to the most recent search so the
  // user can confirm what hit OpenSearch (vs. what they have toggled now).
  // Skip the BM25-baseline event — it forces `hybrid: false` for parity
  // measurement and would otherwise mislead the "Applied" display.
  const steps = useObservabilityStore((s) => s.steps)
  const opensearchEvents = steps
    .filter((step) => step.node === 'retriever')
    .flatMap((step) => step.events)
    .filter(
      (e): e is OpenSearchQueryEvent =>
        e.type === 'opensearch_query' &&
        (e as OpenSearchQueryEvent).query_type !== 'bm25_baseline',
    )
  const lastApplied =
    opensearchEvents.length > 0
      ? opensearchEvents[opensearchEvents.length - 1].optimizations
      : undefined

  return (
    <div className="bg-[var(--color-stage-raised)] border border-[var(--color-stage-border)] rounded-lg p-4">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between hover:bg-[var(--color-stage-raised)]/30 p-2 -m-2 rounded transition-colors"
      >
        <h3 className="font-semibold text-[var(--color-stage-ink)] flex items-center gap-2">
          <span>🔍 Search Optimizations</span>
        </h3>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-[var(--color-stage-ink-soft)]" />
        ) : (
          <ChevronDown className="w-4 h-4 text-[var(--color-stage-ink-soft)]" />
        )}
      </button>

      {isExpanded && (
        <div className="mt-3 space-y-2">
          {OPTIMIZATIONS.map((opt) => {
            const enabled = optimizations[opt.key]
            // llm_judge depends on llm. When LLM is off, the judge has nothing
            // to compare, so the toggle is disabled with a hint.
            const requiresLlm = opt.key === 'llm_judge'
            const blockedByLlm = requiresLlm && !optimizations.llm
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => !blockedByLlm && toggle(opt.key)}
                aria-pressed={enabled && !blockedByLlm}
                disabled={blockedByLlm}
                title={
                  blockedByLlm
                    ? 'Enable LLM Response Generation first — the judge needs a synthesized response to compare against the raw list.'
                    : undefined
                }
                className={clsx(
                  'w-full text-left p-2 rounded text-[1.375rem] transition-colors',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500/50',
                  blockedByLlm
                    ? 'bg-[var(--color-stage-raised)]/40 border border-[var(--color-stage-border)] opacity-50 cursor-not-allowed'
                    : enabled
                      ? 'bg-white border-2 border-[#065F46] border border-[#065F46] hover:bg-white border-2 border-[#065F46] cursor-pointer'
                      : 'bg-[var(--color-stage-raised)]/20 border border-[var(--color-stage-border)] hover:bg-[var(--color-stage-raised)]/30 cursor-pointer'
                )}
              >
                <div className="flex items-start gap-2">
                  <span className="text-lg">{opt.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-[var(--color-stage-ink)]">{opt.name}</div>
                    <div className="text-[1.25rem] text-[var(--color-stage-ink-soft)] mt-0.5">{opt.description}</div>
                  </div>
                  <Toggle enabled={enabled} />
                </div>
              </button>
            )
          })}

          {lastApplied && (
            <div className="mt-3 pt-3 border-t border-[var(--color-stage-border)] text-[1.25rem]">
              <div className="text-[var(--color-stage-ink-soft)] mb-1">Applied to last search:</div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono">
                {Object.entries(lastApplied).map(([k, v]) => (
                  <span key={k} className={v ? 'text-[#065F46]' : 'text-[#991B1B]'}>
                    {k}={v ? 'on' : 'off'}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="mt-3 pt-3 border-t border-[var(--color-stage-border)] text-[1.25rem] text-[var(--color-stage-ink-soft)]">
            <div className="flex items-center justify-between mb-2 gap-3">
              <p className="flex-1">💡 <strong>Tip:</strong> Click any row to toggle it; the next query reflects your choices.</p>
              <button
                type="button"
                role="switch"
                aria-checked={allOn}
                onClick={() => setAll(!allOn)}
                className={clsx(
                  'shrink-0 inline-flex items-center gap-2 px-2 py-1 rounded-md border transition-colors',
                  allOn
                    ? 'border-[#065F46] bg-white border-2 border-[#065F46] text-[#065F46] hover:bg-white border-2 border-[#065F46]'
                    : 'border-[var(--color-stage-border)] bg-[var(--color-stage-raised)] text-[var(--color-stage-ink-muted)] hover:bg-[var(--color-stage-raised)]'
                )}
                title={allOn ? 'Turn all optimizations OFF' : 'Turn all optimizations ON'}
              >
                <span className="text-[1.25rem] uppercase tracking-wide">All</span>
                <span
                  className={clsx(
                    'w-7 h-3.5 rounded-full transition-colors relative',
                    allOn ? 'bg-[#065F46]' : 'bg-gray-600'
                  )}
                >
                  <span
                    className={clsx(
                      'absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white transition-all',
                      allOn ? 'left-4' : 'left-0.5'
                    )}
                  />
                </span>
                <span className="text-[1.25rem] font-medium">{allOn ? 'On' : 'Off'}</span>
              </button>
            </div>
            <p>Try searching for:</p>
            <ul className="list-disc list-inside text-gray-600 mt-1 space-y-1">
              <li>Misspelled terms (e.g., "sonie" for Sony)</li>
              <li>Product alternatives (e.g., "earbuds" for headphones)</li>
              <li>Phonetic variants (e.g., "Sennheiser")</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

function Toggle({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={clsx(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ml-2',
        enabled ? 'bg-green-600' : 'bg-gray-600'
      )}
    >
      <span
        className={clsx(
          'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
          enabled ? 'translate-x-4' : 'translate-x-1'
        )}
      />
    </span>
  )
}
