import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { resetEventsForTests, useEvents, useEventsConnected } from './useEvents'
import type { AppEvent } from './types'

type Handler = (event: MessageEvent) => void

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  private handlers = new Map<string, Handler[]>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, handler: Handler) {
    const list = this.handlers.get(type) ?? []
    list.push(handler)
    this.handlers.set(type, list)
  }

  close() {
    this.closed = true
  }

  emit(type: string, data: string) {
    for (const handler of this.handlers.get(type) ?? []) {
      handler({ data } as MessageEvent)
    }
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  resetEventsForTests()
  vi.unstubAllGlobals()
})

function lastSource(): FakeEventSource {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1]
}

describe('useEvents', () => {
  it('shares one EventSource across subscribers and dispatches parsed events', () => {
    const seen: AppEvent[] = []
    const seenB: AppEvent[] = []
    renderHook(() => useEvents((e) => seen.push(e)))
    renderHook(() => useEvents((e) => seenB.push(e)))

    expect(FakeEventSource.instances).toHaveLength(1)

    act(() => {
      lastSource().emit('job_status', JSON.stringify({ type: 'job_status', job_id: 1, status: 'done' }))
    })
    expect(seen).toEqual([{ type: 'job_status', job_id: 1, status: 'done' }])
    expect(seenB).toEqual(seen)
  })

  it('removes the listener on unmount', () => {
    const seen: AppEvent[] = []
    const { unmount } = renderHook(() => useEvents((e) => seen.push(e)))
    unmount()

    act(() => {
      lastSource().emit('job_status', JSON.stringify({ type: 'job_status', job_id: 1 }))
    })
    expect(seen).toHaveLength(0)
  })

  it('drops malformed payloads and keeps dispatching past a throwing listener', () => {
    const seen: AppEvent[] = []
    renderHook(() =>
      useEvents(() => {
        throw new Error('bad subscriber')
      }),
    )
    renderHook(() => useEvents((e) => seen.push(e)))

    act(() => {
      lastSource().emit('job_log', 'not-json{')
      lastSource().emit('job_log', JSON.stringify({ type: 'job_log', line: 'hi' }))
    })
    // malformed payload dropped, good payload still reached the second listener
    expect(seen).toEqual([{ type: 'job_log', line: 'hi' }])
  })

  it('fires onReconnect only when the connection reopens after an error', () => {
    const reconnects: number[] = []
    renderHook(() => useEvents(() => {}, () => reconnects.push(1)))

    act(() => {
      lastSource().onopen?.()
    })
    expect(reconnects).toHaveLength(0) // initial open is not a reconnect

    act(() => {
      lastSource().onerror?.()
      lastSource().onopen?.()
    })
    expect(reconnects).toHaveLength(1)
  })
})

describe('useEventsConnected', () => {
  it('tracks connection state through error and reopen', () => {
    const { result } = renderHook(() => useEventsConnected())
    expect(result.current).toBe(true)

    act(() => {
      lastSource().onerror?.()
    })
    expect(result.current).toBe(false)

    act(() => {
      lastSource().onopen?.()
    })
    expect(result.current).toBe(true)
  })
})
