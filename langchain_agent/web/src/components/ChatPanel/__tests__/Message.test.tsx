/**
 * Tests for Message component — user/assistant rendering, citations, streaming,
 * and the preprocessMarkdown helper (exercised via the component).
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Message } from '../Message'
import type { ChatMessage } from '../../../stores/chatStore'

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    role: 'user',
    content: 'Hello',
    timestamp: new Date('2026-01-01'),
    ...overrides,
  }
}

describe('Message — user messages', () => {
  it('renders the message content', () => {
    render(<Message message={makeMessage({ content: 'Hello world' })} />)
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('renders avatar with aria-label "You"', () => {
    render(<Message message={makeMessage()} />)
    expect(screen.getByLabelText('You')).toBeInTheDocument()
  })

  it('does NOT render the copy button for user messages', () => {
    render(<Message message={makeMessage()} />)
    expect(screen.queryByLabelText(/copy message/i)).not.toBeInTheDocument()
  })

  it('shows "Queued" text when status is queued', () => {
    render(<Message message={makeMessage({ status: 'queued' })} />)
    expect(screen.getByText('Queued')).toBeInTheDocument()
  })

  it('does not show "Queued" when status is not queued', () => {
    render(<Message message={makeMessage()} />)
    expect(screen.queryByText('Queued')).not.toBeInTheDocument()
  })
})

describe('Message — assistant messages', () => {
  const assistantMsg = makeMessage({ role: 'assistant', content: 'Here is the answer.' })

  it('renders the message content via markdown', () => {
    render(<Message message={assistantMsg} />)
    expect(screen.getByText(/Here is the answer/)).toBeInTheDocument()
  })

  it('renders avatar with aria-label "Agent"', () => {
    render(<Message message={assistantMsg} />)
    expect(screen.getByLabelText('Agent')).toBeInTheDocument()
  })

  it('renders the copy button', () => {
    render(<Message message={assistantMsg} />)
    expect(screen.getByLabelText(/copy message to clipboard/i)).toBeInTheDocument()
  })

  it('shows "..." placeholder when content is empty string', () => {
    render(<Message message={makeMessage({ role: 'assistant', content: '' })} />)
    // preprocessMarkdown receives '' and falls through to '...' via `|| '...'`
    expect(screen.getByText('...')).toBeInTheDocument()
  })

  it('shows streaming indicator when isStreaming is true', () => {
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Working...', isStreaming: true })} />
    )
    expect(screen.getByLabelText('Generating response')).toBeInTheDocument()
  })

  it('does not show streaming indicator when isStreaming is false', () => {
    render(<Message message={assistantMsg} />)
    expect(screen.queryByLabelText('Generating response')).not.toBeInTheDocument()
  })
})

describe('Message — copy button', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('copies content to clipboard and shows Copied state on click', async () => {
    const user = userEvent.setup()
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Copy me' })} />
    )
    // Verify the button starts in un-copied state
    expect(screen.getByLabelText(/copy message to clipboard/i)).toBeInTheDocument()

    await user.click(screen.getByLabelText(/copy message to clipboard/i))

    // After clicking the label should update to indicate success
    await waitFor(() =>
      expect(screen.getByLabelText('Copied to clipboard')).toBeInTheDocument()
    )
  })
})

describe('Message — citations', () => {
  const citations = [
    { url: 'https://example.com/a', label: 'Example A' },
    { url: 'https://example.com/b', label: 'Example B' },
  ]

  it('shows Sources toggle button with count', () => {
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Answer', citations })} />
    )
    expect(screen.getByText('Sources (2)')).toBeInTheDocument()
  })

  it('does not show citation links before toggle is clicked', () => {
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Answer', citations })} />
    )
    expect(screen.queryByText('Example A')).not.toBeInTheDocument()
  })

  it('reveals citation links after clicking the toggle', async () => {
    const user = userEvent.setup()
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Answer', citations })} />
    )
    await user.click(screen.getByText('Sources (2)'))
    expect(screen.getByText('Example A')).toBeInTheDocument()
    expect(screen.getByText('Example B')).toBeInTheDocument()
  })

  it('hides citation links after clicking the toggle a second time', async () => {
    const user = userEvent.setup()
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Answer', citations })} />
    )
    await user.click(screen.getByText('Sources (2)'))
    await user.click(screen.getByText('Sources (2)'))
    expect(screen.queryByText('Example A')).not.toBeInTheDocument()
  })

  it('does not show Sources button when there are no citations', () => {
    render(
      <Message message={makeMessage({ role: 'assistant', content: 'Answer', citations: [] })} />
    )
    expect(screen.queryByText(/sources/i)).not.toBeInTheDocument()
  })
})

describe('Message — preprocessMarkdown (via rendered output)', () => {
  it('converts <br> tags to newlines in rendered content', () => {
    // The content has <br> which preprocessMarkdown converts to \n
    // ReactMarkdown then renders it as a paragraph break.
    render(
      <Message
        message={makeMessage({ role: 'assistant', content: 'Line one<br>Line two' })}
      />
    )
    // Both lines should be present in the DOM
    expect(screen.getByText(/Line one/)).toBeInTheDocument()
    expect(screen.getByText(/Line two/)).toBeInTheDocument()
  })

  it('handles array content blocks (Gemini format)', () => {
    const arrayContent = [
      { text: 'Part one ' },
      { text: 'part two' },
    ] as unknown as string
    render(
      <Message message={makeMessage({ role: 'assistant', content: arrayContent })} />
    )
    expect(screen.getByText(/Part one/)).toBeInTheDocument()
    expect(screen.getByText(/part two/)).toBeInTheDocument()
  })
})
