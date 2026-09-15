import { useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { SwaggerPage } from './pages/SwaggerPage'
import { GuidePage } from './pages/GuidePage'
import { useChatStore } from './stores/chatStore'
import { useWebSocket } from './hooks/useWebSocket'

function ChatApp() {
  const threadId = useChatStore((s) => s.threadId)
  const setThreadId = useChatStore((s) => s.setThreadId)
  const { connect } = useWebSocket()

  // Generate initial thread ID if needed
  useEffect(() => {
    if (!threadId) {
      const newThreadId = `conversation_${Math.random().toString(36).slice(2, 10)}`
      setThreadId(newThreadId)
    }
  }, [threadId, setThreadId])

  // Connect WebSocket when thread ID changes
  useEffect(() => {
    if (threadId) {
      // Small delay to let previous connection close
      const timer = setTimeout(() => {
        connect(threadId)
      }, 100)
      return () => clearTimeout(timer)
    }
  }, [threadId, connect])

  return <Layout />
}

function App() {
  // No AuthGate (#103, made permanent in #135). The shared-password screen
  // put a password prompt between a presenter and their own demo, on stage.
  // The backend has no login gate to match -- every route is same-origin-only.
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatApp />} />
        <Route path="/swagger" element={<SwaggerPage />} />
        <Route path="/guide" element={<GuidePage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
