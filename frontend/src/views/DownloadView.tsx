import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'motion/react'
import { createDownloadJob, getCategories, getJobs } from '../lib/api'
import { useEvents } from '../lib/useEvents'
import type { AppEvent, Job } from '../lib/types'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Card } from '../components/ui/Card'
import { ScrollArea } from '../components/ui/ScrollArea'
import { JobCard } from '../components/JobCard'

export function DownloadView() {
  const navigate = useNavigate()

  const [url, setUrl] = useState('')
  const [category, setCategory] = useState('')
  const [categories, setCategories] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const [jobs, setJobs] = useState<Job[]>([])

  useEffect(() => {
    getCategories()
      .then(setCategories)
      .catch(() => setCategories([]))
  }, [])

  const loadJobs = useCallback(() => {
    getJobs('download')
      .then(setJobs)
      .catch(() => {
        // history list is best-effort; leave the previous list in place on failure
      })
  }, [])

  useEffect(() => {
    loadJobs()
  }, [loadJobs])

  const handleEvent = useCallback(
    (event: AppEvent) => {
      if (event.type === 'job_status' || event.type === 'job_progress') {
        const jobId = event.job_id as number
        setJobs((prev) =>
          prev.map((job) =>
            job.id === jobId
              ? {
                  ...job,
                  ...(event.type === 'job_status' ? { status: String(event.status) } : {}),
                  ...(event.type === 'job_progress'
                    ? { progress: Math.round(Number(event.percent) || 0), stage: String(event.stage) }
                    : {}),
                }
              : job,
          ),
        )
        if (event.type === 'job_status') loadJobs()
      }
    },
    [loadJobs],
  )
  useEvents(handleEvent)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitError(null)
    if (!url.trim()) {
      setSubmitError('URL is required.')
      return
    }
    setSubmitting(true)
    try {
      const { job_id } = await createDownloadJob({ url: url.trim(), category })
      navigate(`/job/${job_id}`)
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <Card className="flex w-96 shrink-0 flex-col gap-4 p-4">
        <h2 className="text-sm font-medium text-zinc-100">Download from YouTube</h2>
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="url" className="text-xs font-medium text-zinc-400">
              YouTube URL
            </label>
            <Input
              id="url"
              placeholder="https://www.youtube.com/watch?v=..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="category" className="text-xs font-medium text-zinc-400">
              Category
            </label>
            <Select id="category" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">(none)</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </div>
          {submitError && <p className="text-xs text-red-400">{submitError}</p>}
          <Button type="submit" disabled={submitting}>
            {submitting ? 'Starting…' : 'Download'}
          </Button>
        </form>
      </Card>

      <Card className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
          <h2 className="text-sm font-medium text-zinc-100">History</h2>
        </div>
        <ScrollArea className="min-h-0 flex-1 p-3">
          <div className="flex flex-col gap-2">
            <AnimatePresence initial={false}>
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} />
              ))}
            </AnimatePresence>
            {jobs.length === 0 && <p className="px-1 text-sm text-zinc-500">No downloads yet.</p>}
          </div>
        </ScrollArea>
      </Card>
    </div>
  )
}
