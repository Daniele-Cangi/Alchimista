from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class IngestMessage(BaseModel):
    id: str = Field(..., description="Document identifier")
    uri: str = Field(..., description="GCS URI (gs://bucket/path)")
    type: str = Field(..., description="MIME type")
    size: int = Field(..., ge=0, description="Object size in bytes")
    tenant: str = Field(default="default")
    ts: str = Field(..., description="ISO8601 timestamp")
    trace_id: str = Field(..., description="Trace correlation ID")

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        if not value.startswith("gs://"):
            raise ValueError("uri must start with gs://")
        return value


class Citation(BaseModel):
    doc_id: str
    chunk_id: str


class QueryAnswer(BaseModel):
    text: str
    score: float
    citations: list[Citation]

    @field_validator("citations")
    @classmethod
    def citations_must_exist(cls, value: list[Citation]) -> list[Citation]:
        if not value:
            raise ValueError("citations must not be empty")
        return value


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    tenant: str = Field(default="default")
    top_k: int = Field(default=5, ge=1, le=20)
    trace_id: str | None = None
    doc_ids: list[str] | None = None


class QueryResponse(BaseModel):
    answers: list[QueryAnswer]
    trace_id: str


class JobRecord(BaseModel):
    job_id: str
    doc_id: str
    tenant: str
    type: str
    status: JobStatus
    trace_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DocumentStatusResponse(BaseModel):
    doc_id: str
    tenant: str
    source_uri: str
    mime_type: str | None = None
    size_bytes: int | None = None
    content_hash: str | None = None
    updated_at: datetime
    job: JobRecord | None = None


class PubSubPushMessage(BaseModel):
    data: str
    messageId: str | None = None
    publishTime: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class PubSubPushEnvelope(BaseModel):
    message: PubSubPushMessage
    subscription: str | None = None


def now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()
