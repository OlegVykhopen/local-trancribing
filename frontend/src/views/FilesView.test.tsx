import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { FilesView } from './FilesView'
import { getFiles, getTranscript } from '../lib/api'
import type { TreeNode } from '../lib/types'

vi.mock('../lib/api', () => ({
  getFiles: vi.fn(),
  getTranscript: vi.fn(),
}))

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

function renderFilesView(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/files" element={<FilesView />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(getFiles).mockResolvedValue(fixture)
  vi.mocked(getTranscript).mockResolvedValue('[00:00:00 - 00:00:05] SPEAKER_00: hello')
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('FilesView deep link', () => {
  it('selects the file from ?path=, expands its dir, and loads the transcript', async () => {
    renderFilesView('/files?path=therapy/done.m4a')

    // Dir auto-expanded so the selected row is visible.
    expect(await screen.findByText('done.m4a')).toBeInTheDocument()
    await waitFor(() => expect(getTranscript).toHaveBeenCalledWith('therapy/done.m4a.txt'))
    expect(await screen.findByText(/SPEAKER_00: hello/)).toBeInTheDocument()
  })

  it('does not select anything without a ?path param', async () => {
    renderFilesView('/files')

    expect(await screen.findByText('therapy')).toBeInTheDocument()
    // Dir stays collapsed, nothing fetched.
    expect(screen.queryByText('done.m4a')).not.toBeInTheDocument()
    expect(getTranscript).not.toHaveBeenCalled()
  })

  it('ignores a ?path that no longer exists in the tree', async () => {
    renderFilesView('/files?path=therapy/deleted.m4a')

    expect(await screen.findByText('therapy')).toBeInTheDocument()
    expect(getTranscript).not.toHaveBeenCalled()
  })
})
