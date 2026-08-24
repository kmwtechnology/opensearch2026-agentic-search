/**
 * Tests for the sign-out button in ConversationsSidebar.
 *
 * Two-click confirm pattern (mirrors the Clear All button) — first click
 * arms the confirm state, second click within 3 s actually calls
 * authStore.logout(). The logout endpoint is exercised in
 * tests/unit/test_auth_routes.py; this test only owns the UI flow.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ConversationsSidebar } from '../index'
import { useAuthStore } from '../../../stores/authStore'
import { useChatStore } from '../../../stores/chatStore'
import { useObservabilityStore } from '../../../stores/observabilityStore'

vi.mock('../../../utils/api', () => ({
  apiGet: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] } as Response)),
  apiDelete: vi.fn(() => Promise.resolve({ ok: true } as Response)),
}))

const renderSidebar = () =>
  render(
    <MemoryRouter>
      <ConversationsSidebar />
    </MemoryRouter>
  )

beforeEach(() => {
  // Reset stores between tests
  useChatStore.setState({
    threadId: null,
    messages: [],
    isProcessing: false,
    streamingContent: '',
    queuedMessages: [],
    isConnected: false,
    isConnecting: false,
    connectionError: null,
    conversations: [],
    conversationsLoading: false,
    inputFocusTrigger: 0,
  })
  useObservabilityStore.setState({ executionStartTime: null } as never)
  useAuthStore.setState({
    isAuthenticated: true,
    isChecking: false,
    isLoggingIn: false,
    loginError: null,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ConversationsSidebar — sign-out button', () => {
  it('renders a sign-out button', () => {
    renderSidebar()
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })

  it('first click arms the confirm state without calling logout', async () => {
    const logoutSpy = vi.fn(() => Promise.resolve())
    useAuthStore.setState({ logout: logoutSpy } as never)

    renderSidebar()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /sign out/i }))

    expect(screen.getByRole('button', { name: /click again to confirm/i })).toBeInTheDocument()
    expect(logoutSpy).not.toHaveBeenCalled()
  })

  it('second click calls authStore.logout', async () => {
    const logoutSpy = vi.fn(() => Promise.resolve())
    useAuthStore.setState({ logout: logoutSpy } as never)

    renderSidebar()
    const user = userEvent.setup()
    const button = screen.getByRole('button', { name: /sign out/i })
    await user.click(button)
    // After first click the accessible name flips; re-query.
    await user.click(screen.getByRole('button', { name: /click again to confirm/i }))

    expect(logoutSpy).toHaveBeenCalledTimes(1)
  })

  it('does not call logout when only the first click happens', async () => {
    // Confirms the click handler short-circuits on the first click — pairs
    // with the second-click test above to lock the two-click invariant.
    const logoutSpy = vi.fn(() => Promise.resolve())
    useAuthStore.setState({ logout: logoutSpy } as never)

    renderSidebar()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /^sign out$/i }))
    expect(logoutSpy).not.toHaveBeenCalled()
  })
})
