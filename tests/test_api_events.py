"""Contract test for the /api/events SSE endpoint.

The EventBus itself is covered by test_events.py; this pins the HTTP layer
the frontend depends on: a published event arrives at an SSE client with
`event:` set to the event's type (useEvents.ts subscribes via
addEventListener per type) and `data:` as the JSON-encoded event dict.
"""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app(tmp_path):
    audio_root = tmp_path / "audio_sources"
    transcripts_root = tmp_path / "transcripts"
    audio_root.mkdir()
    transcripts_root.mkdir()
    return create_app(audio_root, transcripts_root, tmp_path / "app.db")


def test_events_endpoint_streams_published_events(app):
    event = {"type": "job_status", "job_id": 7, "status": "done"}

    with TestClient(app) as client:
        stop = threading.Event()

        def publisher():
            # The subscriber queue is created only once the server starts
            # generating the response, so publish repeatedly rather than once
            # to avoid racing the subscription.
            while not stop.is_set():
                app.state.bus.publish(event)
                time.sleep(0.02)

        thread = threading.Thread(target=publisher, daemon=True)
        thread.start()
        try:
            with client.stream("GET", "/api/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                event_name = None
                payload = None
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        payload = json.loads(line.split(":", 1)[1].strip())
                        break
        finally:
            stop.set()
            thread.join(timeout=1)

    assert event_name == "job_status"
    assert payload == event
