import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { JobCard } from './JobCard'
import type { Job } from '../lib/types'

function makeJob(overrides: Partial<Job>): Job {
  return {
    id: 1,
    kind: 'download',
    status: 'queued',
    params: { url: 'https://youtu.be/abc123', category: 'podcast', format: 'audio' },
    category: 'podcast',
    progress: 0,
    stage: null,
    result: null,
    error: null,
    created_at: '2026-10-20T00:00:00',
    started_at: null,
    finished_at: null,
    ...overrides,
  }
}

function renderJobCard(job: Job) {
  return render(
    <MemoryRouter>
      <JobCard job={job} />
    </MemoryRouter>,
  )
}

describe('JobCard', () => {
  it('renders a done job with title from params, status badge text, and progress 100', () => {
    const job = makeJob({ status: 'done', progress: 100 })
    renderJobCard(job)

    expect(screen.getByText('https://youtu.be/abc123')).toBeInTheDocument()
    expect(screen.getByText('done')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('shows "cancelled" for a cancelled job', () => {
    const job = makeJob({ status: 'cancelled', progress: 40 })
    renderJobCard(job)

    expect(screen.getByText('cancelled')).toBeInTheDocument()
  })
})
