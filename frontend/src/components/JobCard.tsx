import { motion } from 'motion/react'
import { Link } from 'react-router-dom'
import { Card } from './ui/Card'
import { Badge } from './ui/Badge'
import type { Job } from '../lib/types'
import { cn } from '../lib/cn'

const STATUS_CLASSES: Record<string, string> = {
  queued: 'bg-zinc-500/15 text-zinc-300',
  running: 'bg-indigo-500/15 text-indigo-300',
  cancelling: 'bg-amber-500/15 text-amber-300',
  cancelled: 'bg-amber-500/15 text-amber-300',
  done: 'bg-emerald-500/15 text-emerald-400',
  error: 'bg-red-500/15 text-red-400',
}

function jobTitle(job: Job): string {
  const url = job.params?.url
  if (typeof url === 'string' && url.length > 0) return url
  return `Job #${job.id}`
}

export function JobCard({ job }: { job: Job }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 300, damping: 28 }}
    >
      <Link to={`/job/${job.id}`}>
        <Card className="flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:border-indigo-600">
          <div className="min-w-0">
            <p className="truncate text-sm text-zinc-100">{jobTitle(job)}</p>
            <p className="text-xs text-zinc-500">{job.category || 'uncategorized'}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-xs text-zinc-400">{job.progress}%</span>
            <Badge className={cn(STATUS_CLASSES[job.status] ?? STATUS_CLASSES.queued)}>{job.status}</Badge>
          </div>
        </Card>
      </Link>
    </motion.div>
  )
}
