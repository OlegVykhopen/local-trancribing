import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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

function renderJobView() {
  return render(
    <MemoryRouter initialEntries={['/job/1']}>
      <Routes>
        <Route path="/job/:id" element={<JobView />} />
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
