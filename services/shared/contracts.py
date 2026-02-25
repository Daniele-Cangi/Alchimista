from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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


class DecisionOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class ConfidenceBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


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
    decision_id_prefix: str | None = None
    decision_ids: list[str] | None = None
    model: str | None = None
    model_version: str | None = None
    outputs: list[str] | None = None
    decision_trace_id: str | None = None
    query: str | None = None
    context_docs: list[str] | None = None
    context_chunks: list[str] | None = None
    confidence_band: ConfidenceBand | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    max_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_from: datetime | None = None
    created_to: datetime | None = None
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=50, ge=1, le=200)
    order: DecisionOrder = Field(default=DecisionOrder.DESC)
    trace_id: str | None = None

    @field_validator("context_docs", "context_chunks", "outputs", "decision_ids")
    @classmethod
    def normalize_optional_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = str(item).strip()
            if not candidate:
                raise ValueError("list items must not be empty")
            if candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized

    @model_validator(mode="after")
    def validate_ranges(self) -> AIDecisionQueryRequest:
        if self.min_confidence is not None and self.max_confidence is not None:
            if self.min_confidence > self.max_confidence:
                raise ValueError("min_confidence cannot be greater than max_confidence")
        if self.created_from is not None and self.created_to is not None:
            if self.created_from > self.created_to:
                raise ValueError("created_from cannot be greater than created_to")
        return self


class AIDecisionQueryResponse(BaseModel):
    trace_id: str
    decisions: list[AIDecisionRecord]
    total: int
    offset: int
    limit: int
    returned: int


class AIDecisionExportRequest(AIDecisionQueryRequest):
    limit: int = Field(default=200, ge=1, le=1000)
    include_context: bool = False
    object_name: str | None = None


class AIDecisionExportResponse(BaseModel):
    trace_id: str
    generated_at: datetime
    tenant: str
    total: int
    returned: int
    gs_uri: str
    report_hash_sha256: str
    signature_alg: str
    signature_key_id: str | None = None
    signature: str | None = None


class AIDecisionBundleRequest(AIDecisionExportRequest):
    case_id: str | None = None
    regulator_ref: str | None = None
    include_policy_snapshot: bool = True


class AIDecisionBundleResponse(BaseModel):
    trace_id: str
    bundle_id: str
    generated_at: datetime
    tenant: str
    total: int
    returned: int
    gs_uri: str
    report_hash_sha256: str
    signature_alg: str
    signature_key_id: str | None = None
    signature: str | None = None


class AIDecisionAdminQueryRequest(BaseModel):
    tenants: list[str] = Field(..., min_length=1, max_length=50)
    decision_id_prefix: str | None = None
    decision_ids: list[str] | None = None
    model: str | None = None
    model_version: str | None = None
    outputs: list[str] | None = None
    decision_trace_id: str | None = None
    query: str | None = None
    context_docs: list[str] | None = None
    context_chunks: list[str] | None = None
    confidence_band: ConfidenceBand | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    max_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_from: datetime | None = None
    created_to: datetime | None = None
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=50, ge=1, le=500)
    order: DecisionOrder = Field(default=DecisionOrder.DESC)
    trace_id: str | None = None

    @field_validator("tenants", "context_docs", "context_chunks", "outputs", "decision_ids")
    @classmethod
    def normalize_optional_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = str(item).strip()
            if not candidate:
                raise ValueError("list items must not be empty")
            if candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized

    @model_validator(mode="after")
    def validate_ranges(self) -> AIDecisionAdminQueryRequest:
        if self.min_confidence is not None and self.max_confidence is not None:
            if self.min_confidence > self.max_confidence:
                raise ValueError("min_confidence cannot be greater than max_confidence")
        if self.created_from is not None and self.created_to is not None:
            if self.created_from > self.created_to:
                raise ValueError("created_from cannot be greater than created_to")
        return self


class AIDecisionAdminQueryResponse(BaseModel):
    trace_id: str
    tenants: list[str]
    decisions: list[AIDecisionRecord]
    total: int
    offset: int
    limit: int
    returned: int


class AIDecisionReportResponse(BaseModel):
    trace_id: str
    generated_at: datetime
    decision: AIDecisionRecord
    context_documents: list[dict[str, Any]] = Field(default_factory=list)
    context_chunks: list[dict[str, Any]] = Field(default_factory=list)
    report_hash_sha256: str
    signature_alg: str
    signature_key_id: str | None = None
    signature: str | None = None


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
