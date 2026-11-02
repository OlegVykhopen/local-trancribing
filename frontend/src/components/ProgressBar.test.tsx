import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ProgressBar } from './ProgressBar'

describe('ProgressBar', () => {
  it('renders a determinate full bar at 100%', () => {
    render(<ProgressBar percent={100} stage="done" />)

    expect(screen.getByTestId('progress-bar-fill')).toBeInTheDocument()
    expect(screen.queryByTestId('progress-bar-indeterminate')).not.toBeInTheDocument()
  })

  it('animates indeterminately at 0% during an unmetered stage', () => {
    render(<ProgressBar percent={0} stage="aligning" />)

    expect(screen.getByTestId('progress-bar-indeterminate')).toBeInTheDocument()
    expect(screen.queryByTestId('progress-bar-fill')).not.toBeInTheDocument()
  })

  it('stays determinate at 0% when the stage is blanked (terminal jobs)', () => {
    render(<ProgressBar percent={0} stage="" />)

    expect(screen.getByTestId('progress-bar-fill')).toBeInTheDocument()
    expect(screen.queryByTestId('progress-bar-indeterminate')).not.toBeInTheDocument()
  })

  it('is indeterminate when percent is null (queued)', () => {
    render(<ProgressBar percent={null} stage="" />)

    expect(screen.getByTestId('progress-bar-indeterminate')).toBeInTheDocument()
  })
})
