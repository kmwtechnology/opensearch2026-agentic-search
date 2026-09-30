/**
 * Tests for api.ts — apiFetch, apiPost
 */

import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import { apiFetch, apiPost } from '../api'

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

  it('returns the fetch response', async () => {
    const fakeResp = { ok: true, status: 200, json: async () => ({}) } as Response
    mockFetch.mockResolvedValueOnce(fakeResp)
    const result = await apiFetch('/api/test')
    expect(result).toBe(fakeResp)
  })
})

describe('apiPost', () => {
  it('uses POST method', async () => {
    await apiPost('/api/admin/demo-reset', { attribute_type: 'color' })
    const [, options] = mockFetch.mock.calls[0]
    expect(options.method).toBe('POST')
  })

  it('JSON-serialises the body', async () => {
    await apiPost('/api/admin/demo-reset', { attribute_type: 'color' })
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBe(JSON.stringify({ attribute_type: 'color' }))
  })

  it('sends no body when body argument is omitted', async () => {
    await apiPost('/api/admin/demo-reset')
    const [, options] = mockFetch.mock.calls[0]
    expect(options.body).toBeUndefined()
  })
})
