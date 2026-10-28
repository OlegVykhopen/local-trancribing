import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Trash2, Upload } from 'lucide-react'
import type { TreeNode } from '../lib/types'
import { Card } from './ui/Card'
import { ScrollArea } from './ui/ScrollArea'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Select } from './ui/Select'
import { FileTree } from './FileTree'

interface FilePickerProps {
  nodes: TreeNode[]
  selectedPath?: string
  onSelect: (node: TreeNode) => void
  categories: string[]
  /** Comma-separated extension list for the file dialog, e.g. ".m4a,.mp3". */
  accept: string
  /** Copies the file into audio_sources[/category]; rejects with the message to display. */
  onUpload: (file: File, category: string) => Promise<void>
  /** Deletes the source audio file; rejects with the message to display. */
  onDelete: (node: TreeNode) => Promise<void>
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

// A files tree tuned for picking a source to transcribe: untranscribed
// files are the common case (that's what you're here to do) so they render
// at full opacity, while already-transcribed files are dimmed but remain
// selectable — but submitting one is a no-op: the backend keeps the existing
// transcript and reports the job result as "skipped". Reuses
// FileTree's recursive renderer (open/close state, indent, dir/file
// branching) via its fileClassName/renderFileBadge hooks instead of
// forking the tree. A transcribed file's badge links to its transcript on
// the Transcripts tab instead of selecting the file.
//
// Also owns the upload row (header) and delete-source confirm (footer) UI
// state; the API calls and tree refresh belong to the parent.
export function FilePicker({ nodes, selectedPath, onSelect, categories, accept, onUpload, onDelete }: FilePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [category, setCategory] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // A new selection cancels any pending confirm for the previous one.
  useEffect(() => {
    setConfirmingDelete(false)
    setDeleteError(null)
  }, [selectedPath])

  function handleFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null
    e.target.value = '' // allow re-choosing the same file after cancel
    setPendingFile(file)
    setUploadError(null)
  }

  function cancelUpload() {
    setPendingFile(null)
    setUploadError(null)
  }

  async function handleUpload() {
    if (!pendingFile) return
    setUploading(true)
    setUploadError(null)
    try {
      await onUpload(pendingFile, category)
      setPendingFile(null)
    } catch (err: unknown) {
      setUploadError(errorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  async function handleConfirmDelete() {
    const node = findSelected(nodes, selectedPath)
    if (!node) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDelete(node)
    } catch (err: unknown) {
      setDeleteError(errorMessage(err))
    } finally {
      setDeleting(false)
      setConfirmingDelete(false)
    }
  }

  const selectedName = selectedPath?.split('/').pop()

  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-zinc-800 px-4 py-2">
        <h2 className="text-sm font-medium text-zinc-100">Pick a file</h2>
        <IconButton label="Upload audio file" onClick={() => inputRef.current?.click()} disabled={uploading}>
          <Upload size={16} />
        </IconButton>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          data-testid="upload-input"
          className="hidden"
          onChange={handleFileChosen}
        />
      </div>
      {pendingFile && (
        <div className="flex shrink-0 flex-col gap-2 border-b border-zinc-800 bg-zinc-900/60 px-4 py-3">
          <p className="truncate text-xs text-zinc-300" title={pendingFile.name}>
            {pendingFile.name}
          </p>
          <div className="flex items-center gap-2">
            <Select
              aria-label="Category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              disabled={uploading}
              className="min-w-0 flex-1 py-1 text-xs"
            >
              <option value="">(none)</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
            <Button className="px-2.5 py-1 text-xs" onClick={handleUpload} disabled={uploading}>
              {uploading ? 'Uploading…' : 'Upload'}
            </Button>
            <Button variant="outline" className="px-2.5 py-1 text-xs" onClick={cancelUpload} disabled={uploading}>
              Cancel
            </Button>
          </div>
          {uploadError && <p className="text-xs text-red-400">{uploadError}</p>}
        </div>
      )}
      <ScrollArea className="min-h-0 flex-1 py-2">
        <FileTree
          nodes={nodes}
          onSelectFile={onSelect}
          selectedPath={selectedPath}
          fileClassName={(node) => (node.transcribed ? 'text-zinc-500' : 'text-zinc-200')}
          renderFileBadge={(node) =>
            node.transcribed ? (
              <Link
                to={`/transcripts?path=${encodeURIComponent(node.path + '.txt')}`}
                data-testid="transcribed-badge"
                title="Open transcript"
                className="shrink-0"
              >
                <Badge className="hover:underline">already transcribed</Badge>
              </Link>
            ) : null
          }
        />
        {nodes.length === 0 && <p className="px-4 text-sm text-zinc-500">No audio files yet.</p>}
      </ScrollArea>
      {selectedPath && (
        <div className="shrink-0 border-t border-zinc-800 px-4 py-2">
          <div className="flex items-center justify-between gap-2">
            {confirmingDelete ? (
              <>
                <p className="truncate text-xs text-zinc-300">Delete {selectedName}?</p>
                <div className="flex shrink-0 items-center gap-1">
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
                    onClick={() => setConfirmingDelete(false)}
                    disabled={deleting}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="truncate text-xs text-zinc-400">
                  Selected: <span className="text-zinc-200">{selectedPath}</span>
                </p>
                <IconButton label="Delete source file" variant="danger" onClick={() => setConfirmingDelete(true)}>
                  <Trash2 size={16} />
                </IconButton>
              </>
            )}
          </div>
          {deleteError && <p className="pt-1 text-xs text-red-400">{deleteError}</p>}
        </div>
      )}
    </Card>
  )
}

function findSelected(nodes: TreeNode[], path?: string): TreeNode | null {
  if (!path) return null
  for (const node of nodes) {
    if (node.type === 'file' && node.path === path) return node
    const found = node.children ? findSelected(node.children, path) : null
    if (found) return found
  }
  return null
}
