import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FileTree } from './FileTree'
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
  {
    name: 'consulting',
    path: 'consulting',
    type: 'dir',
    children: [
      {
        name: 'marketing',
        path: 'consulting/marketing',
        type: 'dir',
        children: [{ name: 'talk.mp3', path: 'consulting/marketing/talk.mp3', type: 'file', transcribed: true }],
      },
    ],
  },
]

describe('FileTree', () => {
  it('renders top-level directory names, initially collapsed', () => {
    render(<FileTree nodes={fixture} onSelectFile={vi.fn()} />)

    expect(screen.getByText('therapy')).toBeInTheDocument()
    expect(screen.getByText('consulting')).toBeInTheDocument()
    expect(screen.queryByText('done.m4a')).not.toBeInTheDocument()
    expect(screen.queryByText('pending.m4a')).not.toBeInTheDocument()
  })

  it('shows a transcribed badge only for transcribed files, after expanding the dir', async () => {
    const user = userEvent.setup()
    render(<FileTree nodes={fixture} onSelectFile={vi.fn()} />)

    await user.click(screen.getByText('therapy'))

    const doneRow = screen.getByText('done.m4a').closest('[data-testid="file-row"]') as HTMLElement
    const pendingRow = screen.getByText('pending.m4a').closest('[data-testid="file-row"]') as HTMLElement

    expect(doneRow.querySelector('[data-testid="transcribed-badge"]')).not.toBeNull()
    expect(pendingRow.querySelector('[data-testid="transcribed-badge"]')).toBeNull()
  })

  it('toggles a directory open and closed on repeated clicks', async () => {
    const user = userEvent.setup()
    render(<FileTree nodes={fixture} onSelectFile={vi.fn()} />)

    await user.click(screen.getByText('therapy'))
    expect(screen.getByText('done.m4a')).toBeInTheDocument()

    await user.click(screen.getByText('therapy'))
    expect(screen.queryByText('done.m4a')).not.toBeInTheDocument()
  })

  it('calls onSelectFile with the node when a file is clicked', async () => {
    const user = userEvent.setup()
    const onSelectFile = vi.fn()
    render(<FileTree nodes={fixture} onSelectFile={onSelectFile} />)

    await user.click(screen.getByText('therapy'))
    await user.click(screen.getByText('done.m4a'))

    expect(onSelectFile).toHaveBeenCalledWith(fixture[0].children![0])
  })

  it('renders nested directories once their parent is expanded', async () => {
    const user = userEvent.setup()
    render(<FileTree nodes={fixture} onSelectFile={vi.fn()} />)

    expect(screen.queryByText('marketing')).not.toBeInTheDocument()
    await user.click(screen.getByText('consulting'))
    expect(screen.getByText('marketing')).toBeInTheDocument()
  })

  it('auto-expands every ancestor of the selected path, and manual collapse still wins', async () => {
    const user = userEvent.setup()
    render(<FileTree nodes={fixture} onSelectFile={vi.fn()} selectedPath="consulting/marketing/talk.mp3" />)

    // Two levels deep, visible without any clicks.
    expect(screen.getByText('talk.mp3')).toBeInTheDocument()
    // Unrelated dirs stay collapsed.
    expect(screen.queryByText('done.m4a')).not.toBeInTheDocument()

    await user.click(screen.getByText('consulting'))
    expect(screen.queryByText('talk.mp3')).not.toBeInTheDocument()
  })
})
