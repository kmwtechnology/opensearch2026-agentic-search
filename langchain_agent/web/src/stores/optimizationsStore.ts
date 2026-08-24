/**
 * Zustand store for user-toggleable search optimizations.
 *
 * State persists to localStorage so toggles survive page reloads.
 * Each flag maps to a query-construction switch in vector_store.py / suggest.py.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type OptimizationKey =
  | 'hybrid'
  | 'fuzzy'
  | 'synonyms'
  | 'phonetic'
  | 'phrase_boost'
  | 'field_boost'
  | 'typeahead'
  | 'reranking'
  | 'llm'
  | 'llm_judge'

export type Optimizations = Record<OptimizationKey, boolean>

const DEFAULT_OPTIMIZATIONS: Optimizations = {
  hybrid: true,
  fuzzy: true,
  synonyms: true,
  phonetic: true,
  phrase_boost: true,
  field_boost: true,
  typeahead: true,
  reranking: true,
  llm: true,
  llm_judge: true,  // on by default — extra ~1-2s per query, but the
                    // hallucination guardrail is worth it for demo
}

interface OptimizationsState {
  optimizations: Optimizations
  toggle: (key: OptimizationKey) => void
  setAll: (value: boolean) => void
  reset: () => void
}

export const useOptimizationsStore = create<OptimizationsState>()(
  persist(
    (set) => ({
      optimizations: { ...DEFAULT_OPTIMIZATIONS },
      toggle: (key) =>
        set((state) => ({
          optimizations: {
            ...state.optimizations,
            [key]: !state.optimizations[key],
          },
        })),
      setAll: (value) =>
        set({
          optimizations: Object.keys(DEFAULT_OPTIMIZATIONS).reduce(
            (acc, k) => ({ ...acc, [k]: value }),
            {} as Optimizations
          ),
        }),
      reset: () => set({ optimizations: { ...DEFAULT_OPTIMIZATIONS } }),
    }),
    {
      name: 'search-optimizations',
      // Bump on additive flag changes:
      //   v2 added `reranking`; v3 added `llm`; v4 added `llm_judge`;
      //   v5 flipped llm_judge default to true.
      version: 5,
      // Merge persisted state with current defaults so newly added flags
      // appear enabled instead of `undefined`, and unknown keys from older
      // schemas are dropped (we only keep keys that exist in the defaults).
      merge: (persisted, current) => {
        const persistedOpts =
          (persisted as { optimizations?: Partial<Optimizations> } | undefined)?.optimizations ?? {}
        const known = Object.keys(current.optimizations) as OptimizationKey[]
        const cleanedPersisted: Partial<Optimizations> = {}
        for (const k of known) {
          if (k in persistedOpts && typeof persistedOpts[k] === 'boolean') {
            cleanedPersisted[k] = persistedOpts[k]
          }
        }
        return {
          ...current,
          ...(persisted as Partial<OptimizationsState>),
          optimizations: { ...current.optimizations, ...cleanedPersisted },
        }
      },
    }
  )
)
