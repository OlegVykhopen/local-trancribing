import { useEffect } from 'react'
import type { AppEvent } from './types'

// A single shared EventSource for the whole app: every component calling
// useEvents() subscribes to the same underlying connection instead of each
// opening its own /api/events stream. Browsers cap concurrent EventSource
// connections per origin, and SSE reconnects are native to EventSource, so
// sharing one instance here keeps that reconnect behavior intact for every
// subscriber.
const EVENT_TYPES: AppEvent['type'][] = ['job_status', 'job_progress', 'job_log', 'queue']

type Listener = (event: AppEvent) => void

let source: EventSource | null = null
const listeners = new Set<Listener>()

function ensureSource(): EventSource {
  if (source) return source

  source = new EventSource('/api/events')
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (raw: MessageEvent) => {
      let event: AppEvent
      try {
        event = JSON.parse(raw.data) as AppEvent
      } catch {
        return
      }
      for (const listener of listeners) listener(event)
    })
  }
  return source
}

export function useEvents(onEvent: (event: AppEvent) => void): void {
  useEffect(() => {
    ensureSource()
    listeners.add(onEvent)
    return () => {
      listeners.delete(onEvent)
    }
  }, [onEvent])
}
