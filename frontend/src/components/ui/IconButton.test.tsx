import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { IconButton } from './IconButton'

describe('IconButton', () => {
  it('exposes label as aria-label and title and is type=button', () => {
    render(
      <IconButton label="Copy transcript">
        <svg />
      </IconButton>,
    )
    const btn = screen.getByRole('button', { name: 'Copy transcript' })
    expect(btn).toHaveAttribute('title', 'Copy transcript')
    expect(btn).toHaveAttribute('type', 'button')
  })
})
