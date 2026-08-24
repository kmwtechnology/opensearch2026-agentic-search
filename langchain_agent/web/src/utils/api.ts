/**
 * API utility with same-origin authentication.
 *
 * Two-layer auth model:
 * 1. Same-origin (Origin/Referer/Host) enforced by the backend on every route.
 * 2. Shared-password session cookie (HttpOnly) set by POST /api/auth/login.
 *
 * The cookie rides automatically because every request below carries
 * `credentials: 'include'`. No API key is sent in headers or query params.
 */

// When frontend and API are on the same domain (Cloud Run, localhost),
// use relative URLs (empty string) - browser will use the current origin automatically.
// The browser automatically sends the Origin header, which the backend validates.
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/**
 * Create headers for API requests.
 */
function createHeaders(additionalHeaders?: Record<string, string>): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    ...additionalHeaders,
  }
}

/**
 * Make an API request that includes the session cookie.
 *
 * @param endpoint - API endpoint (e.g., '/api/conversations')
 * @param options - Fetch options (method, body, etc.)
 * @returns Fetch response
 */
export async function apiFetch(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const url = `${API_BASE_URL}${endpoint}`

  const headers = createHeaders(
    options.headers as Record<string, string> | undefined
  )

  return fetch(url, {
    ...options,
    headers,
    // Send the session cookie set by /api/auth/login. Without this, the
    // browser would drop the cookie even on same-origin requests when
    // `credentials` defaults to 'same-origin' isn't relied on (e.g. when
    // VITE_API_URL points at a different port during local dev).
    credentials: 'include',
  })
}

/**
 * GET request with authentication.
 */
export async function apiGet(
  endpoint: string,
  options: Omit<RequestInit, 'method' | 'body'> = {}
): Promise<Response> {
  return apiFetch(endpoint, { ...options, method: 'GET' })
}

/**
 * POST request with authentication.
 */
export async function apiPost(endpoint: string, body?: unknown): Promise<Response> {
  return apiFetch(endpoint, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}

/**
 * DELETE request with authentication.
 */
export async function apiDelete(endpoint: string): Promise<Response> {
  return apiFetch(endpoint, { method: 'DELETE' })
}
