/**
 * TypeaheadSuggestions - Autocomplete dropdown with ARIA combobox semantics.
 *
 * Three sections, rendered top-to-bottom in this fixed order whenever each
 * has content:
 *   1. Did you mean       — backend spell correction (requires query)
 *   2. Suggestions        — product prefix matches (requires query)
 *   3. Recent searches    — localStorage history (shown whether or not the
 *                           user has typed, so they can re-run a prior query)
 *
 * Keyboard navigation walks selectable rows in the same order, skipping
 * section headers.
 */

import clsx from 'clsx'
import { History, Lightbulb, Search, SpellCheck2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { apiGet } from '../../utils/api'
import { useRecentSearches } from '../../hooks/useRecentSearches'
import { useOptimizationsStore } from '../../stores/optimizationsStore'

export interface Suggestion {
  title: string
  brand?: string
  type: 'product' | 'spelling' | 'recent'
  score?: number
  highlight?: string[]
}

interface BackendSuggestion {
  title: string
  brand?: string | null
  score?: number | null
  highlight?: string[] | null
}

interface BackendResponse {
  suggestions: BackendSuggestion[]
  spell_correction: BackendSuggestion | null
}

interface TypeaheadSuggestionsProps {
  query: string
  isOpen: boolean
  selectedIndex: number
  listboxId: string
  onSelect: (suggestion: Suggestion) => void
  onRowCountChange?: (count: number) => void
}

const HL_PRE = '<mark data-th>'
const HL_POST = '</mark>'

/** Render a highlighted OpenSearch fragment as React nodes. No dangerouslySetInnerHTML. */
function HighlightedText({ fragment, fallback }: { fragment?: string; fallback: string }) {
  if (!fragment) return <>{fallback}</>

  const nodes: React.ReactNode[] = []
  let cursor = 0
  let key = 0
  while (cursor < fragment.length) {
    const start = fragment.indexOf(HL_PRE, cursor)
    if (start === -1) {
      nodes.push(fragment.slice(cursor))
      break
    }
    if (start > cursor) {
      nodes.push(fragment.slice(cursor, start))
    }
    const end = fragment.indexOf(HL_POST, start + HL_PRE.length)
    if (end === -1) {
      nodes.push(fragment.slice(start))
      break
    }
    const inner = fragment.slice(start + HL_PRE.length, end)
    nodes.push(
      <mark key={key++} className="bg-yellow-500/30 text-yellow-100 rounded px-0.5">
        {inner}
      </mark>
    )
    cursor = end + HL_POST.length
  }

  return <>{nodes.length > 0 ? nodes : fallback}</>
}

function SectionHeader({
  icon,
  label,
  action,
}: {
  icon: React.ReactNode
  label: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between px-4 py-1.5 text-[10px] uppercase tracking-wider text-gray-500 bg-gray-900/40">
      <span className="flex items-center gap-1.5">
        {icon}
        {label}
      </span>
      {action}
    </div>
  )
}

function Row({
  row,
  optionId,
  selected,
  onSelect,
}: {
  row: Suggestion
  optionId: string
  selected: boolean
  onSelect: (s: Suggestion) => void
}) {
  const isSpelling = row.type === 'spelling'
  const isRecent = row.type === 'recent'
  const Icon = isSpelling ? SpellCheck2 : isRecent ? History : Search
  const iconClass = isSpelling ? 'text-amber-400' : 'text-gray-500'

  return (
    <button
      id={optionId}
      type="button"
      role="option"
      aria-selected={selected}
      onMouseDown={(e) => {
        // Prevent textarea blur so onSelect fires before blur-timer closes dropdown.
        e.preventDefault()
      }}
      onClick={() => onSelect(row)}
      className={clsx(
        'w-full text-left px-4 py-2 text-sm transition-colors',
        selected ? 'bg-blue-600/20 text-blue-300' : 'hover:bg-gray-700/50 text-gray-200'
      )}
    >
      <div className="flex items-start gap-3">
        <Icon className={clsx('w-4 h-4 mt-0.5 flex-shrink-0', iconClass)} />
        <div className="flex-1 min-w-0">
          {isSpelling ? (
            <div className="truncate">
              <span className="text-xs text-amber-400 font-medium">Did you mean: </span>
              <span className="font-medium">{row.title}</span>
            </div>
          ) : (
            <div className="truncate font-medium">
              <HighlightedText fragment={row.highlight?.[0]} fallback={row.title} />
            </div>
          )}
          {row.brand && !isSpelling && (
            <div className="text-xs text-gray-400 truncate">{row.brand}</div>
          )}
          {row.score !== undefined && row.score < 1 && !isRecent && (
            <div className="text-xs text-gray-500 mt-0.5">
              Match: {(row.score * 100).toFixed(0)}%
            </div>
          )}
        </div>
      </div>
    </button>
  )
}

export function TypeaheadSuggestions({
  query,
  isOpen,
  selectedIndex,
  listboxId,
  onSelect,
  onRowCountChange,
}: TypeaheadSuggestionsProps) {
  const [products, setProducts] = useState<Suggestion[]>([])
  const [spelling, setSpelling] = useState<Suggestion | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { recent, clear: clearRecent } = useRecentSearches()
  const typeaheadEnabled = useOptimizationsStore((s) => s.optimizations.typeahead)

  const trimmed = query.trim()
  const hasQuery = trimmed.length > 0

  // Fetch suggestions when query, visibility, or settings change
  useEffect(() => {
    // If conditions aren't met, don't fetch (stale state is OK - component won't render it)
    if (!hasQuery || !isOpen || !typeaheadEnabled) {
      return
    }

    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setIsLoading(true)
      setError(null)
      try {
        const response = await apiGet(`/api/suggest?q=${encodeURIComponent(trimmed)}`, {
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data = (await response.json()) as BackendResponse
        setProducts(
          (data.suggestions || []).map((s) => ({
            title: s.title,
            brand: s.brand ?? undefined,
            score: s.score ?? undefined,
            highlight: s.highlight ?? undefined,
            type: 'product' as const,
          }))
        )
        setSpelling(
          data.spell_correction
            ? {
                title: data.spell_correction.title,
                brand: data.spell_correction.brand ?? undefined,
                score: data.spell_correction.score ?? undefined,
                type: 'spelling' as const,
              }
            : null
        )
      } catch (err) {
        if ((err as { name?: string }).name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load suggestions')
        setProducts([])
        setSpelling(null)
      } finally {
        setIsLoading(false)
      }
    }, 300)

    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [trimmed, hasQuery, isOpen, typeaheadEnabled])

  // Flat list of selectable rows in navigation order: spelling → products → recent.
  // Headers are visual-only and don't participate in arrow-key navigation.
  const rows = useMemo<Suggestion[]>(() => {
    const list: Suggestion[] = []
    if (spelling) list.push(spelling)
    list.push(...products)
    list.push(...recent.map((q) => ({ title: q, type: 'recent' as const })))
    return list
  }, [spelling, products, recent])

  useEffect(() => {
    onRowCountChange?.(rows.length)
  }, [rows.length, onRowCountChange])

  // Show sections
  const showSpellSection = hasQuery && !!spelling && !isLoading
  const showSuggestionsSection = hasQuery // always render section header + placeholder/loading/empty/rows while query present
  const showRecentSection = recent.length > 0

  // Close when there's literally nothing to show (no query AND no recent history).
  if (!isOpen) return null
  if (!showSuggestionsSection && !showRecentSection) return null

  const productRows = rows.filter((r) => r.type === 'product')
  const recentRows = rows.filter((r) => r.type === 'recent')
  // Offsets into the flat `rows` array so each row knows its navigation index.
  const spellOffset = 0
  const productOffset = spelling ? 1 : 0
  const recentOffset = productOffset + productRows.length

  return (
    <div
      role="listbox"
      id={listboxId}
      aria-label="Search suggestions"
      className="absolute bottom-full mb-2 left-0 right-0 bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden max-h-[28rem] overflow-y-auto z-50 divide-y divide-gray-700"
    >
      {/* Section 1: Did you mean */}
      {showSpellSection && spelling && (
        <div>
          <SectionHeader icon={<SpellCheck2 className="w-3 h-3 text-amber-400" />} label="Did you mean" />
          <Row
            row={spelling}
            optionId={`typeahead-option-${spellOffset}`}
            selected={selectedIndex === spellOffset}
            onSelect={onSelect}
          />
        </div>
      )}

      {/* Section 2: Suggestions */}
      {showSuggestionsSection && (
        <div>
          <SectionHeader icon={<Search className="w-3 h-3" />} label="Suggestions" />

          {isLoading && (
            <div role="status" aria-live="polite" className="py-1">
              <span className="sr-only">Loading suggestions</span>
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="px-4 py-2 flex items-center gap-3">
                  <div className="w-4 h-4 rounded bg-gray-700/60 animate-pulse" />
                  <div className="h-3 rounded bg-gray-700/60 animate-pulse flex-1" />
                </div>
              ))}
            </div>
          )}

          {error && !isLoading && (
            <div role="status" aria-live="polite" className="px-4 py-3 text-sm text-red-400">
              Could not load suggestions
            </div>
          )}

          {!isLoading && !error && productRows.length === 0 && (
            <div role="status" aria-live="polite" className="px-4 py-3 text-sm text-gray-500">
              No products found for &ldquo;{trimmed}&rdquo;
            </div>
          )}

          {!isLoading && !error &&
            productRows.map((row, i) => {
              const navIndex = productOffset + i
              return (
                <Row
                  key={`product-${i}-${row.title}`}
                  row={row}
                  optionId={`typeahead-option-${navIndex}`}
                  selected={selectedIndex === navIndex}
                  onSelect={onSelect}
                />
              )
            })}
        </div>
      )}

      {/* Section 3: Recent */}
      {showRecentSection && (
        <div>
          <SectionHeader
            icon={<History className="w-3 h-3" />}
            label="Recent"
            action={
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={(e) => {
                  e.stopPropagation()
                  clearRecent()
                }}
                className="flex items-center gap-1 text-gray-500 hover:text-gray-300 transition-colors"
                aria-label="Clear recent searches"
              >
                <X className="w-3 h-3" />
                Clear
              </button>
            }
          />
          {recentRows.map((row, i) => {
            const navIndex = recentOffset + i
            return (
              <Row
                key={`recent-${i}-${row.title}`}
                row={row}
                optionId={`typeahead-option-${navIndex}`}
                selected={selectedIndex === navIndex}
                onSelect={onSelect}
              />
            )
          })}
        </div>
      )}

      {/* Hint */}
      <div className="px-4 py-2 text-xs text-gray-500 bg-gray-900/50">
        <span role="status" aria-live="polite" className="sr-only">
          {rows.length > 0 ? `${rows.length} suggestions available` : ''}
        </span>
        <Lightbulb className="w-3 h-3 inline mr-1" />
        Use arrow keys · Enter to accept · Esc to close
      </div>
    </div>
  )
}
