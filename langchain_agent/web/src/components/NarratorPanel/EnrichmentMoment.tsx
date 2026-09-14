/**
 * The taxonomy correction sequence, rendered as one advancing card (#103).
 *
 * This is the demo's centrepiece and the reason the whole panel exists: a
 * shopper disputes a wrong tag, the catalog rebuilds itself, and the audience
 * watches it happen. Four phases, each visually distinct from the back of the
 * room:
 *
 *   started  → a live elapsed counter, because the ~20s re-index used to be a
 *              completely silent freeze and silence reads as a crash
 *   complete → what changed, plus the real doc count, plus the one button the
 *              presenter needs
 *   failed   → says plainly that the tag is unchanged
 *   declined → the guardrail firing, which is a feature worth showing
 */

import { useEffect, useState } from 'react'
import { AlertTriangle, Check, RefreshCw, ShieldX, X } from 'lucide-react'
import type { NarratorLine } from './narrate'

function useElapsedSeconds(startedAt: number | null, running: boolean): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!running || startedAt === null) return
    // 10Hz: fast enough that the tenths digit visibly moves (the audience
    // needs to see motion), cheap enough to be irrelevant.
    const id = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(id)
  }, [running, startedAt])

  if (startedAt === null) return 0
  return Math.max(0, (now - startedAt) / 1000)
}

interface Props {
  line: NarratorLine
  startedAt: number | null
  onRerun?: () => void
  rerunPending?: boolean
}

export function EnrichmentMoment({ line, startedAt, onRerun, rerunPending }: Props) {
  const running = line.enrichment === 'started'
  const elapsed = useElapsedSeconds(startedAt, running)

  const tone =
    line.enrichment === 'failed' || line.enrichment === 'declined'
      ? { border: 'border-[#9A3412]', bg: 'bg-[#FFF7ED]', fg: 'text-[#9A3412]' }
      : line.enrichment === 'started'
        ? { border: 'border-[#1E40AF]', bg: 'bg-[#EFF6FF]', fg: 'text-[#1E40AF]' }
        : { border: 'border-[#065F46]', bg: 'bg-[#ECFDF5]', fg: 'text-[#065F46]' }

  const Icon =
    line.enrichment === 'failed'
      ? AlertTriangle
      : line.enrichment === 'declined'
        ? ShieldX
        : line.enrichment === 'started'
          ? RefreshCw
          : Check

  // github-mode dispatches never report completion, so the re-run button
  // would sit enabled over a catalog that has not changed yet.
  const canRerun =
    line.enrichment === 'complete' && Boolean(line.docsProcessed) && Boolean(onRerun)

  return (
    <div className={`rounded-2xl border-4 ${tone.border} ${tone.bg} p-7 flex flex-col gap-5`}>
      <div className="flex items-center gap-4">
        <Icon
          className={`w-11 h-11 flex-shrink-0 ${tone.fg} ${running ? 'animate-spin' : ''}`}
          strokeWidth={2.5}
          aria-hidden="true"
        />
        <span
          className={`${tone.fg} font-bold uppercase tracking-[0.12em] text-[length:var(--text-stage-label)]`}
        >
          {line.label}
        </span>
      </div>

      <p className="text-[length:var(--text-stage-lead)] font-bold leading-tight text-[var(--color-stage-ink)]">
        {line.text}
      </p>

      {/* The before/after pair, only when this was a correction rather than a
          brand-new term. Never color alone — each half is labelled. */}
      {line.correctedFrom && line.enrichment === 'complete' && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-5 rounded-xl border-2 border-[#9A3412] bg-white px-6 py-4">
            <span className="flex items-center gap-2 w-40 flex-shrink-0">
              <X className="w-6 h-6 text-[#9A3412]" strokeWidth={3} aria-hidden="true" />
              <span className="font-bold uppercase tracking-[0.12em] text-[#9A3412] text-[length:var(--text-stage-label)]">
                Was
              </span>
            </span>
            <code className="font-mono text-[length:var(--text-stage-step)] font-semibold">
              {line.variant} → {line.correctedFrom}
            </code>
          </div>
          <div className="flex items-center gap-5 rounded-xl border-[3px] border-[#065F46] bg-white px-6 py-4">
            <span className="flex items-center gap-2 w-40 flex-shrink-0">
              <Check className="w-6 h-6 text-[#065F46]" strokeWidth={3} aria-hidden="true" />
              <span className="font-bold uppercase tracking-[0.12em] text-[#065F46] text-[length:var(--text-stage-label)]">
                Now
              </span>
            </span>
            <code className="font-mono text-[length:var(--text-stage-step)] font-semibold">
              {line.variant} → {line.canonical}
            </code>
          </div>
        </div>
      )}

      {/* The counter. This is the whole answer to "is it doing anything?" */}
      {running && (
        <div className="flex items-center gap-7 rounded-xl border-2 border-[var(--color-stage-border-soft)] bg-white px-6 py-5">
          <div className="flex flex-col gap-1">
            <span className="font-bold uppercase tracking-[0.12em] text-[var(--color-stage-ink-soft)] text-[length:var(--text-stage-label)]">
              Elapsed
            </span>
            <span
              className="font-mono text-6xl font-semibold leading-none tabular-nums"
              aria-live="off"
            >
              {elapsed.toFixed(1)}
              <span className="text-3xl text-[var(--color-stage-ink-soft)]">s</span>
            </span>
          </div>
          <p className="text-[length:var(--text-stage-body)] font-medium text-[var(--color-stage-ink-muted)]">
            Rebuilding all 9,618 products. This usually takes about 20 seconds.
          </p>
        </div>
      )}

      {canRerun && (
        <button
          onClick={onRerun}
          disabled={rerunPending}
          className="flex items-center justify-center gap-4 rounded-xl bg-[#065F46] px-7 py-5 text-white text-[1.75rem] font-bold disabled:opacity-60 focus:outline-none focus:ring-4 focus:ring-[#065F46]/40"
        >
          <RefreshCw
            className={`w-8 h-8 ${rerunPending ? 'animate-spin' : ''}`}
            strokeWidth={2.5}
            aria-hidden="true"
          />
          {rerunPending ? 'Starting a clean search…' : 'Re-run search with corrected taxonomy'}
        </button>
      )}

      {/* The cloud fallback. Locally this never appears. */}
      {line.enrichment === 'complete' && !line.docsProcessed && line.reindexRunUrl && (
        <p className="text-[length:var(--text-stage-body)] font-medium text-[var(--color-stage-ink-muted)]">
          The cloud build reports no completion signal back to the app, so the re-run button stays
          disabled. Build:{' '}
          <span className="font-mono break-all">{line.reindexRunUrl}</span>
        </p>
      )}
    </div>
  )
}
