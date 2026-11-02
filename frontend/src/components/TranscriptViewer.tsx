import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Check, Copy, Trash2 } from 'lucide-react'
import { ScrollArea } from './ui/ScrollArea'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import type { TreeNode } from '../lib/types'

interface TranscriptViewerProps {
  node: TreeNode | null
  content: string | null
  loading: boolean
  error: string | null
  /** Deletes the transcript; rejects with the message to display. */
  onDelete: (node: TreeNode) => Promise<void>
}

const COPIED_MS = 1500

export function TranscriptViewer({ node, content, loading, error, onDelete }: TranscriptViewerProps) {
  const [copied, setCopied] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // Reset per-transcript UI state when the selection changes.
  useEffect(() => {
    setCopied(false)
    setConfirming(false)
    setActionError(null)
  }, [node?.path])

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), COPIED_MS)
    return () => clearTimeout(timer)
  }, [copied])

  if (!node) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-500">
        Select a transcript to view it.
      </div>
    )
  }

  async function handleCopy() {
    if (content == null) return
    setActionError(null)
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
    } catch {
      setActionError('Could not copy to clipboard.')
    }
  }

  async function handleConfirmDelete() {
    if (!node) return
    setDeleting(true)
    setActionError(null)
    try {
      await onDelete(node)
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  return (
    <motion.div
      key={node.path}
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="flex h-full flex-col overflow-hidden"
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium text-zinc-100">{node.name}</h2>
          {confirming ? (
            <p className="text-xs text-zinc-300">Delete this transcript?</p>
          ) : (
            <p className="truncate text-xs text-zinc-500">{node.path}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {confirming ? (
            <>
              <Button
                className="bg-red-600 px-2.5 py-1 text-xs hover:bg-red-500"
                onClick={handleConfirmDelete}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </Button>
              <Button
                variant="outline"
                className="px-2.5 py-1 text-xs"
                onClick={() => setConfirming(false)}
                disabled={deleting}
              >
                Cancel
              </Button>
            </>
          ) : (
            <>
              <IconButton
                label={copied ? 'Copied' : 'Copy transcript'}
                onClick={handleCopy}
                disabled={loading || content == null}
                className={copied ? 'text-emerald-400 hover:text-emerald-400' : undefined}
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
              </IconButton>
              <IconButton label="Delete transcript" variant="danger" onClick={() => setConfirming(true)}>
                <Trash2 size={16} />
              </IconButton>
            </>
          )}
        </div>
      </div>
      {actionError && <p className="shrink-0 px-4 pt-2 text-xs text-red-400">{actionError}</p>}
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
