export interface TreeNode {
  name: string
  path: string
  type: 'dir' | 'file'
  transcribed?: boolean
  children?: TreeNode[]
}

export interface Job {
  id: number
  kind: 'download' | 'transcribe' | 'pipeline'
  status: string
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

export interface Meta {
  models: string[]
  default_model: string
  hf_token_present: boolean
}
