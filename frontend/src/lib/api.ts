import type { Meta, TreeNode } from './types'

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
