/**
 * Tests for ConversationItem timestamp formatting.
 *
 * The sidebar previously rendered ambiguous labels ("Thu", "Yesterday") with no
 * time information. These tests lock in the new format that always pairs a day
 * hint with a time ("Thu 7:09 PM", "Yesterday 7:09 PM") and exposes a
 * full-timestamp tooltip.
 */

import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ConversationItem } from '../ConversationItem'
import type { ConversationSummary } from '../../../stores/chatStore'

vi.mock('../../../utils/api', () => ({
  apiDelete: vi.fn(() => Promise.resolve({ ok: true } as Response)),
}))

const FIXED_NOW = new Date('2026-04-30T19:30:00')

const makeConversation = (updatedAt: Date): ConversationSummary => ({
  thread_id: 't1',
  title: 'Test conversation',
  created_at: updatedAt.toISOString(),
  updated_at: updatedAt.toISOString(),
})

const renderItem = (updatedAt: Date) =>
  render(
    <ConversationItem
      conversation={makeConversation(updatedAt)}
      isActive={false}
    />
  )

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(FIXED_NOW)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ConversationItem — timestamp formatting', () => {
  it('renders "Today <time>" for a same-day conversation', () => {
    const sameDay = new Date('2026-04-30T07:09:00')
    renderItem(sameDay)
    // Match "Today 7:09 AM" or "Today 07:09 AM" depending on locale.
    expect(screen.getByText(/^Today \d{1,2}:\d{2}\s?[AP]M$/i)).toBeInTheDocument()
  })

  it('renders "Yesterday <time>" for a one-day-old conversation', () => {
    const yesterday = new Date('2026-04-29T19:09:00')
    renderItem(yesterday)
    expect(screen.getByText(/^Yesterday \d{1,2}:\d{2}\s?[AP]M$/i)).toBeInTheDocument()
  })

  it('renders "<weekday> <time>" for a conversation 2–6 days old', () => {
    // 2026-04-27 is a Monday; locale-short weekday is "Mon" in en-US.
    const threeDaysAgo = new Date('2026-04-27T19:09:00')
    renderItem(threeDaysAgo)
    // Three letters + space + clock — locked across en-US locales.
    expect(screen.getByText(/^[A-Za-z]{3} \d{1,2}:\d{2}\s?[AP]M$/i)).toBeInTheDocument()
  })

  it('renders "<month day> <time>" for a conversation older than a week', () => {
    const oldDate = new Date('2026-04-15T07:09:00')
    renderItem(oldDate)
    expect(screen.getByText(/^[A-Za-z]{3} \d{1,2} \d{1,2}:\d{2}\s?[AP]M$/i)).toBeInTheDocument()
  })

  it('exposes the full timestamp via a title tooltip', () => {
    const date = new Date('2026-04-30T07:09:00')
    renderItem(date)
    const label = screen.getByText(/^Today \d{1,2}:\d{2}\s?[AP]M$/i)
    expect(label).toHaveAttribute('title', date.toLocaleString())
  })
})
