import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { TranscribeView } from './TranscribeView'
import { resetEventsForTests } from '../lib/useEvents'
import { createTranscribeJob, getFiles, getJobs, getMeta } from '../lib/api'
import type { Job } from '../lib/types'
import type { Meta, TreeNode } from '../lib/types'

vi.mock('../lib/api', () => ({
  getFiles: vi.fn(),
  getMeta: vi.fn(),
  getJobs: vi.fn(),
  createTranscribeJob: vi.fn(),
}))

class FakeEventSource {
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  addEventListener() {}
  close() {}
}

const tree: TreeNode[] = [
  {
    name: 'podcast',
    path: 'podcast',
    type: 'dir',
    children: [{ name: 'ep1.mp3', path: 'podcast/ep1.mp3', type: 'file' }],
  },
]

const meta: Meta = {
  models: ['tiny', 'base', 'medium'],
  default_model: 'base',
  hf_token_present: true,
  languages: [
    { code: 'en', name: 'english' },
    { code: 'uk', name: 'ukrainian' },
  ],
  supported_extensions: ['.m4a', '.mp3'],
}

function LocationStateProbe() {
  const location = useLocation()
  return <p data-testid="location-state">{JSON.stringify(location.state ?? null)}</p>
}

function renderTranscribeView(initialEntry: unknown = '/files') {
  return render(
    <MemoryRouter initialEntries={[initialEntry as string]}>
      <LocationStateProbe />
      <Routes>
        <Route path="/files" element={<TranscribeView />} />
        <Route path="/job/:id" element={<p>job page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderWithRetry(retry: Record<string, unknown>) {
  return renderTranscribeView({ pathname: '/files', state: { retry } })
}

beforeEach(() => {
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.mocked(getFiles).mockResolvedValue(tree)
  vi.mocked(getMeta).mockResolvedValue(meta)
  vi.mocked(getJobs).mockResolvedValue([])
})

afterEach(() => {
  resetEventsForTests()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('TranscribeView', () => {
  it('renders the language field as a dropdown of valid languages with auto-detect default', async () => {
    renderTranscribeView()

    const select = (await screen.findByLabelText('Language')) as HTMLSelectElement
    expect(select.tagName).toBe('SELECT')
    expect(select.value).toBe('')

    const options = Array.from(select.options).map((o) => ({ value: o.value, label: o.label }))
    expect(options[0].value).toBe('')
    expect(options).toContainEqual({ value: 'uk', label: 'Ukrainian (uk)' })
    expect(options).toContainEqual({ value: 'en', label: 'English (en)' })
  })

  it('prefills the form from retry state so the failed job can be resubmitted', async () => {
    renderTranscribeView({
      pathname: '/files',
      state: {
        retry: { path: 'podcast/ep1.mp3', model: 'medium', language: 'UK', diarize: true, num_speakers: 2 },
      },
    })

    // "UK" (the invalid code the job failed with) must come back as valid "uk"
    const language = (await screen.findByLabelText('Language')) as HTMLSelectElement
    await waitFor(() => expect(language.value).toBe('uk'))
    expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('medium')
    expect((screen.getByLabelText(/Identify speakers/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/Number of speakers/) as HTMLInputElement).value).toBe('2')

    // the file is preselected: submitting works without touching the picker
    vi.mocked(createTranscribeJob).mockResolvedValue({ job_id: 9 })
    await userEvent.click(screen.getByRole('button', { name: 'Transcribe' }))
    expect(createTranscribeJob).toHaveBeenCalledWith({
      path: 'podcast/ep1.mp3',
      model: 'medium',
      language: 'uk',
      diarize: true,
      num_speakers: 2,
    })
  })

  it('falls back to Auto-detect with a notice when the retry language is not a valid code', async () => {
    renderWithRetry({ path: 'podcast/ep1.mp3', model: 'medium', language: 'zz', diarize: false })

    const language = (await screen.findByLabelText('Language')) as HTMLSelectElement
    await waitFor(() =>
      expect(screen.getByText(/Language "zz" isn't valid — reset to Auto-detect\./)).toBeInTheDocument(),
    )
    expect(language.value).toBe('')
  })

  it('falls back to the default model with a notice when the retry model is unavailable', async () => {
    renderWithRetry({ path: 'podcast/ep1.mp3', model: 'large-v3', diarize: false })

    const model = (await screen.findByLabelText('Model')) as HTMLSelectElement
    await waitFor(() =>
      expect(screen.getByText(/Model "large-v3" is unavailable — using base\./)).toBeInTheDocument(),
    )
    expect(model.value).toBe('base')
  })

  it('shows a notice naming the file when the retried file no longer exists', async () => {
    renderWithRetry({ path: 'podcast/deleted.mp3', model: 'medium', diarize: false })

    await screen.findByLabelText('Language')
    await waitFor(() =>
      expect(
        screen.getByText(/The original file "podcast\/deleted\.mp3" no longer exists — pick a file\./),
      ).toBeInTheDocument(),
    )
  })

  it('does not prefill diarize when the HF token is absent, and says so', async () => {
    vi.mocked(getMeta).mockResolvedValue({ ...meta, hf_token_present: false })
    renderWithRetry({ path: 'podcast/ep1.mp3', model: 'medium', diarize: true, num_speakers: 2 })

    await screen.findByLabelText('Language')
    await waitFor(() =>
      expect(screen.getByText(/Speaker diarization is unavailable without HF_TOKEN/)).toBeInTheDocument(),
    )
    expect((screen.getByLabelText(/Identify speakers/) as HTMLInputElement).checked).toBe(false)
  })

  it('clears the retry state from history after prefilling so Back cannot re-apply it', async () => {
    renderWithRetry({ path: 'podcast/ep1.mp3', model: 'medium', language: 'uk', diarize: false })

    const language = (await screen.findByLabelText('Language')) as HTMLSelectElement
    await waitFor(() => expect(language.value).toBe('uk'))
    await waitFor(() => expect(screen.getByTestId('location-state').textContent).toBe('null'))
  })

  it('links a done job in history to its transcript on the Transcripts tab', async () => {
    const done: Job = {
      id: 7,
      kind: 'transcribe',
      status: 'done',
      params: { path: 'podcast/ep1.mp3', model: 'base' },
      category: 'podcast',
      progress: 100,
      stage: null,
      result: { output_path: 'podcast/ep1.mp3.txt' },
      error: null,
      created_at: '2026-10-28T10:00:00',
      started_at: null,
      finished_at: null,
    }
    vi.mocked(getJobs).mockResolvedValue([done])
    renderTranscribeView()

    const link = await screen.findByRole('link', { name: /view transcript/ })
    expect(link).toHaveAttribute('href', '#/transcripts?path=podcast%2Fep1.mp3.txt')
  })
})
