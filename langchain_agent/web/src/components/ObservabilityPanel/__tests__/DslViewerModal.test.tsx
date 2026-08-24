/**
 * Tests for DslViewerModal — the modal that renders the OpenSearch DSL body
 * behind the eye-icon triggers in the observability panel.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DslViewerModal } from '../DslViewerModal'

const SAMPLE_BODY = {
  size: 4,
  query: {
    bool: {
      must: [{ multi_match: { query: 'shoes', fields: ['title^2', 'chunk_text'] } }],
      filter: [{ term: { collection_id: 'esci_products' } }],
    },
  },
}

describe('DslViewerModal', () => {
  it('renders nothing when isOpen is false', () => {
    render(
      <DslViewerModal
        isOpen={false}
        title="Hybrid query DSL"
        body={SAMPLE_BODY}
        onClose={() => undefined}
      />
    )
    expect(screen.queryByText('Hybrid query DSL')).not.toBeInTheDocument()
  })

  it('renders title and JSON body when open', () => {
    render(
      <DslViewerModal
        isOpen={true}
        title="Hybrid query DSL"
        body={SAMPLE_BODY}
        onClose={() => undefined}
      />
    )
    expect(screen.getByText('Hybrid query DSL')).toBeInTheDocument()
    expect(screen.getByText(/multi_match/)).toBeInTheDocument()
  })

  it('renders POST request line when index is provided', () => {
    render(
      <DslViewerModal
        isOpen={true}
        title="Hybrid query DSL"
        body={SAMPLE_BODY}
        index="agentic_hybrid_search_docs"
        params={{ search_pipeline: 'hybrid_search_pipeline' }}
        onClose={() => undefined}
      />
    )
    expect(
      screen.getByText('POST /agentic_hybrid_search_docs/_search?search_pipeline=hybrid_search_pipeline')
    ).toBeInTheDocument()
  })

  it('omits the request line when index is missing', () => {
    render(
      <DslViewerModal
        isOpen={true}
        title="Test"
        body={SAMPLE_BODY}
        onClose={() => undefined}
      />
    )
    expect(screen.queryByText(/POST \//)).not.toBeInTheDocument()
  })

  it('handles null body gracefully', () => {
    render(
      <DslViewerModal
        isOpen={true}
        title="Empty"
        body={null}
        onClose={() => undefined}
      />
    )
    expect(screen.getByText('Empty')).toBeInTheDocument()
    expect(screen.getByText(/no DSL body available/)).toBeInTheDocument()
  })

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn()
    render(
      <DslViewerModal
        isOpen={true}
        title="Test"
        body={SAMPLE_BODY}
        onClose={onClose}
      />
    )
    await userEvent.click(screen.getByLabelText('Close DSL viewer'))
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose when Escape is pressed', async () => {
    const onClose = vi.fn()
    render(
      <DslViewerModal
        isOpen={true}
        title="Test"
        body={SAMPLE_BODY}
        onClose={onClose}
      />
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('copy button writes the request line + body to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(
      <DslViewerModal
        isOpen={true}
        title="Test"
        body={SAMPLE_BODY}
        index="my_index"
        params={{ search_pipeline: 'hybrid_search_pipeline' }}
        onClose={() => undefined}
      />
    )
    await userEvent.click(screen.getByLabelText('Copy DSL to clipboard'))
    expect(writeText).toHaveBeenCalledOnce()
    const written = writeText.mock.calls[0][0] as string
    expect(written).toContain('POST /my_index/_search?search_pipeline=hybrid_search_pipeline')
    expect(written).toContain('multi_match')
  })
})
