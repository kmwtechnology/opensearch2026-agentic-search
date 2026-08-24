/**
 * Tests for useRecentSearches — localStorage-backed recent query list.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useRecentSearches } from '../useRecentSearches'

const STORAGE_KEY = 'agentic-search-recent'

beforeEach(() => {
  window.localStorage.clear()
})

describe('useRecentSearches', () => {
  describe('initial state', () => {
    it('returns an empty array when localStorage is empty', () => {
      const { result } = renderHook(() => useRecentSearches())
      expect(result.current.recent).toEqual([])
    })

    it('hydrates from existing localStorage data', () => {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(['wireless headphones', 'sony tv'])
      )
      const { result } = renderHook(() => useRecentSearches())
      expect(result.current.recent).toEqual(['wireless headphones', 'sony tv'])
    })

    it('ignores non-array localStorage values', () => {
      window.localStorage.setItem(STORAGE_KEY, '"not-an-array"')
      const { result } = renderHook(() => useRecentSearches())
      expect(result.current.recent).toEqual([])
    })

    it('ignores invalid JSON in localStorage', () => {
      window.localStorage.setItem(STORAGE_KEY, '{bad json}')
      const { result } = renderHook(() => useRecentSearches())
      expect(result.current.recent).toEqual([])
    })

    it('filters out non-string entries from localStorage', () => {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(['valid', 42, null, 'also-valid']))
      const { result } = renderHook(() => useRecentSearches())
      expect(result.current.recent).toEqual(['valid', 'also-valid'])
    })

    it('caps initial data at 8 entries', () => {
      const tooMany = Array.from({ length: 12 }, (_, i) => `query-${i}`)
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tooMany))
      const { result } = renderHook(() => useRecentSearches())
      expect(result.current.recent).toHaveLength(8)
    })
  })

  describe('add', () => {
    it('prepends a new query', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => { result.current.add('wireless headphones') })
      expect(result.current.recent[0]).toBe('wireless headphones')
    })

    it('adds multiple queries in reverse chronological order', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => {
        result.current.add('first')
        result.current.add('second')
      })
      expect(result.current.recent[0]).toBe('second')
      expect(result.current.recent[1]).toBe('first')
    })

    it('deduplicates case-insensitively, moving to front', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => {
        result.current.add('Sony headphones')
        result.current.add('SONY HEADPHONES')
      })
      expect(result.current.recent).toHaveLength(1)
      expect(result.current.recent[0]).toBe('SONY HEADPHONES')
    })

    it('trims whitespace before storing', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => { result.current.add('  trimmed  ') })
      expect(result.current.recent[0]).toBe('trimmed')
    })

    it('ignores empty/whitespace-only strings', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => {
        result.current.add('')
        result.current.add('   ')
      })
      expect(result.current.recent).toHaveLength(0)
    })

    it('caps the list at 8 entries', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => {
        for (let i = 0; i < 10; i++) {
          result.current.add(`query-${i}`)
        }
      })
      expect(result.current.recent).toHaveLength(8)
    })

    it('persists to localStorage after add', () => {
      const { result } = renderHook(() => useRecentSearches())
      act(() => { result.current.add('persisted query') })
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toContain('persisted query')
    })
  })

  describe('clear', () => {
    it('empties the recent array', () => {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(['a', 'b']))
      const { result } = renderHook(() => useRecentSearches())
      act(() => { result.current.clear() })
      expect(result.current.recent).toHaveLength(0)
    })

    it('clears localStorage', () => {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(['a']))
      const { result } = renderHook(() => useRecentSearches())
      act(() => { result.current.clear() })
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toHaveLength(0)
    })
  })
})
