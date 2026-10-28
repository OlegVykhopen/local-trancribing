import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { TranscriptsView } from './TranscriptsView'
import { deleteTranscript, getTranscript, getTranscriptsTree } from '../lib/api'
import type { TreeNode } from '../lib/types'

vi.mock('../lib/api', () => ({
  getTranscriptsTree: vi.fn(),
  getTranscript: vi.fn(),
  deleteTranscript: vi.fn(),
}))

const TEXT = '[00:00:00 - 00:00:05] SPEAKER_00: hello'

const fixture: TreeNode[] = [
  {
    name: 'therapy',
    path: 'therapy',
    type: 'dir',
    children: [{ name: 'done.m4a.txt', path: 'therapy/done.m4a.txt', type: 'file' }],
  },
]

function renderView(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/transcripts" element={<TranscriptsView />} />
      </Routes>
    </MemoryRouter>,
  )
}

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

beforeEach(() => {
  vi.mocked(getTranscriptsTree).mockResolvedValue(fixture)
  vi.mocked(getTranscript).mockResolvedValue(TEXT)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('TranscriptsView', () => {
  it('selects the transcript from ?path=, expands its dir, and loads it', async () => {
    renderView('/transcripts?path=therapy/done.m4a.txt')

    expect(await screen.findByText('done.m4a.txt')).toBeInTheDocument()
    await waitFor(() => expect(getTranscript).toHaveBeenCalledWith('therapy/done.m4a.txt'))
    expect(await screen.findByText(/SPEAKER_00: hello/)).toBeInTheDocument()
  })

  it('does not select anything without a ?path param', async () => {
    renderView('/transcripts')

    expect(await screen.findByText('therapy')).toBeInTheDocument()
    expect(screen.queryByText('done.m4a.txt')).not.toBeInTheDocument()
    expect(getTranscript).not.toHaveBeenCalled()
    expect(screen.getByText(/Select a transcript/)).toBeInTheDocument()
  })

  it('ignores a ?path that no longer exists in the tree', async () => {
    renderView('/transcripts?path=therapy/deleted.m4a.txt')

    expect(await screen.findByText('therapy')).toBeInTheDocument()
    expect(getTranscript).not.toHaveBeenCalled()
  })

  it('copies the transcript and shows Copied', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard(writeText)
    renderView('/transcripts?path=therapy/done.m4a.txt')

    await userEvent.click(await screen.findByRole('button', { name: 'Copy transcript' }))

    expect(writeText).toHaveBeenCalledWith(TEXT)
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('shows an error when the clipboard write fails', async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error('denied')))
    renderView('/transcripts?path=therapy/done.m4a.txt')

    await userEvent.click(await screen.findByRole('button', { name: 'Copy transcript' }))

    expect(await screen.findByText(/Could not copy/)).toBeInTheDocument()
  })

  it('deletes after inline confirm, refetches the tree, and empties the viewer', async () => {
    vi.mocked(deleteTranscript).mockResolvedValue(undefined)
    vi.mocked(getTranscriptsTree).mockResolvedValueOnce(fixture).mockResolvedValueOnce([])
    renderView('/transcripts?path=therapy/done.m4a.txt')

    await userEvent.click(await screen.findByRole('button', { name: 'Delete transcript' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(deleteTranscript).toHaveBeenCalledWith('therapy/done.m4a.txt'))
    await waitFor(() => expect(getTranscriptsTree).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/Select a transcript/)).toBeInTheDocument()
    expect(screen.getByText(/No transcripts yet/)).toBeInTheDocument()
  })

  it('reports a failed tree refresh after a successful delete and still empties the viewer', async () => {
    vi.mocked(deleteTranscript).mockResolvedValue(undefined)
    vi.mocked(getTranscriptsTree).mockResolvedValueOnce(fixture).mockRejectedValueOnce(new Error('500 Internal Server Error'))
    renderView('/transcripts?path=therapy/done.m4a.txt')

    await userEvent.click(await screen.findByRole('button', { name: 'Delete transcript' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText(/Deleted done\.m4a\.txt, but the list could not be refreshed/)).toBeInTheDocument()
    expect(screen.getByText(/Select a transcript/)).toBeInTheDocument()
  })

  it('shows the API error when delete is refused and keeps the transcript', async () => {
    vi.mocked(deleteTranscript).mockRejectedValue(new Error('409 a job is writing this transcript'))
    renderView('/transcripts?path=therapy/done.m4a.txt')

    await userEvent.click(await screen.findByRole('button', { name: 'Delete transcript' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText(/a job is writing this transcript/)).toBeInTheDocument()
    expect(screen.getByText(/SPEAKER_00: hello/)).toBeInTheDocument()
  })

  it('cancel keeps the transcript', async () => {
    renderView('/transcripts?path=therapy/done.m4a.txt')

    await userEvent.click(await screen.findByRole('button', { name: 'Delete transcript' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(deleteTranscript).not.toHaveBeenCalled()
    expect(screen.getByText(/SPEAKER_00: hello/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete transcript' })).toBeInTheDocument()
  })
})
