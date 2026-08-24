/**
 * LoginScreen — full-page password gate rendered when the user is not
 * authenticated. A single password input + submit button + a prominent
 * warning that the demo is shared.
 */

import { FormEvent, useState } from 'react'
import { AlertTriangle, Lock } from 'lucide-react'
import { useAuthStore } from '../stores/authStore'

export function LoginScreen() {
  const [password, setPassword] = useState('')
  const isLoggingIn = useAuthStore((s) => s.isLoggingIn)
  const loginError = useAuthStore((s) => s.loginError)
  const login = useAuthStore((s) => s.login)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!password || isLoggingIn) return
    const ok = await login(password)
    if (!ok) {
      setPassword('')
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <div className="rounded-lg bg-gray-800 border border-gray-700 shadow-xl p-6 sm:p-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="rounded-full bg-blue-500/20 p-2">
              <Lock className="w-5 h-5 text-blue-400" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-100">Agentic Hybrid Search</h1>
              <p className="text-xs text-gray-400">Demo access — enter the shared password</p>
            </div>
          </div>

          <div
            role="alert"
            className="mb-6 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 flex gap-2 text-amber-100"
          >
            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden="true" />
            <div className="text-xs leading-relaxed">
              <strong className="font-semibold">Shared demo:</strong> conversations are visible to
              everyone with this password. <strong>Do not enter personal or sensitive
              information.</strong>
            </div>
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="login-password"
                className="block text-xs font-medium text-gray-300 mb-1.5"
              >
                Password
              </label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoggingIn}
                className="w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:opacity-50"
                placeholder="Enter password"
              />
            </div>

            {loginError && (
              <div
                role="alert"
                className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200"
              >
                {loginError}
              </div>
            )}

            <button
              type="submit"
              disabled={!password || isLoggingIn}
              className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed"
            >
              {isLoggingIn ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
