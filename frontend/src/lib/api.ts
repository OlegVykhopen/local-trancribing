import type { Job, JobStatus, Meta, TreeNode } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = init ? await fetch(path, init) : await fetch(path)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      // response body wasn't JSON; fall back to statusText
    }
    throw new Error(`${response.status} ${detail}`)
  }
  return response.json() as Promise<T>
}

export async function getFiles(): Promise<TreeNode[]> {
  const data = await request<{ tree: TreeNode[] }>('/api/files')
  return data.tree
}

export async function getCategories(): Promise<string[]> {
  const data = await request<{ categories: string[] }>('/api/categories')
  return data.categories
}

export async function createCategory(name: string): Promise<{ name: string }> {
  return request<{ name: string }>('/api/categories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function getTranscript(path: string): Promise<string> {
  const data = await request<{ path: string; content: string }>(
    '/api/transcript?path=' + encodeURIComponent(path),
  )
  return data.content
}

export async function getMeta(): Promise<Meta> {
  return request<Meta>('/api/meta')
}

export async function createDownloadJob(params: { url: string; category: string }): Promise<{ job_id: number }> {
  return request<{ job_id: number }>('/api/jobs/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
}

export async function createTranscribeJob(params: {
  path: string
  model: string
  language?: string
  diarize: boolean
  num_speakers?: number
}): Promise<{ job_id: number }> {
  return request<{ job_id: number }>('/api/jobs/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
}

export async function getJobs(kind?: string): Promise<Job[]> {
  const path = kind ? `/api/jobs?kind=${encodeURIComponent(kind)}` : '/api/jobs'
  const data = await request<{ jobs: Job[] }>(path)
  return data.jobs
}

export async function getJob(id: number): Promise<Job> {
  return request<Job>(`/api/jobs/${id}`)
}

export async function getJobLogs(id: number): Promise<{ ts: string; line: string }[]> {
  const data = await request<{ logs: { ts: string; line: string }[] }>(`/api/jobs/${id}/logs`)
  return data.logs
}

// Rejects with 404 (unknown job) or 409 (job not cancellable) — the
// endpoint no longer returns a null status for those cases.
export async function cancelJob(id: number): Promise<{ status: JobStatus }> {
  return request<{ status: JobStatus }>(`/api/jobs/${id}/cancel`, { method: 'POST' })
}
