/**
 * Layout — the presentation shell (#103).
 *
 * ┌───────────────────────────────────────────────────────────────┐
 * │  Demo selector · turn progress · New Demo · Details · Sign out │
 * ├──────────────────────────┬────────────────────────────────────┤
 * │        Chat (45%)        │   Narrator / Details (55%)         │
 * └──────────────────────────┴────────────────────────────────────┘
 *
 * This app is demoed live to ~300 people on a projector. Three things follow
 * from that and are deliberate:
 *
 *  - The conversations sidebar is gone, along with the presentation-mode
 *    toggle that used to hide it. The app is now permanently in the mode the
 *    toggle produced, so the toggle has nothing left to say. The links and
 *    the sign-out the sidebar hosted moved into the header rather than being
 *    quietly dropped.
 *  - No resizable panes. A drag handle is a thing to fumble on stage, and the
 *    45/55 split is already sized for 1920×1080.
 *  - Nothing scrolls except the chat message list. The narrator caps its own
 *    line count for exactly this reason.
 *
 * The dense observability panel is intact and one keypress (D) away.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  BookOpen,
  Check,
  ChevronRight,
  Code2,
  LayoutList,
  MessageSquare,
  Plus,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { ChatPanel } from './ChatPanel'
import { ObservabilityPanel } from './ObservabilityPanel'
import { NarratorPanel } from './NarratorPanel'
import { DemoSelector } from './DemoSelector'
import { DEFAULT_DEMO_ID, getDemo } from '../demos/registry'
import { useChatStore } from '../stores/chatStore'
import { useObservabilityStore } from '../stores/observabilityStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { apiPost } from '../utils/api'

type RightPane = 'narrator' | 'details'
type MobileTab = 'chat' | 'pipeline'

export function Layout() {
  const [demoId, setDemoId] = useState(DEFAULT_DEMO_ID)
  const [rightPane, setRightPane] = useState<RightPane>('narrator')
  const [mobileTab, setMobileTab] = useState<MobileTab>('chat')

  const isProcessing = useChatStore((s) => s.isProcessing)
  const isConnected = useChatStore((s) => s.isConnected)
  const pendingAutoSend = useChatStore((s) => s.pendingAutoSend)
  const startNewConversation = useChatStore((s) => s.startNewConversation)
  const { sendMessage } = useWebSocket()
  const clearObservability = useObservabilityStore((s) => s.clearState)

  const demo = getDemo(demoId)

  // Position in the script is tracked explicitly rather than derived from the
  // message count. Counting messages breaks on the taxonomy demo: its proof
  // turn deliberately starts a FRESH conversation, which empties `messages`
  // and would send the script back to turn 1 at the exact moment it matters.
  //
  // It also means an off-script question — which a presenter should be free to
  // ask — does not consume a scripted turn.
  const [turnCursor, setTurnCursor] = useState(0)
  const [isResetting, setIsResetting] = useState(false)
  const nextTurn = turnCursor < demo.turns.length ? demo.turns[turnCursor] : null
  const currentTurn = Math.min(turnCursor + 1, demo.turns.length)

  // F2 toggles the detail view.
  //
  // This was 'D', which was a mistake: a printable character cannot be
  // suppressed for a presenter whose cursor is sitting in the chat box. The
  // handler correctly declined to fire, but the letter still landed in the
  // input — a rehearsal produced the query "dshow me tan boots". F2 is
  // non-printable, so it works from anywhere including a focused input, and
  // needs no focus guard at all.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'F2') return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      e.preventDefault()
      setRightPane((p) => (p === 'narrator' ? 'details' : 'narrator'))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Restores the data defect a demo consumes. Safe to call when nothing needs
  // restoring — it is idempotent and takes about half a second.
  const armCatalog = useCallback(async () => {
    setIsResetting(true)
    try {
      const res = await apiPost('/api/admin/demo-reset')
      if (!res.ok) {
        // 404 means this deployment has the demo machinery switched off, which
        // is a legitimate configuration rather than a failure.
        console.warn('Demo reset unavailable:', res.status)
      }
    } catch (err) {
      console.warn('Demo reset failed:', err)
    } finally {
      setIsResetting(false)
    }
  }, [])

  // Restart rewinds the SCRIPT and the DATA. Clearing only the chat was a
  // trap: the taxonomy demo rewrites the catalog when it succeeds, so a
  // "restarted" demo would replay against already-corrected data and quietly
  // show nothing wrong — the failure mode is a demo that looks fine and
  // proves nothing. The reindex takes ~20s, hence the explicit busy state.
  const handleRestart = useCallback(async () => {
    setTurnCursor(0)
    startNewConversation()
    // Clear the narration too. startNewConversation only empties the chat, so
    // without this the right-hand panel keeps describing the run that just
    // ended — a fresh turn 1 sitting beside the previous run's quality-gate
    // verdict, which is exactly the kind of mismatch an audience notices.
    clearObservability()
    await armCatalog()
  }, [startNewConversation, clearObservability, armCatalog])

  const handleSelectDemo = useCallback(
    (id: string) => {
      setDemoId(id)
      setTurnCursor(0)
      // Selecting a demo resets the thread — otherwise the previous demo's
      // history leaks into this one's intent classification.
      startNewConversation()
      clearObservability()
      if (getDemo(id).needsArming) {
        void armCatalog()
      }
    },
    [startNewConversation, clearObservability, armCatalog]
  )

  // Next runs the upcoming scripted turn, so the presenter can drive the whole
  // demo from one button and spend the time talking over the narrator instead
  // of typing. It SENDS rather than only filling the box: the point is to
  // click through the turns, and a fill-only button would need a second
  // keystroke per turn.
  //
  // The chat input stays fully usable — Next is a shortcut for the script, not
  // a replacement for asking something off-script.
  // Derives the turn inside the callback and depends only on primitives.
  // Closing over the `nextTurn` OBJECT instead makes the React Compiler bail
  // out of optimizing this component entirely ("existing memoization could not
  // be preserved"), which CI treats as an error.
  const handleNext = useCallback(async () => {
    const selected = getDemo(demoId)
    const turn = selected.turns[turnCursor]
    if (!turn || isProcessing || pendingAutoSend || !isConnected || isResetting) return
    // Re-arm immediately before the FIRST turn of a demo that consumes a data
    // defect. Selecting the demo already arms it, but this is the gate that
    // actually matters: it covers arriving via page load, via Restart, or
    // simply running the demo twice in a row. A presenter should never have to
    // remember a reset step, and should never get a turn 1 that silently has
    // nothing to demonstrate.
    if (turnCursor === 0 && selected.needsArming) {
      await armCatalog()
    }
    if (turn.requiresNewConversation) {
      // Same path the taxonomy re-run button uses: a fresh thread, with the
      // query fired once the NEW socket reports connection_established.
      startNewConversation(turn.query)
    } else {
      sendMessage(turn.query)
    }
    setTurnCursor((c) => c + 1)
  }, [
    demoId,
    turnCursor,
    isProcessing,
    pendingAutoSend,
    isConnected,
    isResetting,
    armCatalog,
    startNewConversation,
    sendMessage,
  ])

  // The taxonomy demo's proof turn must run in a FRESH conversation: in-thread,
  // the query rewriter folds the correction turn into the query and it falls
  // down a lexical path that isn't comparable to turn 1.
  const handleRerun = useCallback(() => {
    const proofTurn = getDemo('taxonomy-ingestion').turns.find((t) => t.requiresNewConversation)
    startNewConversation(proofTurn?.query ?? 'show me tan boots')
  }, [startNewConversation])

  return (
    <div className="flex h-screen flex-col bg-[var(--color-stage-bg)] text-[var(--color-stage-ink)]">
      <header className="flex flex-shrink-0 flex-wrap items-center gap-8 border-b-[3px] border-[var(--color-stage-border)] bg-[var(--color-stage-surface)] px-7 py-4">
        <DemoSelector demoId={demoId} onSelect={handleSelectDemo} />

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex items-center gap-2.5" aria-hidden="true">
            {demo.turns.map((_, i) => (
              <span
                key={i}
                className="h-2.5 w-14 rounded-full"
                style={{
                  backgroundColor: i < turnCursor ? '#065F46' : 'var(--color-stage-border)',
                }}
              />
            ))}
          </div>
          {/* The expected NEXT query, not the long "what to watch for" blurb —
              it fits on one line and it is the thing the presenter actually
              needs in front of them. A presenter who improvises is not
              corrected; this stays a hint. */}
          <p className="truncate text-[length:var(--text-stage-body)] font-semibold text-[var(--color-stage-ink-muted)]">
            {nextTurn ? (
              <>
                <span className="text-[var(--color-stage-ink-soft)]">
                  Turn {currentTurn} of {demo.turns.length} —{' '}
                </span>
                <span className="text-[var(--color-stage-ink)]">“{nextTurn.query}”</span>
                {nextTurn.requiresNewConversation && (
                  <span className="ml-3 rounded-lg border-2 border-[#9A3412] px-2.5 py-0.5 text-[1.25rem] font-bold uppercase tracking-wider text-[#9A3412]">
                    New chat first
                  </span>
                )}
              </>
            ) : (
              demo.subtitle
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Primary stage control: run the next scripted turn. Sized and
              colored to be the obvious thing to click repeatedly. */}
          <button
            onClick={() => void handleNext()}
            // Also gated on the socket being open. sendMessage() bails silently
            // on a socket that is not OPEN, so for the second or so after a
            // page load a click on Next did nothing at all and gave no clue why
            // — the worst possible behaviour for the one button a presenter
            // leans on.
            disabled={
              !nextTurn || isProcessing || Boolean(pendingAutoSend) || !isConnected || isResetting
            }
            aria-label={
              nextTurn
                ? `Run turn ${currentTurn} of ${demo.turns.length}: ${nextTurn.query}`
                : 'Demo complete'
            }
            className="flex items-center gap-2.5 rounded-xl bg-[#065F46] px-6 py-3 text-[1.5rem] font-bold text-white disabled:bg-[var(--color-stage-raised)] disabled:text-[var(--color-stage-ink-soft)] focus:outline-none focus:ring-4 focus:ring-[#065F46]/40"
          >
            {!isConnected ? (
              <>Connecting…</>
            ) : nextTurn ? (
              <>
                Next
                <span className="font-semibold opacity-90">
                  {currentTurn}/{demo.turns.length}
                </span>
                <ChevronRight className="h-7 w-7" strokeWidth={3} aria-hidden="true" />
              </>
            ) : (
              <>
                <Check className="h-7 w-7" strokeWidth={3} aria-hidden="true" />
                Demo complete
              </>
            )}
          </button>
          <button
            onClick={() => void handleRestart()}
            disabled={isResetting}
            title="Clear the conversation and restore the catalog's original tagging"
            className="flex items-center gap-2.5 rounded-xl border-2 border-[var(--color-stage-border)] bg-white px-4 py-2.5 text-[1.4rem] font-semibold disabled:text-[var(--color-stage-ink-soft)] focus:outline-none focus:ring-4 focus:ring-[#1E40AF]/40"
          >
            <Plus
              className={`h-6 w-6 ${isResetting ? 'animate-spin' : ''}`}
              strokeWidth={2.5}
              aria-hidden="true"
            />
            {isResetting ? 'Resetting…' : 'Restart'}
          </button>
          <button
            onClick={() => setRightPane((p) => (p === 'narrator' ? 'details' : 'narrator'))}
            aria-pressed={rightPane === 'details'}
            className="flex items-center gap-2.5 rounded-xl border-2 border-[var(--color-stage-border)] bg-white px-4 py-2.5 text-[1.4rem] font-semibold focus:outline-none focus:ring-4 focus:ring-[#1E40AF]/40"
          >
            {rightPane === 'details' ? (
              <Sparkles className="h-6 w-6" strokeWidth={2.5} aria-hidden="true" />
            ) : (
              <LayoutList className="h-6 w-6" strokeWidth={2.5} aria-hidden="true" />
            )}
            {rightPane === 'details' ? 'Narration' : 'Details'}
            <kbd className="rounded bg-[var(--color-stage-raised)] px-2 py-0.5 font-mono text-[1.25rem] text-[var(--color-stage-ink-soft)]">
              F2
            </kbd>
          </button>
          {/* These three lived only in the sidebar that this layout removes. */}
          <Link
            to="/guide"
            aria-label="Guide"
            className="rounded-xl border-2 border-[var(--color-stage-border)] bg-white p-2.5 focus:outline-none focus:ring-4 focus:ring-[#1E40AF]/40"
          >
            <BookOpen className="h-6 w-6" strokeWidth={2.5} aria-hidden="true" />
          </Link>
          <Link
            to="/swagger"
            aria-label="API reference"
            className="rounded-xl border-2 border-[var(--color-stage-border)] bg-white p-2.5 focus:outline-none focus:ring-4 focus:ring-[#1E40AF]/40"
          >
            <Code2 className="h-6 w-6" strokeWidth={2.5} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 gap-6 p-6 md:grid-cols-[45fr_55fr]">
        <div
          className={`${mobileTab === 'chat' ? 'flex' : 'hidden md:flex'} min-h-0 min-w-0 overflow-hidden rounded-2xl border-2 border-[var(--color-stage-border)] bg-[var(--color-stage-surface)]`}
        >
          <ChatPanel />
        </div>

        <div
          className={`${mobileTab === 'pipeline' ? 'flex' : 'hidden md:flex'} min-h-0 min-w-0 overflow-hidden`}
        >
          {rightPane === 'narrator' ? (
            <NarratorPanel
              onRerun={handleRerun}
              rerunPending={Boolean(pendingAutoSend)}
              onShowDetails={() => setRightPane('details')}
            />
          ) : (
            <ObservabilityPanel />
          )}
        </div>
      </main>

      <nav
        className="fixed inset-x-0 bottom-0 z-30 flex border-t-2 border-[var(--color-stage-border)] bg-[var(--color-stage-surface)] md:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        aria-label="Mobile navigation"
      >
        <button
          onClick={() => setMobileTab('chat')}
          aria-pressed={mobileTab === 'chat'}
          className="flex flex-1 flex-col items-center gap-1 py-2 text-sm font-semibold"
        >
          <MessageSquare className="h-5 w-5" aria-hidden="true" />
          Chat
        </button>
        <button
          onClick={() => setMobileTab('pipeline')}
          aria-pressed={mobileTab === 'pipeline'}
          className="flex flex-1 flex-col items-center gap-1 py-2 text-sm font-semibold"
        >
          <LayoutList className="h-5 w-5" aria-hidden="true" />
          Pipeline
        </button>
      </nav>
    </div>
  )
}
