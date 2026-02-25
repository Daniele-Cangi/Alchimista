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


class AIDecisionIngestRequest(BaseModel):
    decision_id: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    model_version: str | None = None
    input: str = Field(..., min_length=1)
    output: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    context_docs: list[str] = Field(..., min_length=1)
    context_chunks: list[str] = Field(default_factory=list)
    tenant: str = Field(default="default", min_length=1)
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("context_docs", "context_chunks")
    @classmethod
    def normalize_string_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = str(item).strip()
            if not candidate:
                raise ValueError("context ids must not be empty")
            if candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized


class AIDecisionIngestResponse(BaseModel):
    decision_id: str
    tenant: str
    trace_id: str
    status: str
    context_docs_count: int
    context_chunks_count: int
    created_at: datetime
    updated_at: datetime


class AIDecisionRecord(BaseModel):
    decision_id: str
    tenant: str
    model: str
    model_version: str | None = None
    input: str
    output: str
    confidence: float | None = None
    trace_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    context_docs: list[str] = Field(default_factory=list)
    context_chunks: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AIDecisionQueryRequest(BaseModel):
    tenant: str = Field(default="default", min_length=1)
    model: str | None = None
    model_version: str | None = None
    query: str | None = None
    context_docs: list[str] | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    max_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=200)
    trace_id: str | None = None

    @field_validator("context_docs")
    @classmethod
    def normalize_optional_doc_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = str(item).strip()
            if not candidate:
                raise ValueError("context_docs ids must not be empty")
            if candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized


class AIDecisionQueryResponse(BaseModel):
    trace_id: str
    decisions: list[AIDecisionRecord]
    total: int


class AIDecisionReportResponse(BaseModel):
    trace_id: str
    generated_at: datetime
    decision: AIDecisionRecord
    context_documents: list[dict[str, Any]] = Field(default_factory=list)
    context_chunks: list[dict[str, Any]] = Field(default_factory=list)


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
