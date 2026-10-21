import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { cancelJob, getJob, getJobLogs } from '../lib/api'
import { useEvents, useEventsConnected } from '../lib/useEvents'
import type { AppEvent, Job, JobStatus } from '../lib/types'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { ScrollArea } from '../components/ui/ScrollArea'
import { ProgressBar } from '../components/ProgressBar'

interface LogLine {
  ts: string
  line: string
}

const CANCELLABLE_STATUSES = new Set(['queued', 'running', 'cancelling'])

const STATUS_CLASSES: Record<string, string> = {
  queued: 'bg-zinc-500/15 text-zinc-300',
  running: 'bg-indigo-500/15 text-indigo-300',
  cancelling: 'bg-amber-500/15 text-amber-300',
  cancelled: 'bg-amber-500/15 text-amber-300',
  done: 'bg-emerald-500/15 text-emerald-400',
  error: 'bg-red-500/15 text-red-400',
}

export function JobView() {
  const { id } = useParams<{ id: string }>()
  const jobId = Number(id)

  const [job, setJob] = useState<Job | null>(null)
  const [logs, setLogs] = useState<LogLine[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const logEndRef = useRef<HTMLDivElement | null>(null)

  // Also used as the reconnect handler: SSE events missed while the stream
  // was down (including a terminal job_status) are gone for good, so the
  // only way back to truth is refetching.
  const refresh = useCallback(() => {
    if (!Number.isFinite(jobId)) return
    Promise.all([getJob(jobId), getJobLogs(jobId)])
      .then(([jobData, logData]) => {
        setJob(jobData)
        setLogs(logData)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : String(err))
      })
  }, [jobId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleEvent = useCallback(
    (event: AppEvent) => {
      if (event.job_id !== jobId) return

      if (event.type === 'job_status') {
        setJob((prev) =>
          prev
            ? {
                ...prev,
                status: event.status as JobStatus,
                error: 'error' in event ? ((event.error as string | null) ?? null) : prev.error,
                result: 'result' in event ? ((event.result as Record<string, unknown> | null) ?? null) : prev.result,
              }
            : prev,
        )
      } else if (event.type === 'job_progress') {
        setJob((prev) =>
          prev
            ? {
                ...prev,
                progress: Math.round(Number(event.percent) || 0),
                stage: String(event.stage),
              }
            : prev,
        )
      } else if (event.type === 'job_log') {
        setLogs((prev) => [...prev, { ts: new Date().toISOString(), line: String(event.line) }])
      }
    },
    [jobId],
  )
  useEvents(handleEvent, refresh)
  const connected = useEventsConnected()

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: 'end' })
  }, [logs])

  async function handleCancel() {
    setCancelling(true)
    setCancelError(null)
    try {
      const { status } = await cancelJob(jobId)
      setJob((prev) => (prev ? { ...prev, status } : prev))
    } catch (err: unknown) {
      setCancelError(`Cancel failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setCancelling(false)
    }
  }

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-sm text-red-400">{loadError}</p>
      </div>
    )
  }

  if (!job) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-sm text-zinc-500">Loading…</p>
      </div>
    )
  }

  const title = typeof job.params?.url === 'string' ? (job.params.url as string) : `Job #${job.id}`
  const canCancel = CANCELLABLE_STATUSES.has(job.status)

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4">
      <Card className="flex shrink-0 flex-col gap-3 p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-medium text-zinc-100">{title}</h2>
            <p className="text-xs text-zinc-500">{job.category || 'uncategorized'}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge className={STATUS_CLASSES[job.status] ?? STATUS_CLASSES.queued}>{job.status}</Badge>
            {canCancel && (
              <Button variant="outline" onClick={handleCancel} disabled={cancelling || job.status === 'cancelling'}>
                {job.status === 'cancelling' ? 'Cancelling…' : 'Cancel'}
              </Button>
            )}
          </div>
        </div>
        <ProgressBar percent={job.status === 'queued' ? null : job.progress} stage={job.stage ?? ''} />
        {job.error && <p className="text-xs text-red-400">{job.error}</p>}
        {cancelError && <p className="text-xs text-red-400">{cancelError}</p>}
        {!connected && (
          <p className="text-xs text-amber-400">Live updates disconnected — reconnecting…</p>
        )}
        {job.status === 'done' && job.result?.skipped === true && (
          <p className="text-xs text-amber-400">
            A transcript for this file already existed, so it was not regenerated. Delete the existing transcript to
            re-transcribe.
          </p>
        )}
        {job.status === 'done' && job.result?.diarized === false && (
          <p className="text-xs text-amber-400">
            Speaker diarization was requested but unavailable — the transcript has no speaker labels. See the log
            below for the cause.
          </p>
        )}
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
          <h3 className="text-sm font-medium text-zinc-100">Log</h3>
        </div>
        <ScrollArea className="min-h-0 flex-1 p-3 font-mono text-xs text-zinc-400">
          {logs.map((entry, i) => (
            <div key={i} className="whitespace-pre-wrap">
              {entry.line}
            </div>
          ))}
          <div ref={logEndRef} />
        </ScrollArea>
      </Card>
    </div>
  )
}
