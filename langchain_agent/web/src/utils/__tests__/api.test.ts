/**
 * Tests for api.ts — apiFetch, apiGet, apiPost, apiDelete
 */

import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import { apiFetch, apiGet, apiPost, apiDelete } from '../api'

const mockFetch = vi.fn()

beforeEach(() => {
  mockFetch.mockClear()
  vi.stubGlobal('fetch', mockFetch)
  mockFetch.mockResolvedValue({ ok: true, status: 200 } as Response)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('calls fetch with the correct URL', async () => {
    await apiFetch('/api/test')
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/test',
      expect.objectContaining({})
    )
  })

  it('includes credentials: include', async () => {
    await apiFetch('/api/test')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.credentials).toBe('include')
  })

  it('sets Content-Type to application/json', async () => {
    await apiFetch('/api/test')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.headers['Content-Type']).toBe('application/json')
  })

  it('merges additional headers', async () => {
    await apiFetch('/api/test', {
      headers: { 'X-Custom': 'value' },
    })
    const [, options] = mockFetch.mock.calls[0]
    expect(options.headers['Content-Type']).toBe('application/json')
    expect(options.headers['X-Custom']).toBe('value')
  })

  it('forwards other fetch options (method, body)', async () => {
    await apiFetch('/api/test', { method: 'POST', body: '{"key":"val"}' })
    const [, options] = mockFetch.mock.calls[0]
    expect(options.method).toBe('POST')
    expect(options.body).toBe('{"key":"val"}')
  })

  it('prepends API_BASE_URL to the path', async () => {
    await apiFetch('/api/endpoint')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/api/endpoint')
  })

  it('returns the fetch response', async () => {
    const fakeResp = { ok: true, status: 200, json: async () => ({}) } as Response
    mockFetch.mockResolvedValueOnce(fakeResp)
    const result = await apiFetch('/api/test')
    expect(result).toBe(fakeResp)
  })
})

describe('apiGet', () => {
  it('uses GET method', async () => {
    await apiGet('/api/items')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.method).toBe('GET')
  })

  it('passes the correct URL', async () => {
    await apiGet('/api/items')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toBe('/api/items')
  })

  it('does not send a request body', async () => {
    await apiGet('/api/items')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBeUndefined()
  })
})

describe('apiPost', () => {
  it('uses POST method', async () => {
    await apiPost('/api/auth/login', { password: 'secret' })
    const [, options] = mockFetch.mock.calls[0]
    expect(options.method).toBe('POST')
  })

  it('JSON-serialises the body', async () => {
    await apiPost('/api/auth/login', { password: 'abc' })
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBe(JSON.stringify({ password: 'abc' }))
  })

  it('sends no body when body argument is omitted', async () => {
    await apiPost('/api/auth/logout')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBeUndefined()
  })

  it('sends no body when body is undefined', async () => {
    await apiPost('/api/auth/logout', undefined)
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBeUndefined()
  })
})

describe('apiDelete', () => {
  it('uses DELETE method', async () => {
    await apiDelete('/api/conversations/thread-1')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.method).toBe('DELETE')
  })

  it('passes the correct URL', async () => {
    await apiDelete('/api/conversations/thread-1')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toBe('/api/conversations/thread-1')
  })

  it('does not send a request body', async () => {
    await apiDelete('/api/conversations/thread-1')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBeUndefined()
  })
})
