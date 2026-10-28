import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createCategory,
  deleteSourceFile,
  deleteTranscript,
  getCategories,
  getFiles,
  getMeta,
  getTranscript,
  getTranscriptsTree,
  uploadFile,
} from './api'
import type { TreeNode } from './types'

function mockFetchOnce(body: unknown, init?: Partial<Response>) {
  const response = {
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    json: () =>
      (init?.status ?? 200) === 204 ? Promise.reject(new Error('no body on 204')) : Promise.resolve(body),
  } as Response
  const fetchMock = vi.fn().mockResolvedValue(response)
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

describe('api', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getFiles() hits /api/files and returns the tree array', async () => {
    const tree: TreeNode[] = [
      { name: 'therapy', path: 'therapy', type: 'dir', children: [] },
      { name: 'a.mp3', path: 'a.mp3', type: 'file', transcribed: true },
    ]
    const fetchMock = mockFetchOnce({ tree })

    const result = await getFiles()

    expect(fetchMock).toHaveBeenCalledWith('/api/files')
    expect(result).toEqual(tree)
  })

  it('getCategories() hits /api/categories and returns the categories array', async () => {
    const fetchMock = mockFetchOnce({ categories: ['therapy', 'podcast'] })

    const result = await getCategories()

    expect(fetchMock).toHaveBeenCalledWith('/api/categories')
    expect(result).toEqual(['therapy', 'podcast'])
  })

  it('createCategory() POSTs the name to /api/categories', async () => {
    const fetchMock = mockFetchOnce({ name: 'new-cat' }, { status: 201 })

    const result = await createCategory('new-cat')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/categories',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ name: 'new-cat' }),
      }),
    )
    expect(result).toEqual({ name: 'new-cat' })
  })

  it('getTranscript() hits /api/transcript with the path query param and returns content', async () => {
    const fetchMock = mockFetchOnce({ path: 'therapy/a.m4a.txt', content: 'hello world' })

    const result = await getTranscript('therapy/a.m4a.txt')

    expect(fetchMock).toHaveBeenCalledWith('/api/transcript?path=' + encodeURIComponent('therapy/a.m4a.txt'))
    expect(result).toBe('hello world')
  })

  it('getMeta() hits /api/meta and returns the meta object', async () => {
    const meta = { models: ['base', 'large-v3'], default_model: 'base', hf_token_present: true }
    const fetchMock = mockFetchOnce(meta)

    const result = await getMeta()

    expect(fetchMock).toHaveBeenCalledWith('/api/meta')
    expect(result).toEqual(meta)
  })

  it('throws when the response is not ok', async () => {
    mockFetchOnce({ detail: 'bad path' }, { ok: false, status: 400 })

    await expect(getTranscript('../etc/passwd')).rejects.toThrow()
  })

  it('getTranscriptsTree() hits /api/transcripts and returns the tree array', async () => {
    const fetchMock = mockFetchOnce({ tree: [] })

    expect(await getTranscriptsTree()).toEqual([])
    expect(fetchMock).toHaveBeenCalledWith('/api/transcripts')
  })

  it('uploadFile() posts multipart with file and category and no explicit headers', async () => {
    const fetchMock = mockFetchOnce({ path: 'therapy/x.mp3' }, { status: 201 })
    const file = new File(['x'], 'x.mp3', { type: 'audio/mpeg' })

    expect(await uploadFile(file, 'therapy')).toEqual({ path: 'therapy/x.mp3' })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/files/upload')
    expect(init.method).toBe('POST')
    expect((init.body as FormData).get('category')).toBe('therapy')
    expect((init.body as FormData).get('file')).toBe(file)
    expect(init.headers).toBeUndefined()
  })

  it('deleteSourceFile() and deleteTranscript() send DELETE and resolve on 204', async () => {
    let fetchMock = mockFetchOnce(undefined, { status: 204 })
    await expect(deleteSourceFile('a/b.mp3')).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith('/api/files?path=a%2Fb.mp3', { method: 'DELETE' })

    fetchMock = mockFetchOnce(undefined, { status: 204 })
    await expect(deleteTranscript('a/b.mp3.txt')).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith('/api/transcripts?path=a%2Fb.mp3.txt', { method: 'DELETE' })
  })
})
