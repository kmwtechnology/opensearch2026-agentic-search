/**
 * Tests for ErrorNotification component.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ErrorNotification } from '../ErrorNotification'

describe('ErrorNotification', () => {
  describe('rendering', () => {
    it('displays the error message', () => {
      render(
        <ErrorNotification
          message="Something went wrong"
          onDismiss={vi.fn()}
        />
      )
      expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    })

    it('has role="alert" for accessibility', () => {
      render(
        <ErrorNotification message="Error" onDismiss={vi.fn()} />
      )
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    it('renders a dismiss button', () => {
      render(
        <ErrorNotification message="Error" onDismiss={vi.fn()} />
      )
      expect(screen.getByLabelText(/dismiss error message/i)).toBeInTheDocument()
    })
  })

  describe('dismiss button', () => {
    it('calls onDismiss when the dismiss button is clicked', async () => {
      const onDismiss = vi.fn()
      const user = userEvent.setup()
      render(
        <ErrorNotification message="Error" onDismiss={onDismiss} />
      )
      await user.click(screen.getByLabelText(/dismiss error message/i))
      expect(onDismiss).toHaveBeenCalledTimes(1)
    })
  })

  describe('autoClose', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('calls onDismiss after the default duration (5000ms)', () => {
      const onDismiss = vi.fn()
      render(
        <ErrorNotification message="Error" onDismiss={onDismiss} />
      )
      expect(onDismiss).not.toHaveBeenCalled()
      vi.advanceTimersByTime(5000)
      expect(onDismiss).toHaveBeenCalledTimes(1)
    })

    it('calls onDismiss after a custom duration', () => {
      const onDismiss = vi.fn()
      render(
        <ErrorNotification message="Error" onDismiss={onDismiss} duration={3000} />
      )
      vi.advanceTimersByTime(2999)
      expect(onDismiss).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1)
      expect(onDismiss).toHaveBeenCalledTimes(1)
    })

    it('does NOT auto-dismiss when autoClose is false', () => {
      const onDismiss = vi.fn()
      render(
        <ErrorNotification message="Error" onDismiss={onDismiss} autoClose={false} />
      )
      vi.advanceTimersByTime(10_000)
      expect(onDismiss).not.toHaveBeenCalled()
    })
  })
})
