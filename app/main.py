"""FastAPI application for the Transcribing Studio (read-only API, M1)."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.schemas import (
    CategoriesResponse,
    CreateCategoryRequest,
    FilesResponse,
    MetaResponse,
    TranscriptResponse,
)
from app.services import files as files_service

dotenv.load_dotenv()


def create_app(
    audio_root: Path,
    transcripts_root: Path,
    db_path: Path,
    frontend_dist: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        conn = db.connect(db_path)
        try:
            db.mark_interrupted(conn)
        finally:
            conn.close()
        yield

    app = FastAPI(lifespan=lifespan)

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

    if frontend_dist is not None and Path(frontend_dist).exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app(
    config.AUDIO_ROOT,
    config.TRANSCRIPTS_ROOT,
    config.DB_PATH,
    config.FRONTEND_DIST,
)
