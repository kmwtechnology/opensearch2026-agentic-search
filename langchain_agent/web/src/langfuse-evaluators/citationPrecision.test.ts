// Exercises citationPrecision.ts's exact literal bytes -- the same source
// text submitted to Langfuse as an Evaluator's source_code -- rather than a
// parallel exported copy that could drift from what's actually deployed.
import ts from 'typescript'
import { describe, expect, it } from 'vitest'
import evaluatorSource from './citationPrecision.ts?raw'

type Evaluate = (context: unknown) => { scores: Array<Record<string, unknown>> }

function loadEvaluate(): Evaluate {
  // Langfuse's sandbox transpiles + runs this as a standalone function body
  // (no import/export) -- reproduce that by stripping TS types with the
  // TypeScript compiler API (new Function() only accepts plain JS) and
  // executing the result the same way a script-body sandbox would.
  const { outputText } = ts.transpileModule(evaluatorSource, {
    compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2020 },
  })
  return new Function(`${outputText}\nreturn evaluate;`)()
}

describe('citationPrecision.ts (Langfuse Code Evaluator source)', () => {
  it('is a standalone script with no import/export statements', () => {
    expect(evaluatorSource).not.toMatch(/^\s*import /m)
    expect(evaluatorSource).not.toMatch(/^\s*export /m)
  })

  it('defines a function named evaluate', () => {
    expect(evaluatorSource).toMatch(/function evaluate\(/)
  })

  const ctx = (output: Record<string, unknown>, itemExpectedOutput: unknown) => ({
    observation: { input: {}, output, metadata: {}, toolCalls: [] },
    experiment: itemExpectedOutput ? { itemExpectedOutput, itemMetadata: {} } : undefined,
  })

  it('scores full precision when all cited products are relevant', () => {
    const evaluate = loadEvaluate()
    const output = {
      citations: [{ label: '[1] Boots' }],
      retrieved_documents: [{ metadata: { product_id: 'p1' } }],
    }
    const result = evaluate(ctx(output, { judgments: { p1: 4.0 } }))
    expect(result.scores).toHaveLength(1)
    expect(result.scores[0].name).toBe('eval_citation_precision_ts')
    expect(result.scores[0].value).toBe(1)
  })

  it('scores mixed precision correctly', () => {
    const evaluate = loadEvaluate()
    const output = {
      citations: [{ label: '[1,2] Boots' }],
      retrieved_documents: [
        { metadata: { product_id: 'p1' } },
        { metadata: { product_id: 'p2' } },
      ],
    }
    const result = evaluate(ctx(output, { judgments: { p1: 4.0, p2: 0.0 } }))
    expect(result.scores[0].value).toBe(0.5)
  })

  it('returns the no-data sentinel without ground truth', () => {
    const evaluate = loadEvaluate()
    const output = {
      citations: [{ label: '[1] Boots' }],
      retrieved_documents: [{ metadata: { product_id: 'p1' } }],
    }
    const result = evaluate(ctx(output, undefined))
    expect(result.scores[0].value).toBe(-1)
  })

  it('returns the no-data sentinel without citations', () => {
    const evaluate = loadEvaluate()
    const output = { citations: [], retrieved_documents: [] }
    const result = evaluate(ctx(output, { judgments: { p1: 4.0 } }))
    expect(result.scores[0].value).toBe(-1)
  })

  it('ignores out-of-range citation indices', () => {
    const evaluate = loadEvaluate()
    const output = {
      citations: [{ label: '[1,5] Boots' }],
      retrieved_documents: [{ metadata: { product_id: 'p1' } }],
    }
    const result = evaluate(ctx(output, { judgments: { p1: 4.0 } }))
    expect(result.scores[0].value).toBe(1)
  })
})
