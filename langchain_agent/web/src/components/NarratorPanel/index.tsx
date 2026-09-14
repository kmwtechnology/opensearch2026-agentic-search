/**
 * NarratorPanel — the right column during a demo (#103).
 *
 * Answers "what just happened" in sentences, at a size readable from the back
 * of a 300-person room. The dense observability panel still exists and is one
 * keypress away; this is what is on screen by default.
 *
 * Capped at MAX_VISIBLE_LINES so it never scrolls. A presenter mid-sentence
 * should not have to chase a line that slid off the bottom.
 */

import { useMemo } from 'react'
import { Brain, Compass, ListOrdered, Pencil, Search, ShieldCheck, Sparkles } from 'lucide-react'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { EnrichmentMoment } from './EnrichmentMoment'
import { narrate, visibleLines, type NarratorLine, type NarratorNode } from './narrate'

// Same hue assignments the observability panel has always used, so the two
// views read as the same app. Every entry pairs a color WITH an icon and a
// label — nothing here is distinguished by color alone.
const NODE_STYLE: Record<NarratorNode, { fg: string; tint: string; Icon: typeof Brain }> = {
  intent_classifier: { fg: '#065F46', tint: '#ECFDF5', Icon: Brain },
  query_evaluator: { fg: '#1E40AF', tint: '#EFF6FF', Icon: Compass },
  query_rewriter: { fg: '#0F766E', tint: '#F0FDFA', Icon: Pencil },
  retriever: { fg: '#5B21B6', tint: '#F5F3FF', Icon: Search },
  reranker: { fg: '#3730A3', tint: '#EEF2FF', Icon: ListOrdered },
  quality_gate: { fg: '#9A3412', tint: '#FFF7ED', Icon: ShieldCheck },
  agent: { fg: '#155E75', tint: '#ECFEFF', Icon: Sparkles },
  enrichment: { fg: '#065F46', tint: '#ECFDF5', Icon: Sparkles },
}

function Line({ line, lead }: { line: NarratorLine; lead: boolean }) {
  const style = NODE_STYLE[line.node]
  const { Icon } = style

  return (
    <div className="flex items-start gap-5">
      <span
        className="flex items-center justify-center rounded-xl border-2 flex-shrink-0"
        style={{
          borderColor: style.fg,
          backgroundColor: style.tint,
          width: 44,
          height: 44,
        }}
        aria-hidden="true"
      >
        <Icon style={{ color: style.fg }} strokeWidth={2.5} size={24} />
      </span>
      <span className="flex flex-col gap-1.5 min-w-0">
        <span
          className="font-bold uppercase tracking-[0.12em] text-[length:var(--text-stage-label)]"
          style={{ color: style.fg }}
        >
          {line.label}
        </span>
        <span
          className={
            lead
              ? 'text-[length:var(--text-stage-step)] font-bold leading-snug text-[var(--color-stage-ink)]'
              : 'text-[length:var(--text-stage-step)] font-medium leading-snug text-[var(--color-stage-ink-muted)]'
          }
        >
          {line.text}
        </span>
      </span>
    </div>
  )
}

interface Props {
  onRerun?: () => void
  rerunPending?: boolean
  onShowDetails?: () => void
}

export function NarratorPanel({ onRerun, rerunPending, onShowDetails }: Props) {
  const steps = useObservabilityStore((s) => s.steps)
  const isExecuting = useObservabilityStore((s) => s.isExecuting)
  const enrichmentStartedAt = useObservabilityStore((s) => s.enrichmentStartedAt)

  const lines = useMemo(() => {
    const all = steps.flatMap((step) => step.events)
    const narrated = all.map(narrate).filter((l): l is NarratorLine => l !== null)
    return visibleLines(narrated)
  }, [steps])

  // Pipeline order, top to bottom — the same path as the architecture diagram
  // the audience was just shown. (This used to render newest-first, which made
  // sense when the panel was a sliding feed; now that every stage keeps its own
  // line for the whole turn, following the pipeline reads better and stays put
  // while the presenter talks through it.)
  const ordered = lines
  const latestId = lines.length > 0 ? lines[lines.length - 1].id : null

  return (
    <section
      className="flex h-full w-full flex-col overflow-hidden rounded-2xl border-2 bg-[var(--color-stage-surface)] border-[var(--color-stage-border)]"
      aria-label="What just happened"
    >
      <header className="flex items-center justify-between border-b-2 border-[var(--color-stage-border-soft)] px-7 py-5">
        <h2 className="font-bold uppercase tracking-[0.12em] text-[var(--color-stage-ink-soft)] text-[length:var(--text-stage-label)]">
          What just happened
        </h2>
        {isExecuting && (
          <span className="flex items-center gap-2.5 rounded-full border-2 border-[#155E75] bg-[#ECFEFF] px-4 py-1">
            <span className="h-3 w-3 rounded-full bg-[#155E75] animate-pulse" aria-hidden="true" />
            <span className="font-bold text-[#155E75] text-[length:var(--text-stage-label)]">Thinking</span>
          </span>
        )}
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-hidden px-7 py-6">
        {ordered.length === 0 && (
          <p className="text-[length:var(--text-stage-body)] font-medium text-[var(--color-stage-ink-soft)]">
            Ask a question and the pipeline's reasoning appears here, one step at a time.
          </p>
        )}

        {ordered.map((line) =>
          line.node === 'enrichment' ? (
            <EnrichmentMoment
              key={line.id}
              line={line}
              startedAt={enrichmentStartedAt}
              onRerun={onRerun}
              rerunPending={rerunPending}
            />
          ) : (
            <Line key={line.id} line={line} lead={line.id === latestId} />
          )
        )}
      </div>

      <footer className="flex items-center justify-between border-t-2 border-[var(--color-stage-border-soft)] px-7 py-4">
        <span className="font-semibold text-[var(--color-stage-ink-soft)] text-[length:var(--text-stage-label)]">
          {steps.length} {steps.length === 1 ? 'step' : 'steps'}
        </span>
        <button
          onClick={onShowDetails}
          className="font-semibold text-[var(--color-stage-ink-soft)] text-[length:var(--text-stage-label)] focus:outline-none focus:ring-2 focus:ring-[#1E40AF] rounded"
        >
          Press <kbd className="rounded bg-[var(--color-stage-raised)] px-2 py-0.5 font-mono text-[1.25rem] text-[var(--color-stage-ink)]">F2</kbd> for full detail
        </button>
      </footer>
    </section>
  )
}
