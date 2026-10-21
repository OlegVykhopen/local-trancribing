import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { JobView } from './JobView'
import { resetEventsForTests } from '../lib/useEvents'
import { cancelJob, getJob, getJobLogs } from '../lib/api'
import type { Job } from '../lib/types'

vi.mock('../lib/api', () => ({
  getJob: vi.fn(),
  getJobLogs: vi.fn(),
  cancelJob: vi.fn(),
}))

type Handler = (event: MessageEvent) => void

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  private handlers = new Map<string, Handler[]>()

  constructor(_url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, handler: Handler) {
    const list = this.handlers.get(type) ?? []
    list.push(handler)
    this.handlers.set(type, list)
  }

  close() {}

  emit(type: string, data: unknown) {
    for (const handler of this.handlers.get(type) ?? []) {
      handler({ data: JSON.stringify(data) } as MessageEvent)
    }
  }
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 1,
    kind: 'transcribe',
    status: 'running',
    params: { path: 'podcast/ep1.mp3' },
    category: 'podcast',
    progress: 40,
    stage: 'transcribing',
    result: null,
    error: null,
    created_at: '2026-10-20T00:00:00',
    started_at: '2026-10-20T00:00:01',
    finished_at: null,
    ...overrides,
  }
}

function TranscribeRouteProbe() {
  const location = useLocation()
  return <p>transcribe page, state: {JSON.stringify(location.state)}</p>
}

function FilesRouteProbe() {
  const location = useLocation()
  return <p>files page, search: {location.search}</p>
}

function renderJobView() {
  return render(
    <MemoryRouter initialEntries={['/job/1']}>
      <Routes>
        <Route path="/job/:id" element={<JobView />} />
        <Route path="/transcribe" element={<TranscribeRouteProbe />} />
        <Route path="/files" element={<FilesRouteProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
  vi.mocked(getJobLogs).mockResolvedValue([])
})

afterEach(() => {
  resetEventsForTests()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('JobView', () => {
  it('merges job_status events for its own job id and ignores other jobs', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob())
    renderJobView()
    expect(await screen.findByText('running')).toBeInTheDocument()

    const source = FakeEventSource.instances[0]
    act(() => {
      source.emit('job_status', { type: 'job_status', job_id: 2, status: 'error', error: 'other job' })
    })
    expect(screen.getByText('running')).toBeInTheDocument()

    act(() => {
      source.emit('job_status', { type: 'job_status', job_id: 1, status: 'done', result: null })
    })
    expect(screen.getByText('done')).toBeInTheDocument()
  })

  it('shows a cancel failure instead of swallowing it', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob())
    vi.mocked(cancelJob).mockRejectedValue(new Error('409 job is not cancellable (status: done)'))
    renderJobView()

    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(await screen.findByText(/Cancel failed: 409 job is not cancellable/)).toBeInTheDocument()
  })

  it('surfaces a skipped transcription as a visible notice', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'done', progress: 100, result: { skipped: true, output_path: 'x.txt' } }),
    )
    renderJobView()

    expect(await screen.findByText(/already existed, so it was not regenerated/)).toBeInTheDocument()
  })

  it('surfaces a diarization downgrade on a done job', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'done', progress: 100, result: { diarized: false, output_path: 'x.txt' } }),
    )
    renderJobView()

    expect(await screen.findByText(/diarization was requested but unavailable/i)).toBeInTheDocument()
  })

  it('offers Retry on a failed transcribe job and carries its params to the transcribe form', async () => {
    const params = { path: 'podcast/ep1.mp3', model: 'medium', language: 'UK', diarize: false, num_speakers: null }
    vi.mocked(getJob).mockResolvedValue(makeJob({ status: 'error', error: 'boom', params }))
    renderJobView()

    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(await screen.findByText(/transcribe page/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp('podcast/ep1\\.mp3'))).toBeInTheDocument()
  })

  it('does not offer Retry on a running transcribe job or a failed download job', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob())
    const { unmount } = renderJobView()
    expect(await screen.findByText('running')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    unmount()
    resetEventsForTests()

    vi.mocked(getJob).mockResolvedValue(makeJob({ kind: 'download', status: 'error', error: 'boom' }))
    renderJobView()
    expect(await screen.findByText('error')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('renders a determinate bar on a done job even with stale mid-stage progress', async () => {
    // Rows written before the worker emitted final progress keep
    // progress=0, stage="aligning" — the view must still show a full bar.
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'done', progress: 0, stage: 'aligning', result: { output_path: 'podcast/ep1.mp3.txt' } }),
    )
    renderJobView()

    expect(await screen.findByText('done')).toBeInTheDocument()
    expect(screen.getByTestId('progress-bar-fill')).toBeInTheDocument()
    expect(screen.queryByTestId('progress-bar-indeterminate')).not.toBeInTheDocument()
  })

  it('stops animating on error and cancelled jobs stuck in an unmetered stage', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob({ status: 'error', error: 'boom', progress: 0, stage: 'aligning' }))
    const { unmount } = renderJobView()
    expect(await screen.findByText('error')).toBeInTheDocument()
    expect(screen.queryByTestId('progress-bar-indeterminate')).not.toBeInTheDocument()
    unmount()
    resetEventsForTests()

    vi.mocked(getJob).mockResolvedValue(makeJob({ status: 'cancelled', progress: 0, stage: 'diarizing' }))
    renderJobView()
    expect(await screen.findByText('cancelled')).toBeInTheDocument()
    expect(screen.queryByTestId('progress-bar-indeterminate')).not.toBeInTheDocument()
  })

  it('offers View transcript on a done transcribe job and deep-links to the file', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'done', progress: 100, result: { output_path: 'podcast/ep1.mp3.txt' } }),
    )
    renderJobView()

    await userEvent.click(await screen.findByRole('button', { name: 'View transcript' }))

    expect(await screen.findByText(/files page/)).toBeInTheDocument()
    expect(screen.getByText(/\?path=podcast%2Fep1\.mp3/)).toBeInTheDocument()
  })

  it('offers View transcript on a skipped job — the transcript already exists', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'done', progress: 100, result: { skipped: true, output_path: 'podcast/ep1.mp3.txt' } }),
    )
    renderJobView()

    expect(await screen.findByRole('button', { name: 'View transcript' })).toBeInTheDocument()
  })

  it('does not offer View transcript on running, download, or result-less jobs', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob())
    let view = renderJobView()
    expect(await screen.findByText('running')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'View transcript' })).not.toBeInTheDocument()
    view.unmount()
    resetEventsForTests()

    vi.mocked(getJob).mockResolvedValue(
      makeJob({ kind: 'download', status: 'done', progress: 100, result: { output_path: 'x.mp3' } }),
    )
    view = renderJobView()
    expect(await screen.findByText('done')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'View transcript' })).not.toBeInTheDocument()
    view.unmount()
    resetEventsForTests()

    vi.mocked(getJob).mockResolvedValue(makeJob({ status: 'done', progress: 100, result: null }))
    renderJobView()
    expect(await screen.findByText('done')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'View transcript' })).not.toBeInTheDocument()
  })

  it('shows a disconnected hint and refetches the job on reconnect', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob())
    renderJobView()
    expect(await screen.findByText('running')).toBeInTheDocument()

    const source = FakeEventSource.instances[0]
    act(() => {
      source.onerror?.()
    })
    expect(screen.getByText(/Live updates disconnected/)).toBeInTheDocument()

    // The job finished while the stream was down; reconnect must refetch.
    vi.mocked(getJob).mockResolvedValue(makeJob({ status: 'done', progress: 100 }))
    act(() => {
      source.onopen?.()
    })
    await waitFor(() => expect(screen.getByText('done')).toBeInTheDocument())
    expect(screen.queryByText(/Live updates disconnected/)).not.toBeInTheDocument()
  })
})
