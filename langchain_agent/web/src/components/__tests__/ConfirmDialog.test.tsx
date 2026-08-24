/**
 * Tests for ConfirmDialog component.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDialog } from '../ConfirmDialog'

const defaultProps = {
  isOpen: true,
  title: 'Delete item',
  message: 'Are you sure you want to delete this item?',
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
}

describe('ConfirmDialog', () => {
  describe('when closed', () => {
    it('renders nothing when isOpen is false', () => {
      const { container } = render(
        <ConfirmDialog {...defaultProps} isOpen={false} />
      )
      expect(container.firstChild).toBeNull()
    })
  })

  describe('when open', () => {
    it('renders the title', () => {
      render(<ConfirmDialog {...defaultProps} />)
      expect(screen.getByText('Delete item')).toBeInTheDocument()
    })

    it('renders the message', () => {
      render(<ConfirmDialog {...defaultProps} />)
      expect(screen.getByText('Are you sure you want to delete this item?')).toBeInTheDocument()
    })

    it('has role="alertdialog" for accessibility', () => {
      render(<ConfirmDialog {...defaultProps} />)
      expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    })

    it('renders a confirm button with default text "Confirm"', () => {
      render(<ConfirmDialog {...defaultProps} />)
      expect(screen.getByText('Confirm')).toBeInTheDocument()
    })

    it('renders a cancel button with default text "Cancel"', () => {
      render(<ConfirmDialog {...defaultProps} />)
      expect(screen.getByText('Cancel')).toBeInTheDocument()
    })

    it('renders custom confirmText', () => {
      render(<ConfirmDialog {...defaultProps} confirmText="Delete" />)
      expect(screen.getByText('Delete')).toBeInTheDocument()
    })

    it('renders custom cancelText', () => {
      render(<ConfirmDialog {...defaultProps} cancelText="Go back" />)
      expect(screen.getByText('Go back')).toBeInTheDocument()
    })

    it('renders a close button in the header', () => {
      render(<ConfirmDialog {...defaultProps} />)
      expect(screen.getByLabelText('Close dialog')).toBeInTheDocument()
    })
  })

  describe('user interactions', () => {
    it('calls onConfirm when confirm button is clicked', async () => {
      const onConfirm = vi.fn()
      const user = userEvent.setup()
      render(<ConfirmDialog {...defaultProps} onConfirm={onConfirm} />)
      await user.click(screen.getByText('Confirm'))
      expect(onConfirm).toHaveBeenCalledTimes(1)
    })

    it('calls onCancel when cancel button is clicked', async () => {
      const onCancel = vi.fn()
      const user = userEvent.setup()
      render(<ConfirmDialog {...defaultProps} onCancel={onCancel} />)
      await user.click(screen.getByText('Cancel'))
      expect(onCancel).toHaveBeenCalledTimes(1)
    })

    it('calls onCancel when the close (X) button is clicked', async () => {
      const onCancel = vi.fn()
      const user = userEvent.setup()
      render(<ConfirmDialog {...defaultProps} onCancel={onCancel} />)
      await user.click(screen.getByLabelText('Close dialog'))
      expect(onCancel).toHaveBeenCalledTimes(1)
    })

    it('calls onCancel when Escape key is pressed', async () => {
      const onCancel = vi.fn()
      const user = userEvent.setup()
      render(<ConfirmDialog {...defaultProps} onCancel={onCancel} />)
      await user.keyboard('{Escape}')
      expect(onCancel).toHaveBeenCalledTimes(1)
    })
  })

  describe('loading state', () => {
    it('shows "Processing..." on confirm button when isLoading', () => {
      render(<ConfirmDialog {...defaultProps} isLoading={true} />)
      expect(screen.getByText('Processing...')).toBeInTheDocument()
    })

    it('disables the confirm button when isLoading', () => {
      render(<ConfirmDialog {...defaultProps} confirmText="Delete" isLoading={true} />)
      const btn = screen.getByText('Processing...')
      expect(btn).toBeDisabled()
    })

    it('disables the cancel button when isLoading', () => {
      render(<ConfirmDialog {...defaultProps} isLoading={true} />)
      expect(screen.getByText('Cancel')).toBeDisabled()
    })

    it('disables the close button when isLoading', () => {
      render(<ConfirmDialog {...defaultProps} isLoading={true} />)
      expect(screen.getByLabelText('Close dialog')).toBeDisabled()
    })
  })

  describe('dangerous variant', () => {
    it('shows the AlertCircle icon when isDangerous', () => {
      const { container } = render(
        <ConfirmDialog {...defaultProps} isDangerous={true} />
      )
      // The svg is aria-hidden but the parent button context holds the danger icon
      const icons = container.querySelectorAll('svg[aria-hidden="true"]')
      expect(icons.length).toBeGreaterThan(0)
    })
  })
})
