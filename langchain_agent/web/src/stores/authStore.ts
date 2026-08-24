/**
 * Zustand store for the shared-password login gate.
 *
 * The browser holds the session as an HttpOnly cookie set by the backend on
 * /api/auth/login; this store only mirrors the boolean "is the cookie still
 * valid?" state so React can decide whether to render the login screen or
 * the chat UI. No password material ever touches the store.
 */

import { create } from 'zustand'
import { apiGet, apiPost } from '../utils/api'

interface AuthState {
  // True after a successful /api/auth/status check or login.
  isAuthenticated: boolean
  // True only during the initial /api/auth/status probe on mount.
  isChecking: boolean
  // True while a login request is in flight.
  isLoggingIn: boolean
  // Last login error message, cleared on the next attempt.
  loginError: string | null

  checkAuth: () => Promise<void>
  login: (password: string) => Promise<boolean>
  logout: () => Promise<void>
  // Called by the WebSocket hook on a 4401 close — flips state without a
  // network round-trip so the UI routes back to the login screen instantly.
  markUnauthenticated: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  isChecking: true,
  isLoggingIn: false,
  loginError: null,

  checkAuth: async () => {
    set({ isChecking: true })
    try {
      const response = await apiGet('/api/auth/status')
      if (!response.ok) {
        set({ isAuthenticated: false, isChecking: false })
        return
      }
      const data = await response.json()
      set({ isAuthenticated: !!data.authenticated, isChecking: false })
    } catch (error) {
      console.error('Auth status check failed:', error)
      set({ isAuthenticated: false, isChecking: false })
    }
  },

  login: async (password) => {
    set({ isLoggingIn: true, loginError: null })
    try {
      const response = await apiPost('/api/auth/login', { password })
      if (response.ok) {
        set({ isAuthenticated: true, isLoggingIn: false, loginError: null })
        return true
      }
      if (response.status === 401) {
        set({ isAuthenticated: false, isLoggingIn: false, loginError: 'Wrong password.' })
      } else if (response.status === 429) {
        set({
          isAuthenticated: false,
          isLoggingIn: false,
          loginError: 'Too many attempts. Wait a minute and try again.',
        })
      } else if (response.status === 503) {
        set({
          isAuthenticated: false,
          isLoggingIn: false,
          loginError: 'Login is not configured on this server.',
        })
      } else {
        set({
          isAuthenticated: false,
          isLoggingIn: false,
          loginError: `Login failed (${response.status}).`,
        })
      }
      return false
    } catch (error) {
      console.error('Login request failed:', error)
      set({
        isAuthenticated: false,
        isLoggingIn: false,
        loginError: 'Network error. Check your connection and try again.',
      })
      return false
    }
  },

  logout: async () => {
    try {
      await apiPost('/api/auth/logout')
    } catch (error) {
      console.error('Logout request failed:', error)
    } finally {
      set({ isAuthenticated: false, loginError: null })
    }
  },

  markUnauthenticated: () => set({ isAuthenticated: false, loginError: null }),
}))
