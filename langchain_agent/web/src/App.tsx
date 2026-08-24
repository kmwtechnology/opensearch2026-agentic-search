import { useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { LoginScreen } from './components/LoginScreen'
import { SwaggerPage } from './pages/SwaggerPage'
import { GuidePage } from './pages/GuidePage'
import { useAuthStore } from './stores/authStore'
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

/**
 * AuthGate — checks /api/auth/status on mount and either renders the
 * LoginScreen or the wrapped app.
 *
 * The status probe is silent on first paint (just shows a placeholder)
 * to avoid a login-flash for users with a valid session cookie.
 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const isChecking = useAuthStore((s) => s.isChecking)
  const checkAuth = useAuthStore((s) => s.checkAuth)

  useEffect(() => {
    void checkAuth()
  }, [checkAuth])

  if (isChecking) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-gray-400 text-sm">Checking session…</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <LoginScreen />
  }

  return <>{children}</>
}

function App() {
  return (
    <BrowserRouter>
      <AuthGate>
        <Routes>
          <Route path="/" element={<ChatApp />} />
          <Route path="/swagger" element={<SwaggerPage />} />
          <Route path="/guide" element={<GuidePage />} />
        </Routes>
      </AuthGate>
    </BrowserRouter>
  )
}

export default App
