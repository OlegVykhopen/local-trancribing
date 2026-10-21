"""Pydantic request/response models for the Transcribing Studio API."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    DONE = "done"
    ERROR = "error"


class FileNode(BaseModel):
    name: str
    path: str
    type: str
    children: list["FileNode"] | None = None
    transcribed: bool | None = None


FileNode.model_rebuild()


class FilesResponse(BaseModel):
    tree: list[FileNode]


class CategoriesResponse(BaseModel):
    categories: list[str]


class CreateCategoryRequest(BaseModel):
    name: str


class TranscriptResponse(BaseModel):
    path: str
    content: str


class LanguageOption(BaseModel):
    code: str
    name: str


class MetaResponse(BaseModel):
    models: list[str]
    default_model: str
    hf_token_present: bool
    languages: list[LanguageOption]


class DownloadJobRequest(BaseModel):
    url: str = Field(..., min_length=1)
    category: str = ""

    @field_validator("url")
    @classmethod
    def url_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url must not be blank")
        return v


class TranscribeJobRequest(BaseModel):
    path: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    language: str | None = None
    diarize: bool = False
    num_speakers: int | None = Field(None, ge=1)


class JobResponse(BaseModel):
    """The one shape jobs cross the API in — mirrored by Job in frontend/src/lib/types.ts."""

    id: int
    kind: Literal["download", "transcribe", "pipeline"]
    status: JobStatus
    params: dict | None = None
    category: str | None = None
    parent_job_id: int | None = None
    progress: int = Field(0, ge=0, le=100)
    stage: str | None = None
    result: dict | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class JobsResponse(BaseModel):
    jobs: list[JobResponse]
