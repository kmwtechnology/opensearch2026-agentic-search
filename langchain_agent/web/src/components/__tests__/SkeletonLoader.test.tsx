/**
 * Tests for SkeletonLoader and SkeletonConversationItem components.
 */

import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { SkeletonLoader, SkeletonConversationItem } from '../SkeletonLoader'

describe('SkeletonLoader', () => {
  it('renders 1 skeleton element by default', () => {
    const { container } = render(<SkeletonLoader />)
    const divs = container.querySelectorAll('div[aria-hidden="true"]')
    expect(divs).toHaveLength(1)
  })

  it('renders the specified count of skeleton elements', () => {
    const { container } = render(<SkeletonLoader count={4} />)
    const divs = container.querySelectorAll('div[aria-hidden="true"]')
    expect(divs).toHaveLength(4)
  })

  it('applies the animate-pulse class', () => {
    const { container } = render(<SkeletonLoader />)
    const div = container.querySelector('div[aria-hidden="true"]')
    expect(div?.className).toContain('animate-pulse')
  })

  it('applies the height class', () => {
    const { container } = render(<SkeletonLoader height="h-8" />)
    const div = container.querySelector('div[aria-hidden="true"]')
    expect(div?.className).toContain('h-8')
  })

  it('applies the width class', () => {
    const { container } = render(<SkeletonLoader width="w-1/2" />)
    const div = container.querySelector('div[aria-hidden="true"]')
    expect(div?.className).toContain('w-1/2')
  })

  it('applies extra className', () => {
    const { container } = render(<SkeletonLoader className="my-custom-class" />)
    const div = container.querySelector('div[aria-hidden="true"]')
    expect(div?.className).toContain('my-custom-class')
  })

  it('all skeleton elements are aria-hidden', () => {
    const { container } = render(<SkeletonLoader count={3} />)
    const divs = container.querySelectorAll('[aria-hidden="true"]')
    expect(divs).toHaveLength(3)
  })
})

describe('SkeletonConversationItem', () => {
  it('renders 3 items by default', () => {
    const { container } = render(<SkeletonConversationItem />)
    const rows = container.querySelectorAll('div[aria-hidden="true"]')
    // Top-level container plus inner rows — at least 3 aria-hidden rows exist
    expect(rows.length).toBeGreaterThanOrEqual(3)
  })

  it('renders the specified count of items', () => {
    const { container } = render(<SkeletonConversationItem count={5} />)
    // Each item row has aria-hidden="true"
    const rows = container.querySelectorAll('.space-y-1 > div[aria-hidden="true"]')
    expect(rows).toHaveLength(5)
  })

  it('renders animated pulse elements', () => {
    const { container } = render(<SkeletonConversationItem count={2} />)
    const animated = container.querySelectorAll('.animate-pulse')
    expect(animated.length).toBeGreaterThan(0)
  })
})
