/**
 * API helper. There is no login:
 *
 * Same-origin (Origin/Referer/Host) is enforced by the backend on every
 * route -- no login, no session cookie, no API key sent in headers or
 * query params.
 */

// When frontend and API are on the same domain (same-origin deploy, localhost),
// use relative URLs (empty string) - browser will use the current origin automatically.
// The browser automatically sends the Origin header, which the backend validates.
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/**
 * Make an API request; the browser's Origin header is the only credential.
 *
 * @param endpoint - API endpoint (e.g., '/api/admin/health')
 * @param options - Fetch options (method, body, etc.)
 * @returns Fetch response
 */
export async function apiFetch(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const url = `${API_BASE_URL}${endpoint}`

  return fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers as Record<string, string>) },
    credentials: 'include',
  })
}

/** POST a JSON body. */
export async function apiPost(endpoint: string, body?: unknown): Promise<Response> {
  return apiFetch(endpoint, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}
