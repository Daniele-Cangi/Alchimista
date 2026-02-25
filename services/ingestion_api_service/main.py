from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from services.shared.config import load_runtime_config
from services.shared.contracts import DocumentStatusResponse, IngestMessage, JobRecord, JobStatus, now_iso8601
from services.shared.db import (
    fetch_document_status,
    get_connection,
    get_document_by_hash,
    upsert_document,
    upsert_process_job,
)
from services.shared.dlq_replay import parse_ingest_message_from_dlq
from services.shared.hashing import sha256_bytes
from services.shared.logging_utils import log_event
from services.shared.pubsub_client import PubSubPublisher, PubSubSubscriber
from services.shared.storage import StorageClient, safe_object_name


config = load_runtime_config()
app = FastAPI(title="ingestion-api-service", version="0.1.0")
storage_client = StorageClient(config.project_id)
publisher = PubSubPublisher(config.project_id)
subscriber = PubSubSubscriber(config.project_id)


class IngestSignedUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = Field(default="application/octet-stream")
    size: int = Field(default=0, ge=0)
    tenant: str = Field(default=config.default_tenant)
    doc_id: str | None = None
    trace_id: str | None = None


class IngestCompleteRequest(BaseModel):
    doc_id: str
    tenant: str = Field(default=config.default_tenant)
    trace_id: str | None = None
    gcs_uri: str | None = None
    force_reprocess: bool = False


class IngestResponse(BaseModel):
    doc_id: str
    trace_id: str
    status: str
    gcs_uri: str
    published: bool
    pubsub_message_id: str | None = None
    deduplicated_to_doc_id: str | None = None
    upload_url: str | None = None
    complete_endpoint: str | None = None


class HealthResponse(BaseModel):
    status: str


class DlqReplayRequest(BaseModel):
    max_messages: int = Field(default=10, ge=1, le=200)


class DlqReplayResponse(BaseModel):
    trace_id: str
    requested: int
    pulled: int
    replayed: int
    acked: int
    failed: int
    replayed_doc_ids: list[str]


@app.get("/v1/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/v1/readyz", response_model=HealthResponse)
def readyz() -> HealthResponse:
    try:
        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return HealthResponse(status="ready")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=f"Database not ready: {exc}") from exc


@app.post("/v1/ingest", response_model=IngestResponse)
async def ingest(request: Request) -> IngestResponse:
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        return await _ingest_multipart(request)
    return await _ingest_signed_url(request)


@app.post("/v1/ingest/complete", response_model=IngestResponse)
def complete_ingest(request: IngestCompleteRequest) -> IngestResponse:
    _require_raw_bucket()
    trace_id = request.trace_id or str(uuid4())
    job_id: str | None = None

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            existing = fetch_document_status(cur, request.doc_id, request.tenant)
            if not existing:
                raise HTTPException(status_code=404, detail="doc_id not found")

            gcs_uri = request.gcs_uri or existing["source_uri"]
            try:
                payload = storage_client.download_bytes(gcs_uri)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Unable to read object: {exc}") from exc

            content_hash = sha256_bytes(payload)
            duplicate_doc = get_document_by_hash(cur, request.tenant, content_hash)
            if duplicate_doc and duplicate_doc["doc_id"] != request.doc_id and not request.force_reprocess:
                conn.commit()
                return IngestResponse(
                    doc_id=request.doc_id,
                    trace_id=trace_id,
                    status="DEDUPLICATED",
                    gcs_uri=gcs_uri,
                    published=False,
                    deduplicated_to_doc_id=duplicate_doc["doc_id"],
                )

            upsert_document(
                cur,
                doc_id=request.doc_id,
                tenant=request.tenant,
                source_uri=gcs_uri,
                mime_type=existing["mime_type"],
                size_bytes=len(payload),
                content_hash=content_hash,
            )
            job_id = upsert_process_job(
                cur,
                doc_id=request.doc_id,
                tenant=request.tenant,
                trace_id=trace_id,
                status=JobStatus.QUEUED,
                metrics={"source": "ingest-complete"},
            )
            conn.commit()

    message = IngestMessage(
        id=request.doc_id,
        uri=gcs_uri,
        type=existing.get("mime_type") or "application/octet-stream",
        size=len(payload),
        tenant=request.tenant,
        ts=now_iso8601(),
        trace_id=trace_id,
    )
    message_id = _publish_ingest_message(message, job_id=job_id)
    return IngestResponse(
        doc_id=request.doc_id,
        trace_id=trace_id,
        status=JobStatus.QUEUED.value,
        gcs_uri=gcs_uri,
        published=True,
        pubsub_message_id=message_id,
    )


@app.get("/v1/doc/{doc_id}", response_model=DocumentStatusResponse)
def get_document_status(doc_id: str, tenant: str = config.default_tenant) -> DocumentStatusResponse:
    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            row = fetch_document_status(cur, doc_id, tenant)

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    job = None
    if row.get("job_id"):
        job = JobRecord(
            job_id=str(row["job_id"]),
            doc_id=row["doc_id"],
            tenant=row["tenant"],
            type=row["type"],
            status=JobStatus(row["status"]),
            trace_id=row["trace_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            metrics=row.get("metrics") or {},
            error=row.get("error"),
        )

    return DocumentStatusResponse(
        doc_id=row["doc_id"],
        tenant=row["tenant"],
        source_uri=row["source_uri"],
        mime_type=row.get("mime_type"),
        size_bytes=row.get("size_bytes"),
        content_hash=row.get("content_hash"),
        updated_at=row["updated_at"],
        job=job,
    )


@app.post("/v1/admin/replay-dlq", response_model=DlqReplayResponse)
def replay_dlq(request: DlqReplayRequest, raw_request: Request) -> DlqReplayResponse:
    _require_admin_api_key(raw_request)
    trace_id = str(uuid4())
    try:
        received = subscriber.pull(config.ingest_dlq_subscription, request.max_messages)
    except Exception as exc:
        log_event(
            "error",
            "dlq_replay_pull_failed",
            trace_id=trace_id,
            subscription=config.ingest_dlq_subscription,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail="Unable to read DLQ subscription") from exc
    replayed_doc_ids: list[str] = []
    ack_ids: list[str] = []
    failed = 0

    for item in received:
        try:
            message = parse_ingest_message_from_dlq(item.message.data)
            message_id = _publish_ingest_message(message)
            replayed_doc_ids.append(message.id)
            ack_ids.append(item.ack_id)
            log_event(
                "info",
                "dlq_message_replayed",
                trace_id=trace_id,
                doc_id=message.id,
                tenant=message.tenant,
                dlq_message_id=item.message.message_id,
                replay_message_id=message_id,
                subscription=config.ingest_dlq_subscription,
            )
        except Exception as exc:
            failed += 1
            log_event(
                "error",
                "dlq_message_replay_failed",
                trace_id=trace_id,
                dlq_message_id=item.message.message_id,
                subscription=config.ingest_dlq_subscription,
                error=str(exc),
            )

    if ack_ids:
        try:
            subscriber.acknowledge(config.ingest_dlq_subscription, ack_ids)
        except Exception as exc:
            log_event(
                "error",
                "dlq_replay_ack_failed",
                trace_id=trace_id,
                subscription=config.ingest_dlq_subscription,
                error=str(exc),
            )
            raise HTTPException(status_code=502, detail="DLQ replay ack failed") from exc

    log_event(
        "info",
        "dlq_replay_completed",
        trace_id=trace_id,
        requested=request.max_messages,
        pulled=len(received),
        replayed=len(ack_ids),
        failed=failed,
        acked=len(ack_ids),
    )
    return DlqReplayResponse(
        trace_id=trace_id,
        requested=request.max_messages,
        pulled=len(received),
        replayed=len(ack_ids),
        acked=len(ack_ids),
        failed=failed,
        replayed_doc_ids=replayed_doc_ids,
    )


async def _ingest_signed_url(request: Request) -> IngestResponse:
    _require_raw_bucket()
    payload = IngestSignedUrlRequest.model_validate(await request.json())
    doc_id = payload.doc_id or str(uuid4())
    trace_id = payload.trace_id or str(uuid4())
    job_id: str | None = None
    object_name = f"raw/{payload.tenant}/{doc_id}/{safe_object_name(payload.filename)}"
    gcs_uri = f"gs://{config.raw_bucket}/{object_name}"

    if config.enforce_storage_hardening:
        _assert_bucket_hardening(config.raw_bucket)

    try:
        upload_url = storage_client.generate_upload_signed_url(
            bucket_name=config.raw_bucket,
            object_name=object_name,
            content_type=payload.content_type,
            expiration_minutes=config.signed_url_expiration_minutes,
        )
    except Exception as exc:  # pragma: no cover
        upload_url = None
        log_event(
            "warning",
            "signed_url_generation_failed",
            trace_id=trace_id,
            doc_id=doc_id,
            tenant=payload.tenant,
            error=str(exc),
        )

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            upsert_document(
                cur,
                doc_id=doc_id,
                tenant=payload.tenant,
                source_uri=gcs_uri,
                mime_type=payload.content_type,
                size_bytes=payload.size,
                content_hash=None,
            )
            job_id = upsert_process_job(
                cur,
                doc_id=doc_id,
                tenant=payload.tenant,
                trace_id=trace_id,
                status=JobStatus.QUEUED,
                metrics={"awaiting_upload": True, "source": "signed-url"},
            )
            conn.commit()

    log_event(
        "info",
        "signed_url_created",
        trace_id=trace_id,
        doc_id=doc_id,
        job_id=job_id,
        tenant=payload.tenant,
        gcs_uri=gcs_uri,
        signed_url_available=upload_url is not None,
    )

    return IngestResponse(
        doc_id=doc_id,
        trace_id=trace_id,
        status=JobStatus.QUEUED.value,
        gcs_uri=gcs_uri,
        published=False,
        upload_url=upload_url,
        complete_endpoint="/v1/ingest/complete",
    )


async def _ingest_multipart(request: Request) -> IngestResponse:
    _require_raw_bucket()
    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(status_code=400, detail="multipart form must include 'file'")

    tenant = str(form.get("tenant") or config.default_tenant)
    doc_id = str(form.get("doc_id") or uuid4())
    trace_id = str(form.get("trace_id") or uuid4())
    force_reprocess = str(form.get("force_reprocess") or "false").lower() == "true"
    job_id: str | None = None

    filename = getattr(file, "filename", "document.bin")
    content_type = getattr(file, "content_type", None) or "application/octet-stream"
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")

    content_hash = sha256_bytes(payload)

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            duplicate = get_document_by_hash(cur, tenant, content_hash)
            if duplicate and not force_reprocess:
                row = fetch_document_status(cur, duplicate["doc_id"], tenant)
                conn.commit()
                return IngestResponse(
                    doc_id=duplicate["doc_id"],
                    trace_id=trace_id,
                    status="DEDUPLICATED",
                    gcs_uri=row["source_uri"] if row else duplicate["source_uri"],
                    published=False,
                    deduplicated_to_doc_id=duplicate["doc_id"],
                )

            if duplicate:
                doc_id = duplicate["doc_id"]

            object_name = f"raw/{tenant}/{doc_id}/{safe_object_name(filename)}"
            gcs_uri = storage_client.upload_bytes(
                bucket_name=config.raw_bucket,
                object_name=object_name,
                payload=payload,
                content_type=content_type,
            )

            upsert_document(
                cur,
                doc_id=doc_id,
                tenant=tenant,
                source_uri=gcs_uri,
                mime_type=content_type,
                size_bytes=len(payload),
                content_hash=content_hash,
            )
            job_id = upsert_process_job(
                cur,
                doc_id=doc_id,
                tenant=tenant,
                trace_id=trace_id,
                status=JobStatus.QUEUED,
                metrics={"source": "multipart"},
            )
            conn.commit()

    message = IngestMessage(
        id=doc_id,
        uri=gcs_uri,
        type=content_type,
        size=len(payload),
        tenant=tenant,
        ts=now_iso8601(),
        trace_id=trace_id,
    )
    message_id = _publish_ingest_message(message, job_id=job_id)

    return IngestResponse(
        doc_id=doc_id,
        trace_id=trace_id,
        status=JobStatus.QUEUED.value,
        gcs_uri=gcs_uri,
        published=True,
        pubsub_message_id=message_id,
    )


def _publish_ingest_message(message: IngestMessage, *, job_id: str | None = None) -> str:
    payload = message.model_dump(mode="json")
    message_id = publisher.publish_json(config.ingest_topic, payload)
    log_event(
        "info",
        "ingest_message_published",
        trace_id=message.trace_id,
        doc_id=message.id,
        job_id=job_id,
        tenant=message.tenant,
        topic=config.ingest_topic,
        pubsub_message_id=message_id,
    )
    return message_id


def _require_raw_bucket() -> None:
    if not config.raw_bucket or config.raw_bucket.startswith("TODO"):
        raise HTTPException(status_code=500, detail="RAW_BUCKET is not configured")


def _assert_bucket_hardening(bucket_name: str) -> None:
    status = storage_client.bucket_hardening_status(bucket_name)
    if not status["ubla"]:
        raise HTTPException(status_code=412, detail="UBLA is required but disabled")
    if not status["default_kms_key_name"]:
        raise HTTPException(status_code=412, detail="CMEK default KMS key is required but missing")


def _require_admin_api_key(request: Request) -> None:
    if not config.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    provided = request.headers.get("x-admin-key", "")
    if not hmac.compare_digest(provided, config.admin_api_key):
        raise HTTPException(status_code=403, detail="Forbidden")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("services.ingestion_api_service.main:app", host="0.0.0.0", port=port)
