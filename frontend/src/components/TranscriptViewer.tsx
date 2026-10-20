import { motion } from 'motion/react'
import { ScrollArea } from './ui/ScrollArea'
import type { TreeNode } from '../lib/types'

interface TranscriptViewerProps {
  node: TreeNode | null
  content: string | null
  loading: boolean
  error: string | null
}

export function TranscriptViewer({ node, content, loading, error }: TranscriptViewerProps) {
  if (!node) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-500">
        Select a transcribed file to view its transcript.
      </div>
    )
  }

  return (
    <motion.div
      key={node.path}
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="flex h-full flex-col overflow-hidden"
    >
      <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h2 className="truncate text-sm font-medium text-zinc-100">{node.name}</h2>
        <p className="truncate text-xs text-zinc-500">{node.path}</p>
      </div>
      <ScrollArea className="min-h-0 flex-1 px-4 py-3">
        {loading && <p className="text-sm text-zinc-500">Loading transcript…</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}
        {!loading && !error && (
          <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-zinc-200">
            {content}
          </pre>
        )}
      </ScrollArea>
    </motion.div>
  )
}
