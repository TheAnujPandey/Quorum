from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
    blob_store: bool
    qdrant: bool


class UploadInitRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    file_size: int


class UploadInitResponse(BaseModel):
    upload_id: UUID
    session_id: UUID
    chunk_size: int


class UploadCompleteRequest(BaseModel):
    chunking_method: str = "sentence"
    chunking_config: dict[str, Any] = Field(default_factory=dict)


class UploadCompleteResponse(BaseModel):
    session_id: UUID
    job_id: UUID | None = None
    source_format: str
    upload_status: str = "uploaded"


class JobResponse(BaseModel):
    id: UUID
    job_type: str
    status: str
    stage: str | None = None
    progress_pct: int | None = None
    message: str | None = None
    payload: dict[str, Any]
    result_ref: str | None = None
    error: str | None = None
    attempts: int
    created_at: datetime
    updated_at: datetime


class Citation(BaseModel):
    source_ref: str
    excerpt: str


class ConfidenceScore(BaseModel):
    label: str
    faithfulness: float
    answer_relevancy: float


class AskRequest(BaseModel):
    session_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    openai_api_key: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=64)


class ConfigResponse(BaseModel):
    default_model: str
    openai_key_configured: bool


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: ConfidenceScore
    retries_used: int
    execution_time_ms: int
    insufficient: bool = False
