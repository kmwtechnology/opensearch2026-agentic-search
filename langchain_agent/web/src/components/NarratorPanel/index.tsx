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

import { useEffect, useMemo, useRef, useState } from 'react'
import { NODE_STYLE } from './nodeStyle'
import type { NarratorGauge } from './narrate'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { EnrichmentMoment } from './EnrichmentMoment'
import { GroundTruthMoment } from './GroundTruthMoment'
import { narrate, visibleLines, type NarratorLine } from './narrate'


/**
 * A gauge, sized for a projector: a thick bar, a filled portion, and for a
 * score gauge a hard tick where the threshold sits, so "did it clear the bar"
 * is legible from the back of the room without reading either number.
 *
 * Never color alone — the caption under the bar always states the numbers.
 *
 * The fill animates in from 0 on mount rather than rendering at its final
 * width immediately — the reveal reads as a live measurement landing rather
 * than a fact that was just always there.
 */
function Gauge({ gauge, fg }: { gauge: NarratorGauge; fg: string }) {
  const pct = Math.round(gauge.value * 100)
  const clears = gauge.marker === undefined || gauge.value >= gauge.marker
  const [displayPct, setDisplayPct] = useState(0)

  useEffect(() => {
    const id = window.setTimeout(() => setDisplayPct(pct), 50)
    return () => window.clearTimeout(id)
  }, [pct])

  return (
    <span className="flex flex-col gap-1 mt-1 max-w-[30rem]">
      <span className="flex items-center justify-between text-[length:var(--text-stage-label)] font-semibold text-[var(--color-stage-ink-soft)]">
        <span>{gauge.leftLabel}</span>
        <span>{gauge.rightLabel}</span>
      </span>
      <span
        className="relative block h-4 w-full rounded-full border-2"
        style={{ borderColor: fg, backgroundColor: 'var(--color-stage-raised)' }}
      >
        <span
          className="absolute left-0 top-0 bottom-0 rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${displayPct}%`, backgroundColor: fg }}
        />
        {gauge.marker !== undefined && (
          <span
            className="absolute top-[-6px] bottom-[-6px] w-1 rounded"
            style={{
              left: `${Math.round(gauge.marker * 100)}%`,
              backgroundColor: 'var(--color-stage-ink)',
            }}
          />
        )}
      </span>
      <span className="text-[length:var(--text-stage-label)] font-semibold text-[var(--color-stage-ink-muted)]">
        {gauge.caption}
        {gauge.marker !== undefined && (clears ? ' — cleared' : ' — under the bar')}
      </span>
    </span>
  )
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
        {line.gauge && <Gauge gauge={line.gauge} fg={style.fg} />}
      </span>
    </div>
  )
}

export function NarratorPanel() {
  const steps = useObservabilityStore((s) => s.steps)
  const isExecuting = useObservabilityStore((s) => s.isExecuting)
  const enrichmentStartedAt = useObservabilityStore((s) => s.enrichmentStartedAt)
  // `pipeline_summary` fires after the turn's step is already marked "done"
  // (it's computed once generation and judging finish), so it never lands in
  // any step's `events` array — `addEvent` only appends to a currently
  // *running* step. Read it from its own dedicated store slice instead, the
  // same way `PipelineSummaryCard` already does, rather than relying on the
  // step-events plumbing this event structurally can't reach (#130).
  const pipelineSummary = useObservabilityStore((s) => s.pipelineSummary)

  // Two tabs, not one panel that the ground-truth card used to take over
  // entirely: `lookup_judgments()` runs on every query in every demo, so any
  // exact-match query can surface real ground truth mid-Arc-1 or mid-Arc-2,
  // not just in the dedicated bonus scene this was originally built for.
  // Hiding that turn's actual pipeline steps whenever it happened to fire was
  // surprising, not helpful — so Steps and Ground Truth get their own tab
  // each, and neither covers the other.
  const [activeTab, setActiveTab] = useState<'steps' | 'ground-truth'>('steps')

  // Reset to the steps tab at the start of every new turn, so a ground-truth
  // tab selection left over from an earlier turn doesn't silently hide the
  // new turn's steps behind a tab nobody is looking at. Adjusted during
  // render (React's documented pattern for "reset state when a value
  // changes") rather than in an Effect, which would cost an extra render
  // pass for no benefit here.
  const [prevIsExecuting, setPrevIsExecuting] = useState(isExecuting)
  if (isExecuting !== prevIsExecuting) {
    setPrevIsExecuting(isExecuting)
    if (isExecuting) setActiveTab('steps')
  }

  // Pipeline order, top to bottom — the same path as the architecture diagram
  // the audience was just shown. (This used to render newest-first, which made
  // sense when the panel was a sliding feed; now that every stage keeps its own
  // line for the whole turn, following the pipeline reads better and stays put
  // while the presenter talks through it.)
  const stepLines = useMemo(() => {
    const all = steps.flatMap((step) => step.events)
    const narrated = all.map(narrate).filter((l): l is NarratorLine => l !== null)
    return visibleLines(narrated)
  }, [steps])

  const groundTruthCard = useMemo(
    () => (pipelineSummary ? narrate(pipelineSummary) : null),
    [pipelineSummary]
  )

  const ordered = activeTab === 'ground-truth' && groundTruthCard ? [groundTruthCard] : stepLines
  const latestId = ordered.length > 0 ? ordered[ordered.length - 1].id : null

  // Scroll hardening (#130): `visibleLines`'s caps are tuned for a 1920x1080
  // fullscreen viewport (#108). On anything shorter — a smaller external
  // display, a non-100% zoom, browser chrome eating more than expected — the
  // scroll region below is the safety net, but a silent scrollbar reads as
  // "content vanished," not "more below." Auto-scroll to the newest line and
  // show a fade only while there is genuinely more to see.
  const scrollRef = useRef<HTMLDivElement>(null)
  const [canScrollMore, setCanScrollMore] = useState(false)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [latestId])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const update = () => {
      setCanScrollMore(el.scrollHeight - el.scrollTop - el.clientHeight > 4)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    el.addEventListener('scroll', update)
    return () => {
      observer.disconnect()
      el.removeEventListener('scroll', update)
    }
  }, [ordered])

  return (
    <section
      className="flex h-full w-full flex-col overflow-hidden rounded-2xl border-2 bg-[var(--color-stage-surface)] border-[var(--color-stage-border)]"
      aria-label="What just happened"
    >
      <header className="flex items-center justify-between border-b-2 border-[var(--color-stage-border-soft)] px-7 py-5">
        <h2 className="text-[length:var(--text-stage-body)] font-semibold text-[var(--color-stage-ink)]">
          What just happened
        </h2>
        {isExecuting && (
          <span className="flex items-center gap-2.5 rounded-full border-2 border-[#155E75] bg-[#ECFEFF] px-4 py-1">
            <span className="h-3 w-3 rounded-full bg-[#155E75] animate-pulse" aria-hidden="true" />
            <span className="font-bold text-[#155E75] text-[length:var(--text-stage-label)]">Thinking</span>
          </span>
        )}
      </header>

      {/* Only shown when this turn actually has a ground-truth reveal to
          show — an ordinary turn with no exact-match judgment renders no
          tab bar at all, identical to the panel before tabs existed. */}
      {groundTruthCard && (
        <div
          role="tablist"
          aria-label="What just happened views"
          className="flex gap-2 border-b-2 border-[var(--color-stage-border-soft)] px-7 pt-4"
        >
          {(
            [
              ['steps', 'Steps'],
              ['ground-truth', 'Ground Truth'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={activeTab === key}
              onClick={() => setActiveTab(key)}
              className="px-4 py-2 -mb-0.5 rounded-t-lg border-2 border-b-0 font-semibold text-[length:var(--text-stage-label)] transition-colors"
              style={
                activeTab === key
                  ? {
                      backgroundColor: 'var(--color-stage-surface)',
                      borderColor: 'var(--color-stage-border-soft)',
                      color: 'var(--color-stage-ink)',
                    }
                  : {
                      backgroundColor: 'transparent',
                      borderColor: 'transparent',
                      color: 'var(--color-stage-ink-soft)',
                    }
              }
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/*
        `overflow-y-auto`, not `overflow-hidden` (#108).

        The line cap in `visibleLines` is what keeps this panel from needing to
        scroll, and that remains the design. This is the safety net underneath
        it: with `overflow-hidden`, anything that did overflow — a longer
        filter summary, a wrapped rewrite, a shorter projector — became
        permanently unreachable rather than merely inconvenient, with no
        on-screen sign that content had been cut. Failing to a scrollbar is
        strictly better than failing to silence.
      */}
      <div className="relative flex flex-1 min-h-0 flex-col">
        <div ref={scrollRef} className="flex flex-1 flex-col gap-5 overflow-y-auto px-7 py-6">
          {ordered.length === 0 && (
            <p className="text-[length:var(--text-stage-body)] font-medium text-[var(--color-stage-ink-soft)]">
              Ask a question and the pipeline's reasoning appears here, one step at a time.
            </p>
          )}

          {ordered.map((line) => (
            <div key={line.id} className="animate-fade-in-up">
              {line.node === 'enrichment' ? (
                <EnrichmentMoment line={line} startedAt={enrichmentStartedAt} />
              ) : line.node === 'ground_truth' ? (
                <GroundTruthMoment line={line} />
              ) : (
                <Line line={line} lead={line.id === latestId} />
              )}
            </div>
          ))}
        </div>

        {/* "There's more below" affordance — only shown while genuinely true. */}
        {canScrollMore && (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-14 rounded-b-2xl"
            style={{
              background: 'linear-gradient(to bottom, transparent, var(--color-stage-surface))',
            }}
            aria-hidden="true"
          />
        )}
      </div>

      <footer className="border-t-2 border-[var(--color-stage-border-soft)] px-7 py-4">
        <span className="font-semibold text-[var(--color-stage-ink-soft)] text-[length:var(--text-stage-label)]">
          {/* Always the Steps tab's count, regardless of which tab is active
              — "1 step" while looking at the one-card Ground Truth tab would
              describe that tab, not the turn's actual pipeline step count. */}
          {stepLines.length} {stepLines.length === 1 ? 'step' : 'steps'}
        </span>
      </footer>
    </section>
  )
}
