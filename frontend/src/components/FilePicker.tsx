import { useState } from 'react'
import type { TreeNode } from '../lib/types'
import { Card } from './ui/Card'
import { ScrollArea } from './ui/ScrollArea'
import { Badge } from './ui/Badge'
import { cn } from '../lib/cn'

interface FilePickerProps {
  nodes: TreeNode[]
  selectedPath?: string
  onSelect: (node: TreeNode) => void
}

// A files tree tuned for picking a source to transcribe: untranscribed
// files are the common case (that's what you're here to do) so they render
// at full opacity, while already-transcribed files are dimmed but remain
// selectable — re-transcribing one is a valid (if redundant) choice that
// the backend already handles by reporting the job as "skipped".
export function FilePicker({ nodes, selectedPath, onSelect }: FilePickerProps) {
  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-medium text-zinc-100">Pick a file</h2>
      </div>
      <ScrollArea className="min-h-0 flex-1 py-2">
        <PickerTree nodes={nodes} selectedPath={selectedPath} onSelect={onSelect} />
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

function PickerTree({ nodes, selectedPath, onSelect, depth = 0 }: FilePickerProps & { depth?: number }) {
  return (
    <ul className="select-none text-sm">
      {nodes.map((node) => (
        <PickerRow key={node.path} node={node} selectedPath={selectedPath} onSelect={onSelect} depth={depth} />
      ))}
    </ul>
  )
}

function PickerRow({
  node,
  selectedPath,
  onSelect,
  depth,
}: {
  node: TreeNode
  selectedPath?: string
  onSelect: (node: TreeNode) => void
  depth: number
}) {
  const [open, setOpen] = useState(false)
  const indent = { paddingLeft: `${depth * 16 + 8}px` }

  if (node.type === 'dir') {
    return (
      <li>
        <button
          type="button"
          data-testid="picker-dir-row"
          onClick={() => setOpen((v) => !v)}
          style={indent}
          className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-zinc-300 hover:bg-zinc-800"
        >
          <span className={cn('inline-block transition-transform', open && 'rotate-90')}>▸</span>
          <span className="font-medium">{node.name}</span>
        </button>
        {open && node.children && node.children.length > 0 && (
          <PickerTree nodes={node.children} selectedPath={selectedPath} onSelect={onSelect} depth={depth + 1} />
        )}
      </li>
    )
  }

  const isSelected = selectedPath === node.path

  return (
    <li>
      <button
        type="button"
        data-testid="picker-file-row"
        onClick={() => onSelect(node)}
        style={indent}
        className={cn(
          'flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left hover:bg-zinc-800',
          node.transcribed ? 'text-zinc-500' : 'text-zinc-200',
          isSelected && 'bg-indigo-500/15 text-indigo-300',
        )}
      >
        <span className="truncate">{node.name}</span>
        {node.transcribed && (
          <Badge data-testid="transcribed-badge" className="shrink-0">
            already transcribed
          </Badge>
        )}
      </button>
    </li>
  )
}
