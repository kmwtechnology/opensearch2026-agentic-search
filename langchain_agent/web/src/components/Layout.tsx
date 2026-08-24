/**
 * Layout - Main application layout with three-panel design.
 *
 * Desktop:
 * ┌─────────────────────────────────────────────────────────────────┐
 * │  Conversations  │         Chat          │    Observability      │
 * │    Sidebar      │        Panel          │       Panel           │
 * │   (250px)       │       (50%)           │       (50%)           │
 * └─────────────────┴───────────────────────┴───────────────────────┘
 *
 * Mobile: Sidebar in drawer, Chat full width, Observability hidden
 */

import { useEffect, useState } from 'react'
import { Menu, X, Presentation, MessageSquare, Activity } from 'lucide-react'
import { ConversationsSidebar } from './ConversationsSidebar'
import { ChatPanel } from './ChatPanel'
import { ObservabilityPanel } from './ObservabilityPanel'

type MobileTab = 'chat' | 'pipeline'

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarWidth, setSidebarWidth] = useState(250)
  const [observabilityWidth, setObservabilityWidth] = useState(450)
  const [isResizingSidebar, setIsResizingSidebar] = useState(false)
  const [isResizingObservability, setIsResizingObservability] = useState(false)
  const [presentationMode, setPresentationMode] = useState(false)
  const [mobileTab, setMobileTab] = useState<MobileTab>('chat')
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  const closeSidebar = () => setSidebarOpen(false)

  const handleSidebarMouseDown = (event: React.MouseEvent) => {
    event.preventDefault()
    setIsResizingSidebar(true)
  }

  const handleObservabilityMouseDown = (event: React.MouseEvent) => {
    event.preventDefault()
    setIsResizingObservability(true)
  }

  useEffect(() => {
    if (!isResizingSidebar && !isResizingObservability) {
      document.body.style.cursor = ''
      return
    }

    document.body.style.cursor = 'col-resize'

    const handleMouseMove = (event: MouseEvent) => {
      if (isResizingSidebar) {
        const minWidth = 200
        const maxWidth = 400
        const newWidth = Math.min(Math.max(event.clientX, minWidth), maxWidth)
        setSidebarWidth(newWidth)
      }

      if (isResizingObservability) {
        const minWidth = 300
        const maxWidth = 1200
        const minChatWidth = 300
        const viewportWidth = window.innerWidth
        // Calculate max width based on available space
        const usedByResizer = 4 // resizer handle width
        const availableSpace = viewportWidth - sidebarWidth - usedByResizer - minChatWidth
        const constrainedMaxWidth = Math.min(maxWidth, Math.max(minWidth, availableSpace))
        const rawWidth = viewportWidth - event.clientX
        const newWidth = Math.min(Math.max(rawWidth, minWidth), constrainedMaxWidth)
        setObservabilityWidth(newWidth)
      }
    }

    const handleMouseUp = () => {
      setIsResizingSidebar(false)
      setIsResizingObservability(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
    }
  }, [isResizingSidebar, isResizingObservability, sidebarWidth])

  return (
    <div className="flex h-screen bg-gray-900 text-gray-100">
      {/* Mobile menu button — only show on chat tab so it doesn't overlap pipeline header */}
      {mobileTab === 'chat' && (
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          aria-label={sidebarOpen ? 'Close conversations menu' : 'Open conversations menu'}
          aria-expanded={sidebarOpen}
          className="md:hidden fixed top-4 left-4 z-40 p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {sidebarOpen ? (
            <X className="w-6 h-6" />
          ) : (
            <Menu className="w-6 h-6" />
          )}
        </button>
      )}

      {/* Presentation mode toggle button */}
      <button
        onClick={() => setPresentationMode(!presentationMode)}
        title={presentationMode ? 'Exit presentation mode' : 'Enter presentation mode (hides sidebar for demo)'}
        className="fixed top-4 right-4 z-40 p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-label={presentationMode ? 'Exit presentation mode' : 'Enter presentation mode'}
      >
        <Presentation className={`w-6 h-6 ${presentationMode ? 'text-blue-400' : 'text-gray-400'}`} />
      </button>

      {/* Mobile overlay backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 md:hidden"
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      {/* Sidebar - desktop visible, mobile in drawer (hidden in presentation mode) */}
      {!presentationMode && (
        <>
          <div
            className={`${
              sidebarOpen
                ? 'fixed inset-y-0 left-0 z-40 h-full'
                : 'hidden md:block md:flex-shrink-0 h-full'
            }`}
            style={{ width: `${sidebarWidth}px`, maxWidth: 'min(85vw, 400px)' }}
          >
            <ConversationsSidebar onConversationSelect={closeSidebar} />
          </div>

          {/* Resizer handle — desktop only */}
          <div
            className="hidden md:flex w-4 cursor-col-resize select-none"
            onMouseDown={handleSidebarMouseDown}
            aria-hidden="true"
          >
            <div className="mx-auto h-full w-px bg-gray-800 hover:bg-gray-600 transition-colors" />
          </div>
        </>
      )}

      {/* Main content area — pb-14 on mobile clears the fixed tab bar */}
      <div className="flex-1 flex min-w-0 overflow-hidden pb-14 md:pb-0">
        {/* Chat panel — full width on mobile (pipeline tab hides it), flex-1 on desktop */}
        <div
          className={`${
            mobileTab === 'chat' ? 'flex' : 'hidden md:flex'
          } flex-1 flex-col min-w-0 border-r border-gray-800 overflow-hidden`}
        >
          <ChatPanel />
        </div>

        {/* Observability panel — tab-controlled on mobile, always visible on desktop */}
        <div
          className={`${
            mobileTab === 'pipeline' ? 'flex' : 'hidden md:flex'
          } items-stretch flex-shrink-0 w-full md:w-auto`}
        >
          {/* Resizer handle — desktop only */}
          <div
            className="hidden md:flex items-stretch w-4 cursor-col-resize select-none"
            onMouseDown={handleObservabilityMouseDown}
            aria-hidden="true"
          >
            <div className="mx-auto h-full w-px bg-gray-800 hover:bg-gray-600 transition-colors" />
          </div>
          <div
            className="flex min-w-0 h-full overflow-hidden w-full md:w-auto"
            style={isMobile ? undefined : {
              width: `${observabilityWidth}px`,
              minWidth: '300px',
              maxWidth: '1200px',
            }}
          >
            <ObservabilityPanel />
          </div>
        </div>
      </div>

      {/* Mobile bottom tab bar */}
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-30 flex border-t border-gray-700 bg-gray-900"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        aria-label="Mobile navigation"
      >
        <button
          onClick={() => setMobileTab('chat')}
          aria-pressed={mobileTab === 'chat'}
          className={`flex-1 flex flex-col items-center gap-1 py-2 text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500 ${
            mobileTab === 'chat' ? 'text-blue-400' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <MessageSquare className="w-5 h-5" />
          Chat
        </button>
        <button
          onClick={() => setMobileTab('pipeline')}
          aria-pressed={mobileTab === 'pipeline'}
          className={`flex-1 flex flex-col items-center gap-1 py-2 text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500 ${
            mobileTab === 'pipeline' ? 'text-blue-400' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <Activity className="w-5 h-5" />
          Pipeline
        </button>
      </nav>
    </div>
  )
}
