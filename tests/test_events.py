import asyncio
import threading

from app.events import EventBus


async def test_publish_from_thread_reaches_subscriber():
    bus = EventBus()
    bus.attach_loop(asyncio.get_running_loop())
    q = bus.subscribe()

    event = {"type": "job_status", "job_id": "abc", "status": "running"}

    def worker():
        bus.publish(event)

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    received = await asyncio.wait_for(q.get(), timeout=1)
    assert received == event

    bus.unsubscribe(q)


async def test_full_queue_drops_oldest_not_blocks():
    bus = EventBus()
    bus.attach_loop(asyncio.get_running_loop())
    q = bus.subscribe()

    maxsize = q.maxsize
    for i in range(maxsize + 1):
        bus.publish({"type": "job_progress", "i": i})
        # let the loop process the call_soon_threadsafe callback
        await asyncio.sleep(0)

    assert q.full()
    assert q.qsize() == maxsize

    items = []
    while not q.empty():
        items.append(q.get_nowait())

    # the oldest event (i == 0) should have been dropped
    assert items[0]["i"] == 1
    # the newest event must be present
    assert items[-1]["i"] == maxsize

    bus.unsubscribe(q)


async def test_unsubscribed_queue_stops_receiving():
    bus = EventBus()
    bus.attach_loop(asyncio.get_running_loop())
    q = bus.subscribe()

    bus.unsubscribe(q)

    bus.publish({"type": "queue", "foo": "bar"})
    await asyncio.sleep(0)

    assert q.empty()


async def test_publish_before_attach_loop_is_noop():
    bus = EventBus()
    # no attach_loop call — publish must not raise and must not block
    bus.publish({"type": "job_log", "msg": "hello"})
