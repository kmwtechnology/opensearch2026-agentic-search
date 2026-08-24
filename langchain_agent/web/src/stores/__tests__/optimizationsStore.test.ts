import { describe, it, expect, beforeEach } from 'vitest'
import { useOptimizationsStore, type OptimizationKey, type Optimizations } from '../optimizationsStore'

const ALL_KEYS: OptimizationKey[] = [
  'hybrid', 'fuzzy', 'synonyms', 'phonetic',
  'phrase_boost', 'field_boost', 'typeahead',
  'reranking', 'llm', 'llm_judge',
]

const DEFAULT_OPTIMIZATIONS: Optimizations = {
  hybrid: true, fuzzy: true, synonyms: true, phonetic: true,
  phrase_boost: true, field_boost: true, typeahead: true,
  reranking: true, llm: true, llm_judge: true,
}

beforeEach(() => {
  useOptimizationsStore.setState({ optimizations: { ...DEFAULT_OPTIMIZATIONS } })
})

describe('optimizationsStore', () => {
  describe('initial state', () => {
    it('all default keys are true', () => {
      const { optimizations } = useOptimizationsStore.getState()
      for (const key of ALL_KEYS) {
        expect(optimizations[key]).toBe(true)
      }
    })

    it('has exactly 10 keys', () => {
      const { optimizations } = useOptimizationsStore.getState()
      expect(Object.keys(optimizations)).toHaveLength(10)
    })
  })

  describe('toggle', () => {
    it('flips a single key from true to false', () => {
      const { toggle } = useOptimizationsStore.getState()
      toggle('fuzzy')
      expect(useOptimizationsStore.getState().optimizations.fuzzy).toBe(false)
    })

    it('flips a key back from false to true', () => {
      const { toggle } = useOptimizationsStore.getState()
      toggle('fuzzy')
      toggle('fuzzy')
      expect(useOptimizationsStore.getState().optimizations.fuzzy).toBe(true)
    })

    it('does not affect other keys', () => {
      const { toggle } = useOptimizationsStore.getState()
      toggle('fuzzy')
      const { optimizations } = useOptimizationsStore.getState()
      expect(optimizations.hybrid).toBe(true)
      expect(optimizations.synonyms).toBe(true)
      expect(optimizations.reranking).toBe(true)
    })
  })

  describe('setAll', () => {
    it('setAll(false) disables all keys', () => {
      const { setAll } = useOptimizationsStore.getState()
      setAll(false)
      const { optimizations } = useOptimizationsStore.getState()
      for (const key of ALL_KEYS) {
        expect(optimizations[key]).toBe(false)
      }
    })

    it('setAll(true) enables all keys after disabling', () => {
      const { setAll } = useOptimizationsStore.getState()
      setAll(false)
      setAll(true)
      const { optimizations } = useOptimizationsStore.getState()
      for (const key of ALL_KEYS) {
        expect(optimizations[key]).toBe(true)
      }
    })
  })

  describe('reset', () => {
    it('restores defaults after toggle', () => {
      const { toggle, reset } = useOptimizationsStore.getState()
      toggle('fuzzy')
      toggle('phonetic')
      reset()
      const { optimizations } = useOptimizationsStore.getState()
      expect(optimizations.fuzzy).toBe(true)
      expect(optimizations.phonetic).toBe(true)
    })

    it('restores defaults after setAll(false)', () => {
      const { setAll, reset } = useOptimizationsStore.getState()
      setAll(false)
      reset()
      const { optimizations } = useOptimizationsStore.getState()
      for (const key of ALL_KEYS) {
        expect(optimizations[key]).toBe(true)
      }
    })
  })
})
