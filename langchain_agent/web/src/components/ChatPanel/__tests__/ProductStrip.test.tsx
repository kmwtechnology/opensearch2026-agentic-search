/**
 * Tests for ProductStrip (#144).
 *
 * The matcher is tested through `selectProducts` with an injected image
 * resolver, so these never touch Vite's asset pipeline.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ProductStrip } from '../ProductStrip'
import { selectProducts } from '../selectProducts'
import type { Citation } from '../../../stores/chatStore'

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

describe('selectProducts', () => {
  it('picks the products the answer names, in the order it names them', () => {
    const content =
      'Here are some options:\n' +
      '* **Brother LB7000 Computerized Embroidery and Sewing Machine** — a machine.\n' +
      '* **Singer 3221 Simple Sewing Machine** — another machine.'

    const result = selectProducts(content, citations, allImages)

    expect(result.map((p) => p.asin)).toEqual(['B08PC22TYB', 'B0085SRIC2'])
  })

  it('matches a bold name that is only a prefix of the full catalog title', () => {
    // The LLM bolds a short name; the citation carries colorway and size.
    const content = "**adidas Men's BB6622 Supernova Trail Shoe** is blue."

    const result = selectProducts(content, citations, allImages)

    expect(result).toHaveLength(1)
    expect(result[0].asin).toBe('B07FBKWMBY')
    expect(result[0].title).toContain('Hi-Res Blue')
  })

  it('ignores punctuation and case differences when matching', () => {
    const content = '**ADIDAS MENS BB6622 SUPERNOVA TRAIL SHOE**'

    expect(selectProducts(content, citations, allImages)[0].asin).toBe('B07FBKWMBY')
  })

  it('falls back to citation order when the answer names nothing in bold', () => {
    const result = selectProducts('No products here.', citations, allImages)

    expect(result.map((p) => p.asin)).toEqual(['B07FBKWMBY', 'B0085SRIC2', 'B08PC22TYB'])
  })

  it('omits products that have no bundled image rather than showing a gap', () => {
    const onlySinger = (asin?: string) => (asin === 'B0085SRIC2' ? '/img/singer.jpg' : undefined)
    const content = '**Brother LB7000 Computerized Embroidery and Sewing Machine** and **Singer 3221 Simple Sewing Machine**'

    const result = selectProducts(content, citations, onlySinger)

    expect(result.map((p) => p.asin)).toEqual(['B0085SRIC2'])
  })

  it('returns nothing when no product has an image', () => {
    expect(selectProducts('**Singer 3221 Simple Sewing Machine**', citations, noImages)).toEqual([])
  })

  it('returns nothing when there are no citations', () => {
    expect(selectProducts('**Singer 3221**', undefined, allImages)).toEqual([])
    expect(selectProducts('**Singer 3221**', [], allImages)).toEqual([])
  })

  it('skips citations with no ASIN, since the image is keyed by it', () => {
    const noAsin: Citation[] = [{ label: '[1] Documentation', url: 'https://example.com' }]

    expect(selectProducts('**Documentation**', noAsin, allImages)).toEqual([])
  })

  it('caps the strip at six tiles', () => {
    const many: Citation[] = Array.from({ length: 10 }, (_, i) => ({
      label: `[${i + 1}] Product ${i}`,
      url: `https://example.com/${i}`,
      asin: `ASIN${i}`,
    }))

    expect(selectProducts('nothing bold', many, allImages)).toHaveLength(6)
  })

  it('does not repeat a product the answer names twice', () => {
    const content = '**Singer 3221 Simple Sewing Machine** ... the **Singer 3221 Simple Sewing Machine** again'

    expect(selectProducts(content, citations, allImages)).toHaveLength(1)
  })
})

describe('ProductStrip', () => {
  // These exercise the real bundled image map, so they also assert that
  // `import.meta.glob` keys the assets by bare ASIN as expected.
  it('renders a tile per named product that has a bundled image', () => {
    render(
      <ProductStrip
        content="**Singer 3221 Simple Sewing Machine** is a good pick."
        citations={citations}
      />
    )

    const link = screen.getByRole('link', { name: /Singer 3221/ })
    expect(link).toHaveAttribute('href', 'https://www.amazon.com/s?k=singer')
    expect(screen.getByRole('img', { name: /Singer 3221/ })).toHaveAttribute(
      'src',
      expect.stringContaining('B0085SRIC2')
    )
  })

  it('renders nothing when no citation has a bundled image', () => {
    const unknown: Citation[] = [
      { label: '[1] Imaginary Product', url: 'https://example.com', asin: 'NOTREAL0001' },
    ]

    const { container } = render(<ProductStrip content="**Imaginary Product**" citations={unknown} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing without citations', () => {
    const { container } = render(<ProductStrip content="**Anything**" />)

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId('product-strip')).not.toBeInTheDocument()
  })
})
