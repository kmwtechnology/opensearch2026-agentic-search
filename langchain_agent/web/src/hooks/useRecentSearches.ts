/**
 * useRecentSearches - localStorage-backed recent query memory.
 * Shown in the typeahead when the input is empty.
 */

import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'agentic-search-recent'
const MAX_ENTRIES = 8

function readFromStorage(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is string => typeof v === 'string').slice(0, MAX_ENTRIES)
  } catch {
    return []
  }
}

function writeToStorage(values: string[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(values))
  } catch {
    // Quota errors / private mode — silently drop; feature is non-critical.
  }
}

export function useRecentSearches() {
  const [recent, setRecent] = useState<string[]>(() => readFromStorage())

  useEffect(() => {
    writeToStorage(recent)
  }, [recent])

  const add = useCallback((query: string) => {
    const trimmed = query.trim()
    if (!trimmed) return
    setRecent((prev) => {
      const withoutDupe = prev.filter((q) => q.toLowerCase() !== trimmed.toLowerCase())
      return [trimmed, ...withoutDupe].slice(0, MAX_ENTRIES)
    })
  }, [])

  const clear = useCallback(() => {
    setRecent([])
  }, [])

  return { recent, add, clear }
}
