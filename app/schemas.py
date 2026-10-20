"""Pydantic request/response models for the Transcribing Studio API."""

from __future__ import annotations

from pydantic import BaseModel


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


class MetaResponse(BaseModel):
    models: list[str]
    default_model: str
    hf_token_present: bool
