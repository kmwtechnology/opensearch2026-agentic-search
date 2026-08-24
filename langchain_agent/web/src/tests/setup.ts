import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom in some environments exposes a Storage stub that lacks getItem/setItem.
// Replace it with a minimal in-memory polyfill so useRecentSearches and any
// other localStorage consumers work in tests.
class MemoryStorage implements Storage {
  private store = new Map<string, string>()
  get length(): number {
    return this.store.size
  }
  clear(): void {
    this.store.clear()
  }
  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
  removeItem(key: string): void {
    this.store.delete(key)
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }
}

Object.defineProperty(window, 'localStorage', {
  value: new MemoryStorage(),
  configurable: true,
  writable: true,
})
Object.defineProperty(window, 'sessionStorage', {
  value: new MemoryStorage(),
  configurable: true,
  writable: true,
})

afterEach(() => {
  cleanup()
  ;(window.localStorage as MemoryStorage).clear()
  ;(window.sessionStorage as MemoryStorage).clear()
})
