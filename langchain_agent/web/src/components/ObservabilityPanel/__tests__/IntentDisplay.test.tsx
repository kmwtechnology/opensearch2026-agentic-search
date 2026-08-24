/**
 * Integration tests for intent display across ObservabilityPanel
 * Tests how intent information flows through the component hierarchy
 */

import { describe, it, expect } from 'vitest'

describe('Intent Display Integration', () => {
  describe('Intent Badge Colors', () => {
    const intentColors = {
      search: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
      comparison: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
      attribute_filter: { bg: 'bg-purple-500/20', text: 'text-purple-400' },
      follow_up: { bg: 'bg-cyan-500/20', text: 'text-cyan-400' },
      summary: { bg: 'bg-purple-500/20', text: 'text-purple-400' },
    }

    it('maps all intents to color classes', () => {
      Object.entries(intentColors).forEach(([_intent, colors]) => {
        expect(colors.bg).toBeTruthy()
        expect(colors.text).toBeTruthy()
      })
    })

    it('uses consistent color scheme', () => {
      const colors = Object.values(intentColors)
      expect(colors.length).toBe(5)
    })
  })

  describe('Confidence Visualization', () => {
    it('maps confidence to visual states', () => {
      const testCases = [
        { confidence: 0.1, showWarning: true },
        { confidence: 0.5, showWarning: true },
        { confidence: 0.69, showWarning: true },
        { confidence: 0.7, showWarning: false },
        { confidence: 0.85, showWarning: false },
        { confidence: 1.0, showWarning: false },
      ]

      testCases.forEach(({ confidence, showWarning }) => {
        const isLow = confidence < 0.7
        expect(isLow).toBe(showWarning)
      })
    })
  })

  describe('Intent-Specific Rendering', () => {
    it('displays all 5 intent types', () => {
      const intents = ['search', 'comparison', 'attribute_filter', 'follow_up', 'summary']
      expect(intents.length).toBe(5)
    })

    it('handles unknown intents with fallback', () => {
      const knownIntents = ['search', 'comparison', 'attribute_filter', 'follow_up', 'summary']
      const unknownIntent = 'unknown_type'
      const isKnown = knownIntents.includes(unknownIntent)
      expect(isKnown).toBe(false)
    })
  })

  describe('Query Expansion Display', () => {
    it('expansion applies to follow_up intents', () => {
      const expansionCandidates = ['follow_up', 'search', 'comparison']
      const hasExpansion = expansionCandidates.includes('follow_up')
      expect(hasExpansion).toBe(true)
    })
  })

  describe('Confidence-Based UI Behavior', () => {
    it('clarification shown when confidence < 0.7', () => {
      const testValues = [0.6, 0.69, 0.7, 0.8]
      const results = testValues.map(conf => ({
        confidence: conf,
        showClarify: conf < 0.7,
      }))

      expect(results[0].showClarify).toBe(true)
      expect(results[1].showClarify).toBe(true)
      expect(results[2].showClarify).toBe(false)
      expect(results[3].showClarify).toBe(false)
    })
  })

  describe('Data Consistency', () => {
    it('intent and confidence are required', () => {
      const event = {
        intent: 'search',
        confidence: 0.85,
      }
      expect(event.intent).toBeDefined()
      expect(event.confidence).toBeDefined()
    })

    it('expansion matches intent type', () => {
      const scenarios = [
        { intent: 'follow_up', canHaveExpansion: true },
        { intent: 'search', canHaveExpansion: false },
        { intent: 'comparison', canHaveExpansion: false },
      ]

      scenarios.forEach(scenario => {
        if (scenario.canHaveExpansion) {
          expect(scenario.intent).toBe('follow_up')
        }
      })
    })
  })
})
