import { useState } from 'react'
import type { TreeNode } from '../lib/types'
import { Badge } from './ui/Badge'
import { cn } from '../lib/cn'

interface FileTreeProps {
  nodes: TreeNode[]
  onSelectFile: (node: TreeNode) => void
  selectedPath?: string
  depth?: number
}

export function FileTree({ nodes, onSelectFile, selectedPath, depth = 0 }: FileTreeProps) {
  return (
    <ul className="select-none text-sm">
      {nodes.map((node) => (
        <TreeRow
          key={node.path}
          node={node}
          onSelectFile={onSelectFile}
          selectedPath={selectedPath}
          depth={depth}
        />
      ))}
    </ul>
  )
}

interface TreeRowProps {
  node: TreeNode
  onSelectFile: (node: TreeNode) => void
  selectedPath?: string
  depth: number
}

function TreeRow({ node, onSelectFile, selectedPath, depth }: TreeRowProps) {
  const [open, setOpen] = useState(false)
  const indent = { paddingLeft: `${depth * 16 + 8}px` }

  if (node.type === 'dir') {
    return (
      <li>
        <button
          type="button"
          data-testid="dir-row"
          onClick={() => setOpen((v) => !v)}
          style={indent}
          className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-zinc-300 hover:bg-zinc-800"
        >
          <span className={cn('inline-block transition-transform', open && 'rotate-90')}>▸</span>
          <span className="font-medium">{node.name}</span>
        </button>
        {open && node.children && node.children.length > 0 && (
          <FileTree nodes={node.children} onSelectFile={onSelectFile} selectedPath={selectedPath} depth={depth + 1} />
        )}
      </li>
    )
  }

  const isSelected = selectedPath === node.path

  return (
    <li>
      <button
        type="button"
        data-testid="file-row"
        onClick={() => onSelectFile(node)}
        style={indent}
        className={cn(
          'flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-zinc-400 hover:bg-zinc-800',
          isSelected && 'bg-indigo-500/15 text-indigo-300',
        )}
      >
        <span className="truncate">{node.name}</span>
        {node.transcribed && (
          <Badge data-testid="transcribed-badge" className="shrink-0">
            ✓
          </Badge>
        )}
      </button>
    </li>
  )
}
