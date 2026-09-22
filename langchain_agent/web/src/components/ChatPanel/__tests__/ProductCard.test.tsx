/**
 * Tests for the product cards an answer's bullet list turns into (#144).
 *
 * `indexProducts` is tested with an injected image resolver, so those cases
 * never touch Vite's asset pipeline. The `Message` cases deliberately do —
 * they use real bundled ASINs, which also asserts that `import.meta.glob`
 * keys the assets by bare ASIN under vitest.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Message } from '../Message'
import { indexProducts } from '../productIndex'
import type { Citation, ChatMessage } from '../../../stores/chatStore'

const citations: Citation[] = [
  {
    label: "[1] adidas Men's BB6622 Supernova Trail Shoe, Hi-Res Blue/Hi-Res Orange/Black - 10 M",
    url: 'https://www.amazon.com/s?k=adidas',
    asin: 'B07FBKWMBY',
  },
  {
    label: '[2] Singer 3221 Simple Sewing Machine with Automatic Needle Threader, 21 Stitches',
    url: 'https://www.amazon.com/s?k=singer',
    asin: 'B0085SRIC2',
  },
  {
    label: '[3] Brother LB7000 Computerized Embroidery and Sewing Machine',
    url: 'https://www.amazon.com/s?k=brother',
    asin: 'B08PC22TYB',
  },
]

const allImages = (asin?: string) => (asin ? `/img/${asin}.jpg` : undefined)
const noImages = () => undefined

function answer(content: string, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    role: 'assistant',
    content,
    timestamp: new Date('2026-01-01'),
    citations,
    ...overrides,
  }
}

describe('indexProducts', () => {
  it('matches a bold name that is only a prefix of the full catalog title', () => {
    // The LLM bolds a short name; the citation carries colorway and size.
    const product = indexProducts(citations, allImages)("adidas Men's BB6622 Supernova Trail Shoe")

    expect(product?.asin).toBe('B07FBKWMBY')
    expect(product?.title).toContain('Hi-Res Blue')
    expect(product?.url).toBe('https://www.amazon.com/s?k=adidas')
  })

  it('matches when the bold name is longer than the catalog title', () => {
    const longer = indexProducts(citations, allImages)(
      'Brother LB7000 Computerized Embroidery and Sewing Machine with 103 Stitches'
    )

    expect(longer?.asin).toBe('B08PC22TYB')
  })

  it('ignores punctuation and case differences when matching', () => {
    const product = indexProducts(citations, allImages)('ADIDAS MENS BB6622 SUPERNOVA TRAIL SHOE')

    expect(product?.asin).toBe('B07FBKWMBY')
  })

  it('does not match an unrelated product name', () => {
    expect(indexProducts(citations, allImages)('Hand-cranked butter churn')).toBeUndefined()
  })

  it('skips products with no bundled image rather than promising a photo', () => {
    const onlySinger = (asin?: string) => (asin === 'B0085SRIC2' ? '/img/singer.jpg' : undefined)
    const find = indexProducts(citations, onlySinger)

    expect(find('Singer 3221 Simple Sewing Machine')?.asin).toBe('B0085SRIC2')
    expect(find('Brother LB7000 Computerized Embroidery and Sewing Machine')).toBeUndefined()
  })

  it('skips citations with no ASIN, since the image is keyed by it', () => {
    const noAsin: Citation[] = [{ label: '[1] Documentation', url: 'https://example.com' }]

    expect(indexProducts(noAsin, allImages)('Documentation')).toBeUndefined()
  })

  it('returns nothing when there are no citations or no images at all', () => {
    expect(indexProducts(undefined, allImages)('Singer 3221')).toBeUndefined()
    expect(indexProducts([], allImages)('Singer 3221')).toBeUndefined()
    expect(indexProducts(citations, noImages)('Singer 3221')).toBeUndefined()
  })

  it('ignores an empty name', () => {
    expect(indexProducts(citations, allImages)('')).toBeUndefined()
  })
})

describe('Message — product cards', () => {
  it('turns each named bullet into a card with the photo beside the blurb', () => {
    render(
      <Message
        message={answer(
          'Here are some sewing machines:\n' +
            '*   **Singer 3221 Simple Sewing Machine** — has an automatic needle threader.\n' +
            '*   **Brother LB7000 Computerized Embroidery and Sewing Machine** — offers 103 stitches.'
        )}
      />
    )

    const cards = screen.getAllByTestId('product-card')
    expect(cards).toHaveLength(2)

    // The photo sits inside the list item, not in a strip after the answer.
    const singer = cards[0]
    expect(singer.closest('li')).not.toBeNull()
    expect(singer.querySelector('img')).toHaveAttribute(
      'src',
      expect.stringContaining('B0085SRIC2')
    )
    expect(singer).toHaveTextContent('has an automatic needle threader.')
    expect(singer.querySelector('a')).toHaveAttribute('href', 'https://www.amazon.com/s?k=singer')
  })

  it('drops the em-dash that separated the name from its blurb', () => {
    // The name becomes its own line in the card, so the dash would dangle.
    render(
      <Message message={answer('*   **Singer 3221 Simple Sewing Machine** — a good starter.')} />
    )

    expect(screen.getByTestId('product-card')).toHaveTextContent(
      /Singer 3221 Simple Sewing Machine\s*a good starter\.$/
    )
  })

  it('handles a loose list, where markdown wraps each item in a paragraph', () => {
    render(
      <Message
        message={answer(
          'Options:\n\n' +
            '*   **Singer 3221 Simple Sewing Machine** — a good starter.\n\n' +
            '*   **Brother LB7000 Computerized Embroidery and Sewing Machine** — 103 stitches.\n'
        )}
      />
    )

    expect(screen.getAllByTestId('product-card')).toHaveLength(2)
  })

  it('leaves a bullet the citations do not cover as plain text', () => {
    render(
      <Message
        message={answer(
          '*   **Singer 3221 Simple Sewing Machine** — a good starter.\n' +
            '*   **Hand-cranked butter churn** — not in the catalog.'
        )}
      />
    )

    expect(screen.getAllByTestId('product-card')).toHaveLength(1)
    expect(screen.getByText(/not in the catalog/)).toBeInTheDocument()
  })

  it('renders cards as soon as it has citations, without waiting', () => {
    // Holding the answer back until the citations land is MessageList's job
    // (#144) — by the time a Message renders, the turn is committed. Message
    // itself must not second-guess that, or the cards would never appear.
    render(
      <Message
        message={answer('*   **Singer 3221 Simple Sewing Machine** — a good starter.')}
      />
    )

    expect(screen.getByTestId('product-card')).toBeInTheDocument()
  })

  it('renders a plain list when no product has a bundled image', () => {
    const unknown: Citation[] = [
      { label: '[1] Imaginary Product', url: 'https://example.com', asin: 'NOTREAL0001' },
    ]
    render(
      <Message
        message={answer('*   **Imaginary Product** — does not exist.', { citations: unknown })}
      />
    )

    expect(screen.queryByTestId('product-card')).not.toBeInTheDocument()
    expect(screen.getByText(/does not exist/)).toBeInTheDocument()
  })

  it('renders prose answers untouched, with no cards', () => {
    // Demo 4 turn 1 is the enrichment moment: a sentence and zero citations.
    render(
      <Message
        message={answer('The term "waterproof" has been added and the catalog re-indexed.', {
          citations: [],
        })}
      />
    )

    expect(screen.queryByTestId('product-card')).not.toBeInTheDocument()
    expect(screen.getByText(/catalog re-indexed/)).toBeInTheDocument()
  })
})
