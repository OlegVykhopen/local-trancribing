import { useEffect, useRef, useState } from 'react'
import type { AppEvent } from './types'

// A single shared EventSource for the whole app: every component calling
// useEvents() subscribes to the same underlying connection instead of each
// opening its own /api/events stream. Browsers cap concurrent EventSource
// connections per origin, and SSE reconnects are native to EventSource, so
// sharing one instance here keeps that reconnect behavior intact for every
// subscriber.
//
// Events published by the server while the connection is down are lost (the
// server keeps no replay buffer), so subscribers that mirror server state
// should pass onReconnect and refetch it there.
const EVENT_TYPES: AppEvent['type'][] = ['job_status', 'job_progress', 'job_log', 'queue']

type Listener = (event: AppEvent) => void

let source: EventSource | null = null
let isConnected = true
const listeners = new Set<Listener>()
const connectionListeners = new Set<(connected: boolean) => void>()
const reconnectListeners = new Set<() => void>()

function ensureSource(): EventSource {
  if (source) return source

  source = new EventSource('/api/events')
  source.onopen = () => {
    const wasDown = !isConnected
    isConnected = true
    for (const notify of connectionListeners) notify(true)
    if (wasDown) {
      for (const notify of reconnectListeners) notify()
    }
  }
  source.onerror = () => {
    isConnected = false
    for (const notify of connectionListeners) notify(false)
  }
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (raw: MessageEvent) => {
      let event: AppEvent
      try {
        event = JSON.parse(raw.data) as AppEvent
      } catch {
        console.warn('useEvents: dropping malformed SSE payload', raw.data)
        return
      }
      for (const listener of listeners) {
        // One throwing subscriber must not starve the rest.
        try {
          listener(event)
        } catch (err) {
          console.error('useEvents: listener threw', err)
        }
      }
    })
  }
  return source
}

export function useEvents(onEvent: (event: AppEvent) => void, onReconnect?: () => void): void {
  const reconnectRef = useRef(onReconnect)
  reconnectRef.current = onReconnect

  useEffect(() => {
    ensureSource()
    listeners.add(onEvent)
    const reconnect = () => reconnectRef.current?.()
    reconnectListeners.add(reconnect)
    return () => {
      listeners.delete(onEvent)
      reconnectListeners.delete(reconnect)
    }
  }, [onEvent])
}

// Live connection state of the shared stream, for "updates paused" UI hints.
export function useEventsConnected(): boolean {
  const [connected, setConnected] = useState(isConnected)
  useEffect(() => {
    ensureSource()
    setConnected(isConnected)
    connectionListeners.add(setConnected)
    return () => {
      connectionListeners.delete(setConnected)
    }
  }, [])
  return connected
}

// Test-only: drop the shared source and all module state between tests.
export function resetEventsForTests(): void {
  source?.close()
  source = null
  isConnected = true
  listeners.clear()
  connectionListeners.clear()
  reconnectListeners.clear()
}
