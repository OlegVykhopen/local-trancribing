"""FastAPI application for the Transcribing Studio (M2: + jobs API, SSE)."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app import config, db
from app.events import EventBus
from app.schemas import (
    CategoriesResponse,
    CreateCategoryRequest,
    DownloadJobRequest,
    FilesResponse,
    MetaResponse,
    TranscriptResponse,
)
from app.services import files as files_service
from app.services.downloader import run_download
from app.worker import Worker

dotenv.load_dotenv()


def create_app(
    audio_root: Path,
    transcripts_root: Path,
    db_path: Path,
    frontend_dist: Path | None = None,
) -> FastAPI:
    bus = EventBus()
    worker = Worker(str(db_path), bus)
    worker.register("download", lambda job, ctx: run_download(job["params"], ctx, audio_root))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        bus.attach_loop(asyncio.get_running_loop())
        conn = db.connect(db_path)
        try:
            db.mark_interrupted(conn)
        finally:
            conn.close()
        worker.start()
        yield
        worker.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.bus = bus
    app.state.worker = worker

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/files", response_model=FilesResponse)
    def get_files() -> FilesResponse:
        tree = files_service.list_tree(audio_root, transcripts_root)
        return FilesResponse(tree=tree)

    @app.get("/api/categories", response_model=CategoriesResponse)
    def get_categories() -> CategoriesResponse:
        return CategoriesResponse(categories=files_service.list_categories(audio_root))

    @app.post("/api/categories", status_code=201)
    def post_category(body: CreateCategoryRequest) -> dict:
        files_service.create_category(audio_root, transcripts_root, body.name)
        return {"name": body.name}

    @app.get("/api/transcript", response_model=TranscriptResponse)
    def get_transcript(path: str) -> TranscriptResponse:
        content = files_service.read_transcript(transcripts_root, path)
        return TranscriptResponse(path=path, content=content)

    @app.get("/api/meta", response_model=MetaResponse)
    def get_meta() -> MetaResponse:
        return MetaResponse(
            models=config.WHISPER_MODELS,
            default_model="base",
            hf_token_present=bool(os.environ.get("HF_TOKEN")),
        )

    @app.post("/api/jobs/download", status_code=202)
    def post_download_job(body: DownloadJobRequest) -> dict:
        category = body.category
        if category and not (audio_root / category).is_dir():
            raise ValueError(f"unknown category: {category!r}")

        conn = db.connect(db_path)
        try:
            job_id = db.create_job(
                conn,
                kind="download",
                params={"url": body.url, "category": category, "format": "audio"},
                category=category,
            )
        finally:
            conn.close()

        worker.submit(job_id)
        return {"job_id": job_id}

    @app.get("/api/jobs")
    def get_jobs(kind: str | None = None) -> dict:
        conn = db.connect(db_path)
        try:
            jobs = db.list_jobs(conn, kind=kind)
        finally:
            conn.close()
        return {"jobs": jobs}

    @app.get("/api/jobs/{job_id}")
    def get_job_route(job_id: int) -> dict:
        conn = db.connect(db_path)
        try:
            job = db.get_job(conn, job_id)
        finally:
            conn.close()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/api/jobs/{job_id}/logs")
    def get_job_logs_route(job_id: int) -> dict:
        conn = db.connect(db_path)
        try:
            logs = db.get_logs(conn, job_id)
        finally:
            conn.close()
        return {"logs": logs}

    @app.post("/api/jobs/{job_id}/cancel")
    def post_cancel_job(job_id: int) -> dict:
        status = worker.cancel(job_id)
        return {"status": status}

    @app.get("/api/queue")
    def get_queue() -> dict:
        return {"queue": worker.queue_snapshot()}

    @app.get("/api/events")
    async def get_events(request: Request) -> EventSourceResponse:
        async def event_generator():
            q = bus.subscribe()
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    event = await q.get()
                    yield {"event": event["type"], "data": json.dumps(event)}
            finally:
                bus.unsubscribe(q)

        return EventSourceResponse(event_generator())

    if frontend_dist is not None and Path(frontend_dist).exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app(
    config.AUDIO_ROOT,
    config.TRANSCRIPTS_ROOT,
    config.DB_PATH,
    config.FRONTEND_DIST,
)
