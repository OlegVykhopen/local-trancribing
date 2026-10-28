import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { deleteTranscript, getTranscript, getTranscriptsTree } from '../lib/api'
import type { TreeNode } from '../lib/types'
import { FileTree } from '../components/FileTree'
import { TranscriptViewer } from '../components/TranscriptViewer'
import { Card } from '../components/ui/Card'
import { ScrollArea } from '../components/ui/ScrollArea'

function findFile(nodes: TreeNode[], path: string): TreeNode | null {
  for (const node of nodes) {
    if (node.type === 'file' && node.path === path) return node
    if (node.children) {
      const found = findFile(node.children, path)
      if (found) return found
    }
  }
  return null
}

// Browses the transcripts/ folder directly (not the audio tree), so a
// transcript stays reachable after its source audio is deleted.
export function TranscriptsView() {
  const [tree, setTree] = useState<TreeNode[]>([])
  const [treeError, setTreeError] = useState<string | null>(null)
  const [treeLoading, setTreeLoading] = useState(true)

  const [selected, setSelected] = useState<TreeNode | null>(null)
  const [content, setContent] = useState<string | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)

  const [searchParams, setSearchParams] = useSearchParams()
  const pendingPath = searchParams.get('path')

  const loadTree = useCallback(async () => {
    const data = await getTranscriptsTree()
    setTree(data)
    return data
  }, [])

  // Deep link: /transcripts?path=<transcript-rel-path> selects that file once
  // the tree is loaded, then the param is consumed so it doesn't keep
  // tracking (or fighting) manual selection.
  useEffect(() => {
    if (treeLoading || !pendingPath) return
    const node = findFile(tree, pendingPath)
    if (node) handleSelectFile(node)
    setSearchParams({}, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeLoading, pendingPath])

  useEffect(() => {
    let cancelled = false
    loadTree()
      .catch((err: unknown) => {
        if (!cancelled) setTreeError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadTree])

  function handleSelectFile(node: TreeNode) {
    setSelected(node)
    setContent(null)
    setTranscriptError(null)
    setTranscriptLoading(true)
    getTranscript(node.path)
      .then((text) => setContent(text))
      .catch((err: unknown) => setTranscriptError(err instanceof Error ? err.message : String(err)))
      .finally(() => setTranscriptLoading(false))
  }

  async function handleDelete(node: TreeNode) {
    await deleteTranscript(node.path)
    setSelected(null)
    setContent(null)
    await loadTree()
  }

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <Card className="flex w-80 shrink-0 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
          <h2 className="text-sm font-medium text-zinc-100">Transcripts</h2>
        </div>
        <ScrollArea className="min-h-0 flex-1 py-2">
          {treeLoading && <p className="px-4 text-sm text-zinc-500">Loading…</p>}
          {treeError && <p className="px-4 text-sm text-red-400">{treeError}</p>}
          {!treeLoading && !treeError && (
            <>
              <FileTree nodes={tree} onSelectFile={handleSelectFile} selectedPath={selected?.path} />
              {tree.length === 0 && <p className="px-4 text-sm text-zinc-500">No transcripts yet.</p>}
            </>
          )}
        </ScrollArea>
      </Card>
      <Card className="min-w-0 flex-1 overflow-hidden">
        <TranscriptViewer
          node={selected}
          content={content}
          loading={transcriptLoading}
          error={transcriptError}
          onDelete={handleDelete}
        />
      </Card>
    </div>
  )
}
