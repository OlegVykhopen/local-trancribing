import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getFiles, getTranscript } from '../lib/api'
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

export function FilesView() {
  const [tree, setTree] = useState<TreeNode[]>([])
  const [treeError, setTreeError] = useState<string | null>(null)
  const [treeLoading, setTreeLoading] = useState(true)

  const [selected, setSelected] = useState<TreeNode | null>(null)
  const [content, setContent] = useState<string | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)

  const [searchParams, setSearchParams] = useSearchParams()
  const pendingPath = searchParams.get('path')

  // Deep link from the job view: /files?path=<audio-rel-path> selects that
  // file once the tree is loaded, then the param is consumed so it doesn't
  // keep tracking (or fighting) manual selection.
  useEffect(() => {
    if (treeLoading || !pendingPath) return
    const node = findFile(tree, pendingPath)
    if (node) handleSelectFile(node)
    setSearchParams({}, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeLoading, pendingPath])

  useEffect(() => {
    let cancelled = false
    getFiles()
      .then((data) => {
        if (!cancelled) setTree(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setTreeError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function handleSelectFile(node: TreeNode) {
    setSelected(node)
    setContent(null)
    setTranscriptError(null)

    if (!node.transcribed) {
      setTranscriptError('This file has not been transcribed yet.')
      return
    }

    setTranscriptLoading(true)
    getTranscript(`${node.path}.txt`)
      .then((text) => setContent(text))
      .catch((err: unknown) => setTranscriptError(err instanceof Error ? err.message : String(err)))
      .finally(() => setTranscriptLoading(false))
  }

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <Card className="flex w-80 shrink-0 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
          <h2 className="text-sm font-medium text-zinc-100">Files</h2>
        </div>
        <ScrollArea className="min-h-0 flex-1 py-2">
          {treeLoading && <p className="px-4 text-sm text-zinc-500">Loading…</p>}
          {treeError && <p className="px-4 text-sm text-red-400">{treeError}</p>}
          {!treeLoading && !treeError && (
            <FileTree nodes={tree} onSelectFile={handleSelectFile} selectedPath={selected?.path} />
          )}
        </ScrollArea>
      </Card>
      <Card className="min-w-0 flex-1 overflow-hidden">
        <TranscriptViewer node={selected} content={content} loading={transcriptLoading} error={transcriptError} />
      </Card>
    </div>
  )
}
