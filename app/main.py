"""FastAPI application for the Transcribing Studio: files/categories/transcript
APIs, job queue, SSE events, and the static frontend mount."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app import config, db
from app.events import EventBus
from whisperx.utils import LANGUAGES as WHISPER_LANGUAGES

from app.schemas import (
    CategoriesResponse,
    CreateCategoryRequest,
    DownloadJobRequest,
    FilesResponse,
    JobResponse,
    JobsResponse,
    LanguageOption,
    MetaResponse,
    TranscribeJobRequest,
    TranscriptResponse,
)
from app.services import files as files_service
from app.services.downloader import run_download
from app.services.transcriber import ModelCache, run_transcribe
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
    model_cache = ModelCache()
    worker.register(
        "transcribe",
        lambda job, ctx: run_transcribe(job["params"], ctx, audio_root, transcripts_root, model_cache),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Both roots are gitignored, so a fresh clone has neither; the files
        # and categories endpoints iterate them and would 500 otherwise.
        audio_root.mkdir(parents=True, exist_ok=True)
        transcripts_root.mkdir(parents=True, exist_ok=True)
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

    @app.get("/api/files", response_model=FilesResponse)
    def get_files() -> FilesResponse:
        tree = files_service.list_tree(audio_root, transcripts_root)
        return FilesResponse(tree=tree)

    @app.get("/api/categories", response_model=CategoriesResponse)
    def get_categories() -> CategoriesResponse:
        return CategoriesResponse(categories=files_service.list_categories(audio_root))

    @app.post("/api/categories", status_code=201)
    def post_category(body: CreateCategoryRequest) -> dict:
        # The services raise ValueError for caller mistakes; convert those to
        # 400 here, at the call site, so an incidental ValueError from a bug
        # elsewhere still surfaces as a 500 instead of a misleading 400.
        try:
            files_service.create_category(audio_root, transcripts_root, body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"name": body.name}

    @app.get("/api/transcript", response_model=TranscriptResponse)
    def get_transcript(path: str) -> TranscriptResponse:
        try:
            content = files_service.read_transcript(transcripts_root, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return TranscriptResponse(path=path, content=content)

    @app.get("/api/meta", response_model=MetaResponse)
    def get_meta() -> MetaResponse:
        return MetaResponse(
            models=config.WHISPER_MODELS,
            default_model="base",
            hf_token_present=bool(os.environ.get("HF_TOKEN")),
            languages=[
                LanguageOption(code=code, name=name)
                for code, name in sorted(WHISPER_LANGUAGES.items(), key=lambda item: item[1])
            ],
        )

    @app.post("/api/jobs/download", status_code=202)
    def post_download_job(body: DownloadJobRequest) -> dict:
        category = body.category
        if category:
            resolved = (audio_root / category).resolve()
            if not resolved.is_relative_to(audio_root.resolve()) or not resolved.is_dir():
                raise HTTPException(status_code=400, detail=f"unknown category: {category!r}")

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

    @app.post("/api/jobs/transcribe", status_code=202)
    def post_transcribe_job(body: TranscribeJobRequest) -> dict:
        if body.model not in config.WHISPER_MODELS:
            raise HTTPException(status_code=400, detail=f"unknown model: {body.model!r}")

        # Whisper only accepts lowercase ISO codes ("UK" fails at model-load
        # time inside the worker); normalize here so the job never queues
        # with a code that is guaranteed to fail.
        language = (body.language or "").strip().lower() or None
        if language is not None and language not in WHISPER_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"unknown language: {body.language!r}")

        resolved_root = audio_root.resolve()
        resolved = (resolved_root / body.path).resolve()
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
            raise HTTPException(status_code=400, detail=f"source file not found: {body.path!r}")

        category = Path(body.path).parts[0] if len(Path(body.path).parts) > 1 else ""

        conn = db.connect(db_path)
        try:
            job_id = db.create_job(
                conn,
                kind="transcribe",
                params={
                    "path": body.path,
                    "model": body.model,
                    "language": language,
                    "diarize": body.diarize,
                    "num_speakers": body.num_speakers,
                },
                category=category,
            )
        finally:
            conn.close()

        worker.submit(job_id)
        return {"job_id": job_id}

    @app.get("/api/jobs", response_model=JobsResponse)
    def get_jobs(kind: str | None = None) -> dict:
        conn = db.connect(db_path)
        try:
            jobs = db.list_jobs(conn, kind=kind)
        finally:
            conn.close()
        return {"jobs": jobs}

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
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
        if status is not None:
            return {"status": status}
        # Distinguish the two no-op cases so the UI can say something true:
        # a job id that doesn't exist vs. a job that can't be cancelled
        # (already terminal, or orphaned by a server restart).
        conn = db.connect(db_path)
        try:
            job = db.get_job(conn, job_id)
        finally:
            conn.close()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        raise HTTPException(status_code=409, detail=f"job is not cancellable (status: {job['status']})")

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
