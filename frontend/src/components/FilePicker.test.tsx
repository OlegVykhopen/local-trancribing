import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { FilePicker } from './FilePicker'
import type { TreeNode } from '../lib/types'

const fixture: TreeNode[] = [
  {
    name: 'therapy',
    path: 'therapy',
    type: 'dir',
    children: [
      { name: 'done.m4a', path: 'therapy/done.m4a', type: 'file', transcribed: true },
      { name: 'pending.m4a', path: 'therapy/pending.m4a', type: 'file', transcribed: false },
    ],
  },
]

function renderPicker(onSelect = vi.fn()) {
  render(
    <MemoryRouter>
      <FilePicker nodes={fixture} onSelect={onSelect} categories={[]} accept="" onUpload={vi.fn()} onDelete={vi.fn()} />
    </MemoryRouter>,
  )
  return onSelect
}

describe('FilePicker', () => {
  it('links the transcribed badge to the transcript and does not select the file', async () => {
    const onSelect = renderPicker()
    await userEvent.click(screen.getByText('therapy'))

    const badge = screen.getByTestId('transcribed-badge')
    expect(badge).toHaveAttribute('href', '/transcripts?path=therapy%2Fdone.m4a.txt')

    await userEvent.click(badge)
    expect(onSelect).not.toHaveBeenCalled()

    await userEvent.click(screen.getByText('done.m4a'))
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ path: 'therapy/done.m4a' }))
  })
})
