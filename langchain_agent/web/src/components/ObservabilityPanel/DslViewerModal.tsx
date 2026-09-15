/**
 * DslViewerModal - Shows the raw OpenSearch DSL JSON body for a query that
 * the retriever sent to the cluster. Used by the eye-icon triggers on the
 * hybrid query, BM25 baseline query, and quality-gate retry cards.
 *
 * The body is shown verbatim except for embedding vectors, which are
 * replaced upstream with a placeholder string for readability.
 */

import { useEffect, useRef, useState } from 'react'
import { X, Copy, Check } from 'lucide-react'

interface DslViewerModalProps {
  isOpen: boolean
  title: string
  subtitle?: string
  body: Record<string, unknown> | null | undefined
  index?: string
  params?: Record<string, string>
  onClose: () => void
}

function buildRequestLine(index?: string, params?: Record<string, string>): string | null {
  if (!index) return null
  const qs = params && Object.keys(params).length > 0
    ? '?' + Object.entries(params).map(([k, v]) => `${k}=${v}`).join('&')
    : ''
  return `POST /${index}/_search${qs}`
}

export function DslViewerModal({ isOpen, title, subtitle, body, index, params, onClose }: DslViewerModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    dialogRef.current?.focus()

    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(t)
  }, [copied])

  if (!isOpen) return null

  const json = body ? JSON.stringify(body, null, 2) : '// no DSL body available'
  const requestLine = buildRequestLine(index, params)
  const copyText = requestLine ? `${requestLine}\n${json}` : json

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyText)
      setCopied(true)
    } catch {
      // Clipboard may be unavailable (insecure context, denied permission).
      // Fail silently — the user can still select and copy manually.
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="bg-[var(--color-stage-surface)] rounded-lg shadow-xl border border-[var(--color-stage-border)] max-w-3xl w-full max-h-[80vh] flex flex-col"
        role="dialog"
        aria-labelledby="dsl-viewer-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 p-4 border-b border-[var(--color-stage-border)]">
          <div className="min-w-0">
            <h2 id="dsl-viewer-title" className="text-[var(--text-stage-body)] font-semibold text-[var(--color-stage-ink)]">
              {title}
            </h2>
            {subtitle && <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] mt-0.5">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={handleCopy}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[1.25rem] text-[var(--color-stage-ink-muted)] hover:text-[var(--color-stage-ink)] hover:bg-[var(--color-stage-raised)] border border-[var(--color-stage-border)] transition-colors"
              aria-label="Copy DSL to clipboard"
              disabled={!body}
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#065F46]" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  Copy
                </>
              )}
            </button>
            <button
              onClick={onClose}
              aria-label="Close DSL viewer"
              className="text-[var(--color-stage-ink-soft)] hover:text-[var(--color-stage-ink)] p-1"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/*
          Palette, aligned with the rest of the projector UI (#103).

          This block used to pair bg-gray-950 with --color-stage-ink — the
          near-black ink meant for LIGHT surfaces — so it rendered dark grey on
          dark grey, and the /80 and /60 alphas washed the "dark" ground halfway
          back to page white. The request line was #9A3412, which is
          --color-node-gate (the quality-gate hue) used raw: on a projector a
          burnt-red header reads as an error, and it borrowed a hue that means
          something specific elsewhere in this UI.

          The app is light-ground everywhere, so the code block is too: the
          raised surface, the standard ink, the standard border. The request
          line carries the RETRIEVER hue and its tint, because that is what this
          panel is showing — a retrieval query — and those tokens are already
          the 800-weight shades chosen to clear 7:1 on a light ground.
        */}
        <div className="flex-1 overflow-auto p-4">
          {requestLine && (
            <pre className="text-[1.25rem] font-mono whitespace-pre bg-[var(--color-node-retriever-tint)] text-[var(--color-node-retriever)] rounded-t p-3 border border-b-0 border-[var(--color-stage-border)]">
              {requestLine}
            </pre>
          )}
          <pre
            className={`text-[1.25rem] text-[var(--color-stage-ink)] font-mono whitespace-pre bg-[var(--color-stage-raised)] p-3 border border-[var(--color-stage-border)] ${
              requestLine ? 'rounded-b' : 'rounded'
            }`}
          >
            {json}
          </pre>
          <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] mt-3">
            Embedding vectors are replaced with a placeholder for readability. Paste the request
            line + body into OpenSearch's Dev Tools or any REST client to inspect or replay.
          </p>
        </div>
      </div>
    </div>
  )
}
