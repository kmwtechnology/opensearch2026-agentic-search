/**
 * The bonus scene's payoff, rendered as one card (#130).
 *
 * Every other turn's Pipeline Quality Summary is a self-referential proxy —
 * the reranker grading its own homework. This turn is different: real ESCI
 * relevance judgments exist for the query, so the panel can show an actual
 * NDCG@10 climb across retrieval stages instead of a confidence heuristic.
 * That distinction is the entire point of the scene, so it gets a bar chart,
 * not a table — the climb should be visible at a glance from the back of the
 * room, the same way the alpha and quality gauges are.
 */

import { useEffect, useState } from 'react'
import { NODE_STYLE } from './nodeStyle'
import type { GroundTruthStage, NarratorLine } from './narrate'

const { fg, tint, Icon } = NODE_STYLE.ground_truth

function Bar({ stage, delayMs }: { stage: GroundTruthStage; delayMs: number }) {
  const [pct, setPct] = useState(0)
  const target = Math.max(0, Math.min(100, Math.round(stage.ndcg10 * 100)))

  useEffect(() => {
    const id = window.setTimeout(() => setPct(target), delayMs)
    return () => window.clearTimeout(id)
  }, [target, delayMs])

  const isLast = stage.stage === 'reranked'

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-[length:var(--text-stage-label)] font-semibold text-[var(--color-stage-ink-soft)]">
        <span>{stage.label}</span>
        <span className="flex items-center gap-3">
          {isLast && (
            <span
              className="rounded-full border-2 bg-white px-3 py-0.5 font-bold"
              style={{ borderColor: fg, color: fg }}
            >
              {stage.judgedCount}/10 judged
            </span>
          )}
          <span className="font-mono font-bold text-[var(--color-stage-ink)]">
            {stage.ndcg10.toFixed(3)}
          </span>
        </span>
      </div>
      <div
        className="relative h-6 w-full rounded-full border-2"
        style={{ borderColor: fg, backgroundColor: 'var(--color-stage-raised)' }}
      >
        <span
          className="absolute left-0 top-0 bottom-0 rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${pct}%`, backgroundColor: fg }}
        />
      </div>
    </div>
  )
}

interface Props {
  line: NarratorLine
}

export function GroundTruthMoment({ line }: Props) {
  const stages = line.groundTruthStages ?? []

  return (
    <div
      className="rounded-2xl border-4 p-7 flex flex-col gap-5"
      style={{ borderColor: fg, backgroundColor: tint }}
    >
      <div className="flex items-center gap-4">
        <span
          className="flex items-center justify-center rounded-xl border-2 flex-shrink-0"
          style={{ borderColor: fg, backgroundColor: '#ffffff', width: 44, height: 44 }}
          aria-hidden="true"
        >
          <Icon style={{ color: fg }} strokeWidth={2.5} size={24} />
        </span>
        <span
          className="font-bold uppercase tracking-[0.12em]"
          style={{ color: fg, fontSize: 'var(--text-stage-label)' }}
        >
          {line.label}
        </span>
      </div>

      <p className="text-[length:var(--text-stage-lead)] font-bold leading-tight text-[var(--color-stage-ink)]">
        {line.text}
      </p>

      <div className="flex flex-col gap-4 rounded-xl border-2 border-[var(--color-stage-border-soft)] bg-white px-6 py-5">
        {stages.map((stage, i) => (
          <Bar key={stage.stage} stage={stage} delayMs={80 * i} />
        ))}
      </div>

      <p className="text-[length:var(--text-stage-body)] font-medium text-[var(--color-stage-ink-muted)]">
        Scored against Amazon's own ESCI relevance judgments — an external, academic ground
        truth, not this system grading its own results.
      </p>
    </div>
  )
}
