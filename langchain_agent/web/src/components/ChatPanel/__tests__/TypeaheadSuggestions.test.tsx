/**
 * Tests for TypeaheadSuggestions — product rows, spell correction banner,
 * recent searches, ARIA listbox contract, abort-on-stale-query.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TypeaheadSuggestions } from '../TypeaheadSuggestions'

vi.mock('../../../utils/api', () => ({
  apiGet: vi.fn(),
}))

import { apiGet } from '../../../utils/api'

const mockApiGet = apiGet as unknown as ReturnType<typeof vi.fn>

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response
}

beforeEach(() => {
  mockApiGet.mockReset()
  window.localStorage.clear()
})

describe('TypeaheadSuggestions', () => {
  it('renders skeleton rows while the request is in flight', async () => {
    // Promise that never resolves — UI stays in loading state.
    mockApiGet.mockReturnValueOnce(new Promise(() => {}))

    render(
      <TypeaheadSuggestions
        query="sony"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    await waitFor(
      () => expect(screen.getByText(/loading suggestions/i)).toBeInTheDocument(),
      { timeout: 1000 }
    )
  })

  it('renders product rows with brand and score', async () => {
    mockApiGet.mockResolvedValueOnce(
      jsonResponse({
        suggestions: [
          { title: 'Sony WH-1000XM5', brand: 'Sony', score: 0.95, highlight: null },
          { title: 'Sony Bravia', brand: 'Sony', score: 0.5, highlight: null },
        ],
        spell_correction: null,
      })
    )

    render(
      <TypeaheadSuggestions
        query="sony"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    await waitFor(
      () => expect(screen.getByText('Sony WH-1000XM5')).toBeInTheDocument(),
      { timeout: 1500 }
    )
    expect(screen.getByText('Sony Bravia')).toBeInTheDocument()
    expect(screen.getByText('Match: 50%')).toBeInTheDocument()
  })

  it('renders "Did you mean" banner and fires onSelect with type=spelling', async () => {
    const onSelect = vi.fn()
    mockApiGet.mockResolvedValueOnce(
      jsonResponse({
        suggestions: [{ title: 'Sony WH-1000XM5', brand: 'Sony', score: 0.8, highlight: null }],
        spell_correction: { title: 'sony', brand: 'Sony', score: 0.9, highlight: null },
      })
    )

    const user = userEvent.setup()
    render(
      <TypeaheadSuggestions
        query="sonie"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={onSelect}
      />
    )

    await waitFor(
      () => expect(screen.getByText(/did you mean:/i)).toBeInTheDocument(),
      { timeout: 1500 }
    )
    await user.click(screen.getByText('sony'))
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ type: 'spelling', title: 'sony' }))
  })

  it('shows the empty state when no suggestions come back', async () => {
    mockApiGet.mockResolvedValueOnce(jsonResponse({ suggestions: [], spell_correction: null }))

    render(
      <TypeaheadSuggestions
        query="zzznothing"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    await waitFor(
      () => expect(screen.getByText(/no products found/i)).toBeInTheDocument(),
      { timeout: 1500 }
    )
  })

  it('renders <mark> from highlight fragments', async () => {
    mockApiGet.mockResolvedValueOnce(
      jsonResponse({
        suggestions: [
          {
            title: 'Sony WH-1000XM5',
            brand: 'Sony',
            score: 0.8,
            highlight: ['<mark data-th>Son</mark>y WH-1000XM5'],
          },
        ],
        spell_correction: null,
      })
    )

    const { container } = render(
      <TypeaheadSuggestions
        query="son"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    await waitFor(() => expect(container.querySelector('mark')).not.toBeNull(), { timeout: 1500 })
    expect(container.querySelector('mark')?.textContent).toBe('Son')
  })

  it('applies listbox/option ARIA roles with aria-selected tracking selectedIndex', async () => {
    mockApiGet.mockResolvedValueOnce(
      jsonResponse({
        suggestions: [
          { title: 'Sony A', brand: null, score: 1, highlight: null },
          { title: 'Sony B', brand: null, score: 1, highlight: null },
        ],
        spell_correction: null,
      })
    )

    render(
      <TypeaheadSuggestions
        query="sony"
        isOpen={true}
        selectedIndex={1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2), { timeout: 1500 })
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'false')
    expect(options[1]).toHaveAttribute('aria-selected', 'true')
  })

  it('fires onSelect with type=product when a suggestion row is clicked', async () => {
    const onSelect = vi.fn()
    mockApiGet.mockResolvedValueOnce(
      jsonResponse({
        suggestions: [{ title: 'Sony A', brand: null, score: 1, highlight: null }],
        spell_correction: null,
      })
    )

    const user = userEvent.setup()
    render(
      <TypeaheadSuggestions
        query="sony"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={onSelect}
      />
    )

    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(1), { timeout: 1500 })
    await user.click(screen.getByRole('option'))
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'product', title: 'Sony A' })
    )
  })

  it('renders recent searches when query is empty', async () => {
    window.localStorage.setItem(
      'agentic-search-recent',
      JSON.stringify(['wireless headphones', 'sony tv'])
    )
    const onSelect = vi.fn()
    const user = userEvent.setup()

    render(
      <TypeaheadSuggestions
        query=""
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={onSelect}
      />
    )

    expect(screen.getByText('wireless headphones')).toBeInTheDocument()
    expect(screen.getByText('sony tv')).toBeInTheDocument()
    await user.click(screen.getByText('sony tv'))
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'recent', title: 'sony tv' })
    )
  })

  it('aborts the in-flight request when the query changes', async () => {
    let firstAborted = false

    mockApiGet
      .mockImplementationOnce((_url: string, options: { signal?: AbortSignal }) => {
        return new Promise<Response>((_, reject) => {
          options.signal?.addEventListener('abort', () => {
            firstAborted = true
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
          })
        })
      })
      .mockResolvedValueOnce(
        jsonResponse({
          suggestions: [{ title: 'Sony Final', brand: null, score: 1, highlight: null }],
          spell_correction: null,
        })
      )

    const { rerender } = render(
      <TypeaheadSuggestions
        query="son"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    // Wait until the first request is mid-flight, then change the query.
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1), { timeout: 1000 })

    rerender(
      <TypeaheadSuggestions
        query="sony"
        isOpen={true}
        selectedIndex={-1}
        listboxId="lb"
        onSelect={vi.fn()}
      />
    )

    await waitFor(() => expect(firstAborted).toBe(true), { timeout: 1500 })
    await waitFor(() => expect(screen.getByText('Sony Final')).toBeInTheDocument(), {
      timeout: 1500,
    })
  })
})
