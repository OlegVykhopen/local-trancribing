"""Thread-safe event bus bridging a worker thread to asyncio SSE subscribers.

A background worker thread calls `publish(event)`. Async SSE handlers running
on the FastAPI event loop call `subscribe()` to get a queue of events and
`unsubscribe()` when the client disconnects. `publish` must never block or
slow down the worker thread, even if a subscriber's queue is full (e.g. a
stalled browser) — on overflow the oldest queued event is dropped in favor
of the new one.
"""

import asyncio
import threading

QUEUE_MAXSIZE = 200


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        loop = self._loop
        if loop is None:
            return

        with self._lock:
            subscribers = list(self._subscribers)

        for q in subscribers:
            loop.call_soon_threadsafe(self._enqueue, q, event)

    @staticmethod
    def _enqueue(q: asyncio.Queue, event: dict) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
