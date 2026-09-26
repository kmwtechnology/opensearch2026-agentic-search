/**
 * Tests for the product cards an answer's bullet list turns into (#144).
 *
 * Each citation carries its product's own image URL (SQID, #147), so a card
 * exists exactly when the cited product has a photo.
 */

import { describe, it, expect } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Message } from '../Message'
import { indexProducts } from '../productIndex'
import type { Citation, ChatMessage } from '../../../stores/chatStore'

const citations: Citation[] = [
  {
    label: "[1] adidas Men's BB6622 Supernova Trail Shoe, Hi-Res Blue/Hi-Res Orange/Black - 10 M",
    url: 'https://www.amazon.com/s?k=adidas',
    asin: 'B07FBKWMBY',
    image_url: 'https://m.media-amazon.com/images/I/adidas.jpg',
  },
  {
    label: '[2] Singer 3221 Simple Sewing Machine with Automatic Needle Threader, 21 Stitches',
    url: 'https://www.amazon.com/s?k=singer',
    asin: 'B0085SRIC2',
    image_url: 'https://m.media-amazon.com/images/I/singer.jpg',
  },
  {
    label: '[3] Brother LB7000 Computerized Embroidery and Sewing Machine',
    url: 'https://www.amazon.com/s?k=brother',
    asin: 'B08PC22TYB',
    image_url: 'https://m.media-amazon.com/images/I/brother.jpg',
  },
]

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
    const product = indexProducts(citations)("adidas Men's BB6622 Supernova Trail Shoe")

    expect(product?.asin).toBe('B07FBKWMBY')
    expect(product?.title).toContain('Hi-Res Blue')
    expect(product?.url).toBe('https://www.amazon.com/s?k=adidas')
  })

  it('matches when the bold name is longer than the catalog title', () => {
    const longer = indexProducts(citations)(
      'Brother LB7000 Computerized Embroidery and Sewing Machine with 103 Stitches'
    )

    expect(longer?.asin).toBe('B08PC22TYB')
  })

  it('ignores punctuation and case differences when matching', () => {
    const product = indexProducts(citations)('ADIDAS MENS BB6622 SUPERNOVA TRAIL SHOE')

    expect(product?.asin).toBe('B07FBKWMBY')
  })

  it('does not match an unrelated product name', () => {
    expect(indexProducts(citations)('Hand-cranked butter churn')).toBeUndefined()
  })

  it('skips products with no image URL rather than promising a photo', () => {
    const find = indexProducts(
      citations.map((c) => (c.asin === 'B0085SRIC2' ? c : { ...c, image_url: undefined }))
    )

    expect(find('Singer 3221 Simple Sewing Machine')?.asin).toBe('B0085SRIC2')
    expect(find('Brother LB7000 Computerized Embroidery and Sewing Machine')).toBeUndefined()
  })

  it('uses the citation image URL as the card photo', () => {
    expect(indexProducts(citations)('Singer 3221')?.image).toBe(
      'https://m.media-amazon.com/images/I/singer.jpg'
    )
  })

  it('returns nothing when there are no citations or no images at all', () => {
    const noImages = citations.map((c) => ({ ...c, image_url: undefined }))
    expect(indexProducts(undefined)('Singer 3221')).toBeUndefined()
    expect(indexProducts([])('Singer 3221')).toBeUndefined()
    expect(indexProducts(noImages)('Singer 3221')).toBeUndefined()
  })

  it('ignores an empty name', () => {
    expect(indexProducts(citations)('')).toBeUndefined()
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
      'https://m.media-amazon.com/images/I/singer.jpg'
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

  it('falls back to the plain bullet when the image URL is dead', () => {
    render(
      <Message message={answer('*   **Singer 3221 Simple Sewing Machine** — a good starter.')} />
    )

    fireEvent.error(screen.getByRole('img'))

    expect(screen.queryByTestId('product-card')).not.toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText(/a good starter/)).toBeInTheDocument()
  })

  it('renders a plain list when no product has an image', () => {
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
