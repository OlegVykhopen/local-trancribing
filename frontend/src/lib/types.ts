export interface TreeNode {
  name: string
  path: string
  type: 'dir' | 'file'
  transcribed?: boolean
  children?: TreeNode[]
}

// Mirrors JobStatus in app/schemas.py.
export type JobStatus = 'queued' | 'running' | 'cancelling' | 'cancelled' | 'done' | 'error'

export interface Job {
  id: number
  kind: 'download' | 'transcribe' | 'pipeline'
  status: JobStatus
  params: Record<string, unknown>
  category: string | null
  progress: number
  stage: string | null
  result: Record<string, unknown> | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AppEvent {
  type: 'job_status' | 'job_progress' | 'job_log' | 'queue'
  [k: string]: unknown
}

export interface LanguageOption {
  code: string
  name: string
}

export interface Meta {
  models: string[]
  default_model: string
  hf_token_present: boolean
  languages: LanguageOption[]
}
