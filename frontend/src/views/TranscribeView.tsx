import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'motion/react'
import { createTranscribeJob, getFiles, getJobs, getMeta } from '../lib/api'
import { useEvents } from '../lib/useEvents'
import type { AppEvent, Job, Meta, TreeNode } from '../lib/types'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Card } from '../components/ui/Card'
import { ScrollArea } from '../components/ui/ScrollArea'
import { JobCard } from '../components/JobCard'
import { FilePicker } from '../components/FilePicker'

export function TranscribeView() {
  const navigate = useNavigate()

  const [tree, setTree] = useState<TreeNode[]>([])
  const [meta, setMeta] = useState<Meta | null>(null)

  const [selected, setSelected] = useState<TreeNode | null>(null)
  const [model, setModel] = useState('')
  const [language, setLanguage] = useState('')
  const [diarize, setDiarize] = useState(false)
  const [numSpeakers, setNumSpeakers] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const [jobs, setJobs] = useState<Job[]>([])

  useEffect(() => {
    getFiles()
      .then(setTree)
      .catch(() => setTree([]))
    getMeta()
      .then((m) => {
        setMeta(m)
        setModel(m.default_model)
      })
      .catch(() => setMeta(null))
  }, [])

  const loadJobs = useCallback(() => {
    getJobs('transcribe')
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
    if (!selected) {
      setSubmitError('Pick a file to transcribe.')
      return
    }
    if (!model) {
      setSubmitError('Pick a model.')
      return
    }
    setSubmitting(true)
    try {
      const { job_id } = await createTranscribeJob({
        path: selected.path,
        model,
        language: language.trim() || undefined,
        diarize,
        num_speakers: diarize && numSpeakers.trim() ? Number(numSpeakers) : undefined,
      })
      navigate(`/job/${job_id}`)
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const diarizeDisabled = !meta?.hf_token_present

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <FilePicker nodes={tree} selectedPath={selected?.path} onSelect={setSelected} />

      <Card className="flex w-96 shrink-0 flex-col gap-4 p-4">
        <h2 className="text-sm font-medium text-zinc-100">Transcribe</h2>
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="model" className="text-xs font-medium text-zinc-400">
              Model
            </label>
            <Select id="model" value={model} onChange={(e) => setModel(e.target.value)}>
              {(meta?.models ?? []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="language" className="text-xs font-medium text-zinc-400">
              Language
            </label>
            <Input
              id="language"
              placeholder="auto"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-2 text-xs font-medium text-zinc-400">
              <input
                type="checkbox"
                checked={diarize}
                disabled={diarizeDisabled}
                onChange={(e) => setDiarize(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-zinc-700 bg-zinc-900 disabled:cursor-not-allowed"
              />
              Identify speakers (diarize)
            </label>
            {diarizeDisabled && (
              <p className="text-xs text-zinc-500">
                Set HF_TOKEN in .env to enable speaker diarization.
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="num-speakers" className="text-xs font-medium text-zinc-400">
              Number of speakers (optional)
            </label>
            <Input
              id="num-speakers"
              type="number"
              min={1}
              placeholder="auto"
              value={numSpeakers}
              disabled={!diarize}
              onChange={(e) => setNumSpeakers(e.target.value)}
            />
          </div>
          {submitError && <p className="text-xs text-red-400">{submitError}</p>}
          <Button type="submit" disabled={submitting}>
            {submitting ? 'Starting…' : 'Transcribe'}
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
                <div key={job.id} className="flex flex-col gap-1">
                  <JobCard job={job} />
                  {job.status === 'done' && (
                    <a
                      href="#/files"
                      className="self-end px-1 text-xs text-indigo-400 hover:text-indigo-300"
                    >
                      view transcript →
                    </a>
                  )}
                </div>
              ))}
            </AnimatePresence>
            {jobs.length === 0 && <p className="px-1 text-sm text-zinc-500">No transcriptions yet.</p>}
          </div>
        </ScrollArea>
      </Card>
    </div>
  )
}
