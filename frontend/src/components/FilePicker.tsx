import type { TreeNode } from '../lib/types'
import { Card } from './ui/Card'
import { ScrollArea } from './ui/ScrollArea'
import { Badge } from './ui/Badge'
import { FileTree } from './FileTree'

interface FilePickerProps {
  nodes: TreeNode[]
  selectedPath?: string
  onSelect: (node: TreeNode) => void
}

// A files tree tuned for picking a source to transcribe: untranscribed
// files are the common case (that's what you're here to do) so they render
// at full opacity, while already-transcribed files are dimmed but remain
// selectable — but submitting one is a no-op: the backend keeps the existing
// transcript and reports the job result as "skipped". Reuses
// FileTree's recursive renderer (open/close state, indent, dir/file
// branching) via its fileClassName/renderFileBadge hooks instead of
// forking the tree.
export function FilePicker({ nodes, selectedPath, onSelect }: FilePickerProps) {
  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-medium text-zinc-100">Pick a file</h2>
      </div>
      <ScrollArea className="min-h-0 flex-1 py-2">
        <FileTree
          nodes={nodes}
          onSelectFile={onSelect}
          selectedPath={selectedPath}
          fileClassName={(node) => (node.transcribed ? 'text-zinc-500' : 'text-zinc-200')}
          renderFileBadge={(node) =>
            node.transcribed ? (
              <Badge data-testid="transcribed-badge" className="shrink-0">
                already transcribed
              </Badge>
            ) : null
          }
        />
        {nodes.length === 0 && <p className="px-4 text-sm text-zinc-500">No audio files yet.</p>}
      </ScrollArea>
      {selectedPath && (
        <div className="shrink-0 border-t border-zinc-800 px-4 py-2">
          <p className="truncate text-xs text-zinc-400">
            Selected: <span className="text-zinc-200">{selectedPath}</span>
          </p>
        </div>
      )}
    </Card>
  )
}
