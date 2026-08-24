/**
 * Tests for authStore — checkAuth status probing, login success/failure
 * paths (401/429/503/network), logout, and the WS-driven
 * markUnauthenticated escape hatch.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../authStore'

vi.mock('../../utils/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

import { apiGet, apiPost } from '../../utils/api'

const mockApiGet = apiGet as unknown as ReturnType<typeof vi.fn>
const mockApiPost = apiPost as unknown as ReturnType<typeof vi.fn>

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

const INITIAL_STATE = {
  isAuthenticated: false,
  isChecking: true,
  isLoggingIn: false,
  loginError: null,
}

beforeEach(() => {
  mockApiGet.mockReset()
  mockApiPost.mockReset()
  useAuthStore.setState(INITIAL_STATE)
})

describe('authStore.checkAuth', () => {
  it('flips isAuthenticated based on /status response', async () => {
    mockApiGet.mockResolvedValueOnce(jsonResponse({ authenticated: true }))
    await useAuthStore.getState().checkAuth()
    const s = useAuthStore.getState()
    expect(s.isAuthenticated).toBe(true)
    expect(s.isChecking).toBe(false)
  })

  it('sets isAuthenticated=false when /status reports false', async () => {
    mockApiGet.mockResolvedValueOnce(jsonResponse({ authenticated: false }))
    await useAuthStore.getState().checkAuth()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('treats non-200 /status as unauthenticated', async () => {
    mockApiGet.mockResolvedValueOnce(jsonResponse({}, 500))
    await useAuthStore.getState().checkAuth()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('treats network errors as unauthenticated and clears isChecking', async () => {
    mockApiGet.mockRejectedValueOnce(new Error('network down'))
    await useAuthStore.getState().checkAuth()
    const s = useAuthStore.getState()
    expect(s.isAuthenticated).toBe(false)
    expect(s.isChecking).toBe(false)
  })
})

describe('authStore.login', () => {
  it('returns true and sets isAuthenticated on 200', async () => {
    mockApiPost.mockResolvedValueOnce(jsonResponse({ authenticated: true }))
    const ok = await useAuthStore.getState().login('right')
    expect(ok).toBe(true)
    const s = useAuthStore.getState()
    expect(s.isAuthenticated).toBe(true)
    expect(s.loginError).toBeNull()
    expect(s.isLoggingIn).toBe(false)
  })

  it('reports "Wrong password." on 401', async () => {
    mockApiPost.mockResolvedValueOnce(jsonResponse({}, 401))
    const ok = await useAuthStore.getState().login('wrong')
    expect(ok).toBe(false)
    expect(useAuthStore.getState().loginError).toBe('Wrong password.')
  })

  it('reports rate-limit message on 429', async () => {
    mockApiPost.mockResolvedValueOnce(jsonResponse({}, 429))
    await useAuthStore.getState().login('try-fast')
    expect(useAuthStore.getState().loginError).toMatch(/too many attempts/i)
  })

  it('reports misconfiguration on 503', async () => {
    mockApiPost.mockResolvedValueOnce(jsonResponse({}, 503))
    await useAuthStore.getState().login('any')
    expect(useAuthStore.getState().loginError).toMatch(/not configured/i)
  })

  it('reports a generic message on other non-2xx codes', async () => {
    mockApiPost.mockResolvedValueOnce(jsonResponse({}, 502))
    await useAuthStore.getState().login('any')
    expect(useAuthStore.getState().loginError).toMatch(/login failed \(502\)/i)
  })

  it('reports network error on fetch rejection', async () => {
    mockApiPost.mockRejectedValueOnce(new Error('connect ECONNREFUSED'))
    const ok = await useAuthStore.getState().login('any')
    expect(ok).toBe(false)
    expect(useAuthStore.getState().loginError).toMatch(/network error/i)
  })
})

describe('authStore.logout', () => {
  it('clears isAuthenticated and posts to /logout', async () => {
    useAuthStore.setState({ isAuthenticated: true, isChecking: false })
    mockApiPost.mockResolvedValueOnce(jsonResponse({ authenticated: false }))

    await useAuthStore.getState().logout()

    expect(mockApiPost).toHaveBeenCalledWith('/api/auth/logout')
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().loginError).toBeNull()
  })

  it('still clears isAuthenticated even if the network call fails', async () => {
    // Defensive: a flaky network shouldn't trap the user inside the app
    // with no escape from a session they thought was cleared.
    useAuthStore.setState({ isAuthenticated: true, isChecking: false })
    mockApiPost.mockRejectedValueOnce(new Error('network'))

    await useAuthStore.getState().logout()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })
})

describe('authStore.markUnauthenticated', () => {
  it('flips isAuthenticated to false without a network call', () => {
    useAuthStore.setState({ isAuthenticated: true })
    useAuthStore.getState().markUnauthenticated()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(mockApiPost).not.toHaveBeenCalled()
  })
})
