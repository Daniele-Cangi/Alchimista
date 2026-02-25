from __future__ import annotations

import base64
import json
import os
import time
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pypdf import PdfReader

from services.shared.auth import require_auth, require_pubsub_push_auth
from services.shared.backpressure import InflightGate
from services.shared.chunking import chunk_text
from services.shared.config import load_runtime_config
from services.shared.contracts import IngestMessage, JobStatus, PubSubPushEnvelope
from services.shared.db import (
    get_chunk_ids_for_doc,
    get_connection,
    replace_chunks,
    replace_entities,
    upsert_document,
    upsert_process_job,
    utcnow,
)
from services.shared.embeddings import build_embedder
from services.shared.entities import extract_entities
from services.shared.hashing import sha256_bytes
from services.shared.logging_utils import log_event
from services.shared.pubsub_client import PubSubPublisher
from services.shared.storage import StorageClient
from services.shared.vertex_vector_search import build_vertex_client


config = load_runtime_config()
app = FastAPI(title="document-processor-service", version="0.1.0")
storage_client = StorageClient(config.project_id)
publisher = PubSubPublisher(config.project_id)
vertex_client = build_vertex_client(config)
inflight_gate = InflightGate(config.processor_max_inflight)
embed_text = build_embedder(config)


class ProcessResponse(BaseModel):
    doc_id: str
    tenant: str
    status: str
    chunks: int
    entities: int
    trace_id: str


class HealthResponse(BaseModel):
    status: str


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


@app.post("/v1/process", response_model=ProcessResponse)
def process_direct(message: IngestMessage, request: Request) -> ProcessResponse:
    require_auth(request, config=config, tenant=message.tenant)
    return _process_with_backpressure(message)


@app.post("/v1/process/pubsub", response_model=ProcessResponse)
def process_pubsub(envelope: PubSubPushEnvelope, request: Request) -> ProcessResponse:
    try:
        decoded = base64.b64decode(envelope.message.data).decode("utf-8")
        payload = json.loads(decoded)
        message = IngestMessage.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Pub/Sub envelope: {exc}") from exc

    auth_header = request.headers.get("authorization", "")
    if config.auth_enabled and (not config.auth_allow_unauthenticated_pubsub or auth_header):
        try:
            require_auth(request, config=config, tenant=message.tenant)
        except HTTPException:
            if not auth_header or not config.pubsub_push_auth_enabled:
                raise
            require_pubsub_push_auth(request, config=config)

    return _process_with_backpressure(message)


def _process_with_backpressure(message: IngestMessage) -> ProcessResponse:
    if not inflight_gate.try_enter():
        log_event(
            "warning",
            "processor_backpressure_reject",
            trace_id=message.trace_id,
            doc_id=message.id,
            job_id=None,
            tenant=message.tenant,
            active=inflight_gate.active,
            max_inflight=inflight_gate.limit,
        )
        raise HTTPException(status_code=429, detail="Processor busy, retry later")
    try:
        return _process_ingest_message(message)
    finally:
        inflight_gate.leave()


def _process_ingest_message(message: IngestMessage) -> ProcessResponse:
    trace_id = message.trace_id or str(uuid4())
    process_job_id: str | None = None
    started_at = utcnow()
    t0 = time.perf_counter()

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            process_job_id = upsert_process_job(
                cur,
                doc_id=message.id,
                tenant=message.tenant,
                trace_id=trace_id,
                status=JobStatus.RUNNING,
                started_at=started_at,
                metrics={"phase": "download"},
            )
            conn.commit()

    try:
        payload = storage_client.download_bytes(message.uri)
        content_hash = sha256_bytes(payload)
        text = _extract_text(payload, message.type, message.uri)
        text_chunks = chunk_text(text)
        if not text_chunks:
            raise RuntimeError("No text extracted from document")

        chunk_records = []
        entity_records = []

        for idx, chunk in enumerate(text_chunks):
            chunk_id = f"{message.id}:{idx:05d}"
            embedding = embed_text(chunk)
            chunk_records.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": message.id,
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "token_count": len(chunk.split()),
                    "embedding": embedding,
                    "metadata": {"source_uri": message.uri, "mime_type": message.type},
                }
            )

            for entity_type, entity_value in extract_entities(chunk):
                entity_records.append(
                    {
                        "chunk_id": chunk_id,
                        "entity_type": entity_type,
                        "entity_value": entity_value,
                    }
                )

        finished_at = utcnow()
        duration_ms = int((time.perf_counter() - t0) * 1000)
        existing_chunk_ids: list[str] = []

        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                existing_chunk_ids = get_chunk_ids_for_doc(cur, message.id, message.tenant)
                upsert_document(
                    cur,
                    doc_id=message.id,
                    tenant=message.tenant,
                    source_uri=message.uri,
                    mime_type=message.type,
                    size_bytes=message.size,
                    content_hash=content_hash,
                )
                replace_chunks(cur, doc_id=message.id, tenant=message.tenant, chunks=chunk_records)
                replace_entities(cur, doc_id=message.id, tenant=message.tenant, entities=entity_records)
                conn.commit()

        _sync_vector_index(
            tenant=message.tenant,
            chunk_records=chunk_records,
            existing_chunk_ids=existing_chunk_ids,
        )

        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                process_job_id = upsert_process_job(
                    cur,
                    doc_id=message.id,
                    tenant=message.tenant,
                    trace_id=trace_id,
                    status=JobStatus.SUCCEEDED,
                    started_at=started_at,
                    finished_at=finished_at,
                    metrics={
                        "chunks": len(chunk_records),
                        "entities": len(entity_records),
                        "duration_ms": duration_ms,
                        "vector_backend": config.vector_backend,
                    },
                )
                conn.commit()

        _write_processed_report(message, chunk_records, trace_id)

        log_event(
            "info",
            "document_processed",
            trace_id=trace_id,
            doc_id=message.id,
            job_id=process_job_id,
            tenant=message.tenant,
            chunks=len(chunk_records),
            entities=len(entity_records),
            duration_ms=duration_ms,
        )

        return ProcessResponse(
            doc_id=message.id,
            tenant=message.tenant,
            status=JobStatus.SUCCEEDED.value,
            chunks=len(chunk_records),
            entities=len(entity_records),
            trace_id=trace_id,
        )

    except Exception as exc:
        finished_at = utcnow()
        error_text = str(exc)

        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                process_job_id = upsert_process_job(
                    cur,
                    doc_id=message.id,
                    tenant=message.tenant,
                    trace_id=trace_id,
                    status=JobStatus.FAILED,
                    started_at=started_at,
                    finished_at=finished_at,
                    metrics={"phase": "failed"},
                    error=error_text,
                )
                conn.commit()

        _publish_dlq(message, trace_id, error_text, job_id=process_job_id)
        log_event(
            "error",
            "document_processing_failed",
            trace_id=trace_id,
            doc_id=message.id,
            job_id=process_job_id,
            tenant=message.tenant,
            error=error_text,
        )
        raise HTTPException(status_code=500, detail=error_text) from exc


def _sync_vector_index(*, tenant: str, chunk_records: list[dict], existing_chunk_ids: list[str]) -> None:
    if not vertex_client:
        return

    new_ids = {chunk["chunk_id"] for chunk in chunk_records}
    stale_ids = [chunk_id for chunk_id in existing_chunk_ids if chunk_id not in new_ids]
    vertex_client.upsert_chunks(tenant=tenant, chunks=chunk_records)
    vertex_client.remove_chunks(stale_ids)


def _extract_text(payload: bytes, mime_type: str, uri: str) -> str:
    lowered = mime_type.lower()
    if lowered == "application/pdf" or uri.lower().endswith(".pdf"):
        return _extract_pdf(payload)

    if lowered.startswith("text/"):
        return payload.decode("utf-8", errors="ignore")

    if lowered.startswith("image/"):
        return _extract_image_text(payload)

    return payload.decode("utf-8", errors="ignore")


def _extract_pdf(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _extract_image_text(payload: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"OCR dependencies unavailable: {exc}") from exc

    with Image.open(BytesIO(payload)) as img:
        return pytesseract.image_to_string(img)


def _publish_dlq(message: IngestMessage, trace_id: str, reason: str, job_id: str | None) -> None:
    payload = {
        "reason": reason,
        "trace_id": trace_id,
        "ts": utcnow().isoformat(),
        "event": message.model_dump(mode="json"),
    }
    try:
        publisher.publish_json(config.ingest_dlq_topic, payload)
    except Exception as exc:  # pragma: no cover
        log_event(
            "error",
            "dlq_publish_failed",
            trace_id=trace_id,
            doc_id=message.id,
            job_id=job_id,
            tenant=message.tenant,
            error=str(exc),
        )


def _write_processed_report(message: IngestMessage, chunks: list[dict], trace_id: str) -> None:
    if not config.processed_bucket or config.processed_bucket.startswith("TODO"):
        return

    report = {
        "doc_id": message.id,
        "tenant": message.tenant,
        "trace_id": trace_id,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "chunk_index": chunk["chunk_index"],
                "token_count": chunk["token_count"],
                "preview": chunk["chunk_text"][:200],
            }
            for chunk in chunks
        ],
    }
    object_name = f"processed/{message.tenant}/{message.id}/report.json"
    storage_client.upload_bytes(
        bucket_name=config.processed_bucket,
        object_name=object_name,
        payload=json.dumps(report, ensure_ascii=True).encode("utf-8"),
        content_type="application/json",
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("services.document_processor_service.main:app", host="0.0.0.0", port=port)
