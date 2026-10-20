import { useParams } from 'react-router-dom'

export function JobView() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="flex h-full items-center justify-center p-4">
      <p className="text-sm text-zinc-500">Job {id} — coming soon.</p>
    </div>
  )
}
