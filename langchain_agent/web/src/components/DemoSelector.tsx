/**
 * DemoSelector — names the demo currently being run (#103).
 *
 * The presenter picks; nothing auto-detects. Auto-detection from the typed
 * query was considered and rejected: one improvised question or typo would
 * relabel the header mid-demo, in front of the audience, with no way to
 * correct it quickly.
 *
 * Rendered as a native <select> layered over the styled label — it gets
 * keyboard handling, an accessible name and the platform's own popup for
 * free, and none of those are worth reimplementing for a control that gets
 * touched twice a talk.
 */

import { ChevronDown } from 'lucide-react'
import { DEMOS, getDemo } from '../demos/registry'

interface Props {
  demoId: string
  onSelect: (id: string) => void
}

export function DemoSelector({ demoId, onSelect }: Props) {
  const demo = getDemo(demoId)

  return (
    <div className="flex flex-col gap-1">
      <span className="font-bold uppercase tracking-[0.12em] text-[var(--color-stage-ink-soft)] text-[length:var(--text-stage-label)]">
        Demo {DEMOS.findIndex((d) => d.id === demo.id) + 1} of {DEMOS.length}
      </span>
      <div className="relative flex items-center gap-3.5 rounded-2xl border-2 border-[var(--color-stage-border)] bg-[var(--color-stage-raised)] px-5 py-1.5 focus-within:ring-4 focus-within:ring-[#1E40AF]/40">
        <span className="text-[length:var(--text-stage-title)] font-bold tracking-tight">{demo.title}</span>
        <ChevronDown
          className="h-7 w-7 text-[var(--color-stage-ink-soft)]"
          strokeWidth={2.5}
          aria-hidden="true"
        />
        <select
          aria-label="Select demo"
          value={demo.id}
          onChange={(e) => onSelect(e.target.value)}
          className="absolute inset-0 cursor-pointer opacity-0"
        >
          {DEMOS.map((d) => (
            <option key={d.id} value={d.id}>
              {d.title}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
