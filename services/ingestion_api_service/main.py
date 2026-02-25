from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import posixpath
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import PreconditionFailed
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.types.json import Json

from services.shared.auth import require_auth
from services.shared.config import load_runtime_config
from services.shared.contracts import (
    AIDecisionAdminQueryRequest,
    AIDecisionAdminQueryResponse,
    AIDecisionBundleRequest,
    AIDecisionBundleResponse,
    AIDecisionExportRequest,
    AIDecisionExportResponse,
    AIDecisionIngestRequest,
    AIDecisionIngestResponse,
    AIDecisionPackageRequest,
    AIDecisionPackageResponse,
    AIDecisionQueryRequest,
    AIDecisionQueryResponse,
    AIDecisionRecord,
    AIDecisionReportResponse,
    AIDecisionVerifyRequest,
    AIDecisionVerifyResponse,
    ConnectorIngestResponse,
    DocumentStatusResponse,
    GCSConnectorImportRequest,
    IngestMessage,
    JobRecord,
    JobStatus,
    LegalHoldCreateRequest,
    LegalHoldListResponse,
    LegalHoldRecord,
    LegalHoldReleaseRequest,
    LegalHoldResponse,
    RetentionPolicyRecord,
    RetentionPolicyListResponse,
    RetentionEnforcementItem,
    RetentionEnforcementRequest,
    RetentionEnforcementResponse,
    RetentionPolicyResponse,
    RetentionPolicyUpsertRequest,
    now_iso8601,
)
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
from services.shared.storage import StorageClient, parse_gs_uri, safe_object_name


config = load_runtime_config()
app = FastAPI(title="ingestion-api-service", version="0.1.0")
storage_client = StorageClient(config.project_id)
publisher = PubSubPublisher(config.project_id)
subscriber = PubSubSubscriber(config.project_id)
_ai_schema_lock = threading.Lock()
_ai_schema_initialized = False


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
def complete_ingest(request: IngestCompleteRequest, raw_request: Request) -> IngestResponse:
    _require_raw_bucket()
    require_auth(raw_request, config=config, tenant=request.tenant)
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
def get_document_status(request: Request, doc_id: str, tenant: str = config.default_tenant) -> DocumentStatusResponse:
    require_auth(request, config=config, tenant=tenant)
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


@app.post("/v1/connectors/gcs/import", response_model=ConnectorIngestResponse)
def connector_import_gcs(payload: GCSConnectorImportRequest, request: Request) -> ConnectorIngestResponse:
    _require_raw_bucket()
    require_auth(request, config=config, tenant=payload.tenant)
    trace_id = payload.trace_id or str(uuid4())
    doc_id = payload.doc_id or str(uuid4())
    job_id: str | None = None

    try:
        source_bytes = storage_client.download_bytes(payload.source_gcs_uri)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read source_gcs_uri: {exc}") from exc
    if not source_bytes:
        raise HTTPException(status_code=400, detail="Source object is empty")

    _, source_object_name = parse_gs_uri(payload.source_gcs_uri)
    filename = posixpath.basename(source_object_name) or f"{doc_id}.bin"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    content_hash = sha256_bytes(source_bytes)

    if config.enforce_storage_hardening:
        _assert_bucket_hardening(config.raw_bucket)

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            duplicate = get_document_by_hash(cur, payload.tenant, content_hash)
            if duplicate and not payload.force_reprocess:
                row = fetch_document_status(cur, duplicate["doc_id"], payload.tenant)
                conn.commit()
                return ConnectorIngestResponse(
                    connector="gcs",
                    tenant=payload.tenant,
                    doc_id=duplicate["doc_id"],
                    trace_id=trace_id,
                    status="DEDUPLICATED",
                    source_gcs_uri=payload.source_gcs_uri,
                    raw_gcs_uri=row["source_uri"] if row else duplicate["source_uri"],
                    published=False,
                    deduplicated_to_doc_id=duplicate["doc_id"],
                )
            if duplicate:
                doc_id = duplicate["doc_id"]

            object_name = f"raw/{payload.tenant}/{doc_id}/{safe_object_name(filename)}"
            raw_gcs_uri = storage_client.upload_bytes(
                bucket_name=config.raw_bucket,
                object_name=object_name,
                payload=source_bytes,
                content_type=content_type,
            )
            upsert_document(
                cur,
                doc_id=doc_id,
                tenant=payload.tenant,
                source_uri=raw_gcs_uri,
                mime_type=content_type,
                size_bytes=len(source_bytes),
                content_hash=content_hash,
            )
            job_id = upsert_process_job(
                cur,
                doc_id=doc_id,
                tenant=payload.tenant,
                trace_id=trace_id,
                status=JobStatus.QUEUED,
                metrics={"source": "connector:gcs-import", "source_gcs_uri": payload.source_gcs_uri},
            )
            conn.commit()

    message_id = None
    published = False
    if payload.publish:
        message = IngestMessage(
            id=doc_id,
            uri=raw_gcs_uri,
            type=content_type,
            size=len(source_bytes),
            tenant=payload.tenant,
            ts=now_iso8601(),
            trace_id=trace_id,
        )
        message_id = _publish_ingest_message(message, job_id=job_id)
        published = True

    log_event(
        "info",
        "connector_gcs_import_completed",
        trace_id=trace_id,
        doc_id=doc_id,
        job_id=job_id,
        tenant=payload.tenant,
        source_gcs_uri=payload.source_gcs_uri,
        raw_gcs_uri=raw_gcs_uri,
        published=published,
    )
    return ConnectorIngestResponse(
        connector="gcs",
        tenant=payload.tenant,
        doc_id=doc_id,
        trace_id=trace_id,
        status=JobStatus.QUEUED.value if published else "STAGED",
        source_gcs_uri=payload.source_gcs_uri,
        raw_gcs_uri=raw_gcs_uri,
        published=published,
        pubsub_message_id=message_id,
    )


@app.post("/v1/decisions", response_model=AIDecisionIngestResponse)
def ingest_decision(payload: AIDecisionIngestRequest, request: Request) -> AIDecisionIngestResponse:
    require_auth(request, config=config, tenant=payload.tenant)
    trace_id = payload.trace_id or str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            missing_doc_ids = _missing_document_ids(cur, tenant=payload.tenant, doc_ids=payload.context_docs)
            if missing_doc_ids:
                raise HTTPException(
                    status_code=404,
                    detail={"message": "Context documents not found", "missing_doc_ids": missing_doc_ids},
                )

            missing_chunk_ids, mismatched_chunk_ids = _validate_context_chunks(
                cur,
                tenant=payload.tenant,
                chunk_ids=payload.context_chunks,
                allowed_doc_ids=payload.context_docs,
            )
            if missing_chunk_ids:
                raise HTTPException(
                    status_code=404,
                    detail={"message": "Context chunks not found", "missing_chunk_ids": missing_chunk_ids},
                )
            if mismatched_chunk_ids:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "Context chunks must belong to context_docs",
                        "mismatched_chunk_ids": mismatched_chunk_ids,
                    },
                )

            decision_ref_id, created_at, updated_at = _upsert_ai_decision(cur, payload=payload, trace_id=trace_id)
            _replace_ai_decision_context_docs(
                cur,
                decision_ref_id=decision_ref_id,
                tenant=payload.tenant,
                doc_ids=payload.context_docs,
            )
            _replace_ai_decision_context_chunks(
                cur,
                decision_ref_id=decision_ref_id,
                tenant=payload.tenant,
                chunk_ids=payload.context_chunks,
            )
            conn.commit()

    log_event(
        "info",
        "ai_decision_recorded",
        trace_id=trace_id,
        doc_id=payload.context_docs[0],
        job_id=f"ai-decision:{payload.tenant}:{payload.decision_id}",
        tenant=payload.tenant,
        decision_id=payload.decision_id,
        model=payload.model,
        context_docs=len(payload.context_docs),
        context_chunks=len(payload.context_chunks),
    )

    return AIDecisionIngestResponse(
        decision_id=payload.decision_id,
        tenant=payload.tenant,
        trace_id=trace_id,
        status="RECORDED",
        context_docs_count=len(payload.context_docs),
        context_chunks_count=len(payload.context_chunks),
        created_at=created_at,
        updated_at=updated_at,
    )


@app.post("/v1/decisions/query", response_model=AIDecisionQueryResponse)
def query_decisions(payload: AIDecisionQueryRequest, request: Request) -> AIDecisionQueryResponse:
    require_auth(request, config=config, tenant=payload.tenant)
    trace_id = payload.trace_id or str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            conn.commit()
            rows, total = _query_ai_decisions(cur, payload=payload)

    decisions = [_map_ai_decision_row(row) for row in rows]
    log_event(
        "info",
        "ai_decision_query_completed",
        trace_id=trace_id,
        doc_id=None,
        job_id=f"ai-decision-query:{trace_id}",
        tenant=payload.tenant,
        model=payload.model,
        offset=payload.offset,
        limit=payload.limit,
        returned=len(decisions),
        total=total,
    )
    return AIDecisionQueryResponse(
        trace_id=trace_id,
        decisions=decisions,
        total=total,
        offset=payload.offset,
        limit=payload.limit,
        returned=len(decisions),
    )


@app.post("/v1/decisions/export", response_model=AIDecisionExportResponse)
def export_decisions(payload: AIDecisionExportRequest, request: Request) -> AIDecisionExportResponse:
    principal = require_auth(request, config=config, tenant=payload.tenant)
    _require_reports_bucket()
    trace_id = payload.trace_id or str(uuid4())
    generated_at = datetime.now(timezone.utc)

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            conn.commit()
            rows, total = _query_ai_decisions(cur, payload=payload)
            decisions = [_map_ai_decision_row(row) for row in rows]
            decision_context: dict[str, dict[str, Any]] = {}
            if payload.include_context:
                for row in rows:
                    decision_ref_id = int(row["id"])
                    decision_context[str(row["decision_id"])] = {
                        "context_documents": _fetch_ai_decision_context_documents(
                            cur,
                            tenant=payload.tenant,
                            decision_ref_id=decision_ref_id,
                        ),
                        "context_chunks": _fetch_ai_decision_context_chunks(
                            cur,
                            tenant=payload.tenant,
                            decision_ref_id=decision_ref_id,
                        ),
                    }

    export_payload: dict[str, Any] = {
        "trace_id": trace_id,
        "generated_at": generated_at,
        "tenant": payload.tenant,
        "filters": payload.model_dump(
            mode="json",
            exclude={"trace_id", "include_context", "object_name"},
            exclude_none=True,
        ),
        "total": total,
        "returned": len(decisions),
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }
    if payload.include_context:
        export_payload["decision_context"] = decision_context

    report_hash = _sha256_json(export_payload)
    signature_alg = "none"
    signature = None
    signature_key_id = None
    if config.audit_report_signing_key:
        signature_alg = "hmac-sha256"
        signature = _hmac_sha256_b64(config.audit_report_signing_key, export_payload)
        signature_key_id = config.audit_report_signing_key_id or None

    export_document = {
        **export_payload,
        "report_hash_sha256": report_hash,
        "signature_alg": signature_alg,
        "signature_key_id": signature_key_id,
        "signature": signature,
    }
    object_name = _resolve_audit_export_object_name(
        tenant=payload.tenant,
        requested_object_name=payload.object_name,
        trace_id=trace_id,
        generated_at=generated_at,
    )
    upload_result = _upload_json_artifact_immutable(
        bucket_name=config.reports_bucket,
        object_name=object_name,
        payload=export_document,
    )
    gs_uri = str(upload_result["gs_uri"])
    _insert_audit_artifact_records(
        [
            {
                "artifact_id": f"export-{trace_id}",
                "tenant": payload.tenant,
                "artifact_type": "decision_export",
                "gs_uri": gs_uri,
                "object_generation": int(upload_result.get("generation") or 0),
                "metageneration": int(upload_result.get("metageneration") or 0),
                "report_hash_sha256": report_hash,
                "signature_alg": signature_alg,
                "signature_key_id": signature_key_id,
                "created_by": principal.subject if principal else "anonymous",
                "trace_id": trace_id,
                "metadata": {
                    "total": total,
                    "returned": len(decisions),
                    "include_context": payload.include_context,
                },
            }
        ]
    )

    log_event(
        "info",
        "ai_decision_export_written",
        trace_id=trace_id,
        doc_id=decisions[0].context_docs[0] if decisions and decisions[0].context_docs else None,
        job_id=f"ai-decision-export:{payload.tenant}:{trace_id}",
        tenant=payload.tenant,
        total=total,
        returned=len(decisions),
        include_context=payload.include_context,
        gs_uri=gs_uri,
        signature_alg=signature_alg,
    )
    return AIDecisionExportResponse(
        trace_id=trace_id,
        generated_at=generated_at,
        tenant=payload.tenant,
        total=total,
        returned=len(decisions),
        gs_uri=gs_uri,
        report_hash_sha256=report_hash,
        signature_alg=signature_alg,
        signature_key_id=signature_key_id,
        signature=signature,
    )


@app.post("/v1/decisions/bundle", response_model=AIDecisionBundleResponse)
def bundle_decisions(payload: AIDecisionBundleRequest, request: Request) -> AIDecisionBundleResponse:
    principal = require_auth(request, config=config, tenant=payload.tenant)
    _require_reports_bucket()
    trace_id = payload.trace_id or str(uuid4())
    generated_at = datetime.now(timezone.utc)
    bundle_id = f"bundle-{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{trace_id[:8]}"

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            conn.commit()
            rows, total = _query_ai_decisions(cur, payload=payload)
            decisions = [_map_ai_decision_row(row) for row in rows]
            decision_reports: list[dict[str, Any]] = []
            for row, decision in zip(rows, decisions):
                context_documents: list[dict[str, Any]] = []
                context_chunks: list[dict[str, Any]] = []
                if payload.include_context:
                    context_documents = _fetch_ai_decision_context_documents(
                        cur,
                        tenant=payload.tenant,
                        decision_ref_id=int(row["id"]),
                    )
                    context_chunks = _fetch_ai_decision_context_chunks(
                        cur,
                        tenant=payload.tenant,
                        decision_ref_id=int(row["id"]),
                    )

                decision_report_payload = {
                    "decision": decision.model_dump(mode="json"),
                    "context_documents": context_documents,
                    "context_chunks": context_chunks,
                }
                decision_reports.append(
                    {
                        **decision_report_payload,
                        "report_hash_sha256": _sha256_json(decision_report_payload),
                    }
                )

    policy_snapshot = _build_policy_snapshot() if payload.include_policy_snapshot else None

    bundle_payload: dict[str, Any] = {
        "bundle_id": bundle_id,
        "trace_id": trace_id,
        "generated_at": generated_at,
        "tenant": payload.tenant,
        "exported_by": principal.subject if principal else "anonymous",
        "case_id": payload.case_id,
        "regulator_ref": payload.regulator_ref,
        "filters": payload.model_dump(
            mode="json",
            exclude={
                "trace_id",
                "include_context",
                "object_name",
                "case_id",
                "regulator_ref",
                "include_policy_snapshot",
            },
            exclude_none=True,
        ),
        "total": total,
        "returned": len(decision_reports),
        "decision_reports": decision_reports,
    }
    if policy_snapshot is not None:
        bundle_payload["policy_snapshot"] = policy_snapshot

    report_hash = _sha256_json(bundle_payload)
    signature_alg = "none"
    signature = None
    signature_key_id = None
    if config.audit_report_signing_key:
        signature_alg = "hmac-sha256"
        signature = _hmac_sha256_b64(config.audit_report_signing_key, bundle_payload)
        signature_key_id = config.audit_report_signing_key_id or None

    bundle_document = {
        **bundle_payload,
        "report_hash_sha256": report_hash,
        "signature_alg": signature_alg,
        "signature_key_id": signature_key_id,
        "signature": signature,
    }
    object_name = _resolve_audit_bundle_object_name(
        tenant=payload.tenant,
        requested_object_name=payload.object_name,
        trace_id=trace_id,
        generated_at=generated_at,
    )
    upload_result = _upload_json_artifact_immutable(
        bucket_name=config.reports_bucket,
        object_name=object_name,
        payload=bundle_document,
    )
    gs_uri = str(upload_result["gs_uri"])
    _insert_audit_artifact_records(
        [
            {
                "artifact_id": f"bundle-{bundle_id}",
                "tenant": payload.tenant,
                "artifact_type": "decision_bundle",
                "gs_uri": gs_uri,
                "object_generation": int(upload_result.get("generation") or 0),
                "metageneration": int(upload_result.get("metageneration") or 0),
                "report_hash_sha256": report_hash,
                "signature_alg": signature_alg,
                "signature_key_id": signature_key_id,
                "created_by": principal.subject if principal else "anonymous",
                "trace_id": trace_id,
                "metadata": {
                    "bundle_id": bundle_id,
                    "total": total,
                    "returned": len(decision_reports),
                    "case_id": payload.case_id,
                    "regulator_ref": payload.regulator_ref,
                },
            }
        ]
    )

    log_event(
        "info",
        "ai_decision_bundle_written",
        trace_id=trace_id,
        doc_id=decisions[0].context_docs[0] if decisions and decisions[0].context_docs else None,
        job_id=f"ai-decision-bundle:{payload.tenant}:{trace_id}",
        tenant=payload.tenant,
        bundle_id=bundle_id,
        total=total,
        returned=len(decision_reports),
        include_context=payload.include_context,
        include_policy_snapshot=payload.include_policy_snapshot,
        gs_uri=gs_uri,
        signature_alg=signature_alg,
    )
    return AIDecisionBundleResponse(
        trace_id=trace_id,
        bundle_id=bundle_id,
        generated_at=generated_at,
        tenant=payload.tenant,
        total=total,
        returned=len(decision_reports),
        gs_uri=gs_uri,
        report_hash_sha256=report_hash,
        signature_alg=signature_alg,
        signature_key_id=signature_key_id,
        signature=signature,
    )


@app.post("/v1/decisions/package", response_model=AIDecisionPackageResponse)
def package_decisions(payload: AIDecisionPackageRequest, request: Request) -> AIDecisionPackageResponse:
    principal = require_auth(request, config=config, tenant=payload.tenant)
    _require_reports_bucket()
    trace_id = payload.trace_id or str(uuid4())
    generated_at = datetime.now(timezone.utc)
    package_id = payload.package_id or f"pkg-{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{trace_id[:8]}"
    object_prefix = _resolve_audit_package_prefix(
        tenant=payload.tenant,
        requested_object_prefix=payload.object_prefix,
        package_id=package_id,
    )
    artifact_records: list[dict[str, Any]] = []

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            conn.commit()
            rows, total = _query_ai_decisions(cur, payload=payload)
            decisions = [_map_ai_decision_row(row) for row in rows]

            files: list[dict[str, Any]] = []
            for row, decision in zip(rows, decisions):
                context_documents: list[dict[str, Any]] = []
                context_chunks: list[dict[str, Any]] = []
                if payload.include_context:
                    context_documents = _fetch_ai_decision_context_documents(
                        cur,
                        tenant=payload.tenant,
                        decision_ref_id=int(row["id"]),
                    )
                    context_chunks = _fetch_ai_decision_context_chunks(
                        cur,
                        tenant=payload.tenant,
                        decision_ref_id=int(row["id"]),
                    )

                decision_report_payload = {
                    "decision": decision.model_dump(mode="json"),
                    "context_documents": context_documents,
                    "context_chunks": context_chunks,
                }
                decision_report_hash = _sha256_json(decision_report_payload)
                decision_signature_alg = "none"
                decision_signature = None
                decision_signature_key_id = None
                if config.audit_report_signing_key:
                    decision_signature_alg = "hmac-sha256"
                    decision_signature = _hmac_sha256_b64(config.audit_report_signing_key, decision_report_payload)
                    decision_signature_key_id = config.audit_report_signing_key_id or None

                decision_report_document = {
                    **decision_report_payload,
                    "report_hash_sha256": decision_report_hash,
                    "signature_alg": decision_signature_alg,
                    "signature_key_id": decision_signature_key_id,
                    "signature": decision_signature,
                }
                decision_file_id = decision.decision_id.replace("/", "_")
                decision_object_name = safe_object_name(f"{object_prefix}/decision_reports/{decision_file_id}.json")
                decision_upload = _upload_json_artifact_immutable(
                    bucket_name=config.reports_bucket,
                    object_name=decision_object_name,
                    payload=decision_report_document,
                )
                decision_gs_uri = str(decision_upload["gs_uri"])
                artifact_records.append(
                    {
                        "artifact_id": f"pkg-report-{package_id}-{decision.decision_id}",
                        "tenant": payload.tenant,
                        "artifact_type": "decision_report",
                        "gs_uri": decision_gs_uri,
                        "object_generation": int(decision_upload.get("generation") or 0),
                        "metageneration": int(decision_upload.get("metageneration") or 0),
                        "report_hash_sha256": decision_report_hash,
                        "signature_alg": decision_signature_alg,
                        "signature_key_id": decision_signature_key_id,
                        "created_by": principal.subject if principal else "anonymous",
                        "trace_id": trace_id,
                        "metadata": {"package_id": package_id, "decision_id": decision.decision_id},
                    }
                )
                files.append(
                    {
                        "kind": "decision_report",
                        "decision_id": decision.decision_id,
                        "gs_uri": decision_gs_uri,
                        "report_hash_sha256": decision_report_hash,
                        "signature_alg": decision_signature_alg,
                        "signature_key_id": decision_signature_key_id,
                        "signature": decision_signature,
                    }
                )

    if payload.include_policy_snapshot:
        policy_snapshot_payload = _build_policy_snapshot()
        policy_report_hash = _sha256_json(policy_snapshot_payload)
        policy_signature_alg = "none"
        policy_signature = None
        policy_signature_key_id = None
        if config.audit_report_signing_key:
            policy_signature_alg = "hmac-sha256"
            policy_signature = _hmac_sha256_b64(config.audit_report_signing_key, policy_snapshot_payload)
            policy_signature_key_id = config.audit_report_signing_key_id or None
        policy_document = {
            **policy_snapshot_payload,
            "report_hash_sha256": policy_report_hash,
            "signature_alg": policy_signature_alg,
            "signature_key_id": policy_signature_key_id,
            "signature": policy_signature,
        }
        policy_object_name = safe_object_name(f"{object_prefix}/policy_snapshot.json")
        policy_upload = _upload_json_artifact_immutable(
            bucket_name=config.reports_bucket,
            object_name=policy_object_name,
            payload=policy_document,
        )
        policy_gs_uri = str(policy_upload["gs_uri"])
        artifact_records.append(
            {
                "artifact_id": f"pkg-policy-{package_id}",
                "tenant": payload.tenant,
                "artifact_type": "policy_snapshot",
                "gs_uri": policy_gs_uri,
                "object_generation": int(policy_upload.get("generation") or 0),
                "metageneration": int(policy_upload.get("metageneration") or 0),
                "report_hash_sha256": policy_report_hash,
                "signature_alg": policy_signature_alg,
                "signature_key_id": policy_signature_key_id,
                "created_by": principal.subject if principal else "anonymous",
                "trace_id": trace_id,
                "metadata": {"package_id": package_id},
            }
        )
        files.append(
            {
                "kind": "policy_snapshot",
                "gs_uri": policy_gs_uri,
                "report_hash_sha256": policy_report_hash,
                "signature_alg": policy_signature_alg,
                "signature_key_id": policy_signature_key_id,
                "signature": policy_signature,
            }
        )

    manifest_payload: dict[str, Any] = {
        "package_id": package_id,
        "trace_id": trace_id,
        "generated_at": generated_at,
        "tenant": payload.tenant,
        "exported_by": principal.subject if principal else "anonymous",
        "case_id": payload.case_id,
        "regulator_ref": payload.regulator_ref,
        "filters": payload.model_dump(
            mode="json",
            exclude={"trace_id", "package_id", "case_id", "regulator_ref", "object_prefix"},
            exclude_none=True,
        ),
        "total": total,
        "returned": len(decisions),
        "files": files,
    }
    manifest_hash = _sha256_json(manifest_payload)
    manifest_signature_alg = "none"
    manifest_signature = None
    manifest_signature_key_id = None
    if config.audit_report_signing_key:
        manifest_signature_alg = "hmac-sha256"
        manifest_signature = _hmac_sha256_b64(config.audit_report_signing_key, manifest_payload)
        manifest_signature_key_id = config.audit_report_signing_key_id or None

    manifest_document = {
        **manifest_payload,
        "report_hash_sha256": manifest_hash,
        "signature_alg": manifest_signature_alg,
        "signature_key_id": manifest_signature_key_id,
        "signature": manifest_signature,
    }
    manifest_object_name = safe_object_name(f"{object_prefix}/manifest.json")
    manifest_upload = _upload_json_artifact_immutable(
        bucket_name=config.reports_bucket,
        object_name=manifest_object_name,
        payload=manifest_document,
    )
    manifest_gs_uri = str(manifest_upload["gs_uri"])
    artifact_records.append(
        {
            "artifact_id": f"pkg-manifest-{package_id}",
            "tenant": payload.tenant,
            "artifact_type": "regulator_package_manifest",
            "gs_uri": manifest_gs_uri,
            "object_generation": int(manifest_upload.get("generation") or 0),
            "metageneration": int(manifest_upload.get("metageneration") or 0),
            "report_hash_sha256": manifest_hash,
            "signature_alg": manifest_signature_alg,
            "signature_key_id": manifest_signature_key_id,
            "created_by": principal.subject if principal else "anonymous",
            "trace_id": trace_id,
            "metadata": {"package_id": package_id, "files_count": len(files) + 1},
        }
    )
    _insert_audit_artifact_records(artifact_records)

    log_event(
        "info",
        "ai_decision_package_written",
        trace_id=trace_id,
        doc_id=decisions[0].context_docs[0] if decisions and decisions[0].context_docs else None,
        job_id=f"ai-decision-package:{payload.tenant}:{trace_id}",
        tenant=payload.tenant,
        package_id=package_id,
        files_count=len(files) + 1,
        manifest_gs_uri=manifest_gs_uri,
        signature_alg=manifest_signature_alg,
    )
    return AIDecisionPackageResponse(
        trace_id=trace_id,
        package_id=package_id,
        generated_at=generated_at,
        tenant=payload.tenant,
        total=total,
        returned=len(decisions),
        manifest_gs_uri=manifest_gs_uri,
        files_count=len(files) + 1,
        report_hash_sha256=manifest_hash,
        signature_alg=manifest_signature_alg,
        signature_key_id=manifest_signature_key_id,
        signature=manifest_signature,
    )


@app.get("/v1/decisions/{decision_id}/report", response_model=AIDecisionReportResponse)
def get_decision_report(request: Request, decision_id: str, tenant: str = config.default_tenant) -> AIDecisionReportResponse:
    require_auth(request, config=config, tenant=tenant)
    trace_id = str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            conn.commit()
            row = _fetch_ai_decision(cur, tenant=tenant, decision_id=decision_id)
            if not row:
                raise HTTPException(status_code=404, detail="Decision not found")
            context_documents = _fetch_ai_decision_context_documents(cur, tenant=tenant, decision_ref_id=row["id"])
            context_chunks = _fetch_ai_decision_context_chunks(cur, tenant=tenant, decision_ref_id=row["id"])

    decision = _map_ai_decision_row(row)
    report_payload = {
        "decision": decision.model_dump(mode="json"),
        "context_documents": context_documents,
        "context_chunks": context_chunks,
    }
    report_hash = _sha256_json(report_payload)
    signature_alg = "none"
    signature = None
    signature_key_id = None
    if config.audit_report_signing_key:
        signature_alg = "hmac-sha256"
        signature = _hmac_sha256_b64(config.audit_report_signing_key, report_payload)
        signature_key_id = config.audit_report_signing_key_id or None

    log_event(
        "info",
        "ai_decision_report_generated",
        trace_id=trace_id,
        doc_id=decision.context_docs[0] if decision.context_docs else None,
        job_id=f"ai-decision-report:{tenant}:{decision_id}",
        tenant=tenant,
        decision_id=decision_id,
        context_docs=len(decision.context_docs),
        context_chunks=len(decision.context_chunks),
        signature_alg=signature_alg,
    )
    return AIDecisionReportResponse(
        trace_id=trace_id,
        generated_at=datetime.now(timezone.utc),
        decision=decision,
        context_documents=context_documents,
        context_chunks=context_chunks,
        report_hash_sha256=report_hash,
        signature_alg=signature_alg,
        signature_key_id=signature_key_id,
        signature=signature,
    )


@app.post("/v1/decisions/verify", response_model=AIDecisionVerifyResponse)
def verify_decision_artifact(payload: AIDecisionVerifyRequest, request: Request) -> AIDecisionVerifyResponse:
    require_auth(request, config=config, tenant=payload.tenant)
    _require_reports_bucket()
    trace_id = payload.trace_id or str(uuid4())
    errors: list[str] = []

    bucket_name, object_name = parse_gs_uri(payload.gs_uri)
    if bucket_name != config.reports_bucket:
        raise HTTPException(status_code=400, detail="gs_uri bucket does not match REPORTS_BUCKET")
    if payload.strict_tenant_path and not object_name.startswith(f"reports/{payload.tenant}/audit/"):
        raise HTTPException(status_code=403, detail="gs_uri path is outside tenant audit prefix")

    try:
        raw_payload = storage_client.download_bytes(payload.gs_uri)
        document = json.loads(raw_payload.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to load JSON artifact: {exc}") from exc
    if not isinstance(document, dict):
        raise HTTPException(status_code=400, detail="Artifact must be a JSON object")

    stored_hash = document.get("report_hash_sha256")
    signature_alg = str(document.get("signature_alg") or "none")
    signature_key_id = str(document.get("signature_key_id") or "") or None
    signature = str(document.get("signature") or "") or None
    unsigned_payload = dict(document)
    unsigned_payload.pop("report_hash_sha256", None)
    unsigned_payload.pop("signature_alg", None)
    unsigned_payload.pop("signature_key_id", None)
    unsigned_payload.pop("signature", None)

    computed_hash = _sha256_json(unsigned_payload)
    hash_match = isinstance(stored_hash, str) and bool(stored_hash) and hmac.compare_digest(computed_hash, stored_hash)
    if not hash_match:
        errors.append("hash_mismatch")

    expected_hash_match = None
    if payload.expected_report_hash_sha256 is not None:
        expected_hash_match = hmac.compare_digest(computed_hash, payload.expected_report_hash_sha256)
        if not expected_hash_match:
            errors.append("expected_hash_mismatch")

    signature_valid = False
    if signature_alg == "none":
        signature_valid = signature is None
    elif signature_alg == "hmac-sha256":
        if not config.audit_report_signing_key:
            errors.append("signing_key_not_configured")
            signature_valid = False
        elif not signature:
            errors.append("missing_signature")
            signature_valid = False
        else:
            expected_signature = _hmac_sha256_b64(config.audit_report_signing_key, unsigned_payload)
            signature_valid = hmac.compare_digest(signature, expected_signature)
            if not signature_valid:
                errors.append("signature_mismatch")
    else:
        errors.append("unsupported_signature_alg")
        signature_valid = False

    expected_signature_key_match = None
    if payload.expected_signature_key_id is not None:
        expected_signature_key_match = (signature_key_id == payload.expected_signature_key_id)
        if not expected_signature_key_match:
            errors.append("signature_key_id_mismatch")

    report_type = _infer_decision_artifact_type(unsigned_payload)
    verified = hash_match and signature_valid
    if expected_hash_match is not None:
        verified = verified and expected_hash_match
    if expected_signature_key_match is not None:
        verified = verified and expected_signature_key_match

    log_event(
        "info",
        "ai_decision_artifact_verified",
        trace_id=trace_id,
        doc_id=None,
        job_id=f"ai-decision-verify:{payload.tenant}:{trace_id}",
        tenant=payload.tenant,
        gs_uri=payload.gs_uri,
        verified=verified,
        report_type=report_type,
        signature_alg=signature_alg,
        errors=errors,
    )
    return AIDecisionVerifyResponse(
        trace_id=trace_id,
        tenant=payload.tenant,
        gs_uri=payload.gs_uri,
        report_type=report_type,
        verified_at=datetime.now(timezone.utc),
        computed_report_hash_sha256=computed_hash,
        stored_report_hash_sha256=stored_hash if isinstance(stored_hash, str) else None,
        hash_match=hash_match,
        expected_hash_match=expected_hash_match,
        signature_alg=signature_alg,
        signature_key_id=signature_key_id,
        signature_valid=signature_valid,
        expected_signature_key_match=expected_signature_key_match,
        verified=verified,
        errors=errors,
    )


@app.post("/v1/admin/retention-policies", response_model=RetentionPolicyResponse)
def upsert_retention_policy(payload: RetentionPolicyUpsertRequest, request: Request) -> RetentionPolicyResponse:
    principal = require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = payload.trace_id or str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            row = _upsert_retention_policy(
                cur,
                tenant=payload.tenant,
                artifact_type=payload.artifact_type,
                retain_days=payload.retain_days,
                legal_hold_enabled=payload.legal_hold_enabled,
                immutable_required=payload.immutable_required,
                created_by=principal.subject if principal else "anonymous",
            )
            conn.commit()

    policy = _map_retention_policy_row(row)
    log_event(
        "info",
        "retention_policy_upserted",
        trace_id=trace_id,
        doc_id=None,
        job_id=f"retention-policy:{payload.tenant}:{payload.artifact_type}",
        tenant=payload.tenant,
        subject=principal.subject if principal else None,
        retain_days=policy.retain_days,
        immutable_required=policy.immutable_required,
    )
    return RetentionPolicyResponse(trace_id=trace_id, policy=policy)


@app.get("/v1/admin/retention-policies", response_model=RetentionPolicyListResponse)
def list_retention_policies(request: Request, tenant: str | None = None) -> RetentionPolicyListResponse:
    require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            rows = _list_retention_policies(cur, tenant=tenant)

    policies = [_map_retention_policy_row(row) for row in rows]
    return RetentionPolicyListResponse(trace_id=trace_id, tenant=tenant, policies=policies)


@app.post("/v1/admin/legal-holds", response_model=LegalHoldResponse)
def create_legal_hold(payload: LegalHoldCreateRequest, request: Request) -> LegalHoldResponse:
    principal = require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = payload.trace_id or str(uuid4())
    hold_id = f"lh-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{str(uuid4())[:8]}"

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            row = _create_legal_hold(
                cur,
                hold_id=hold_id,
                tenant=payload.tenant,
                scope_type=payload.scope_type,
                scope_id=payload.scope_id,
                reason=payload.reason,
                case_id=payload.case_id,
                regulator_ref=payload.regulator_ref,
                created_by=principal.subject if principal else "anonymous",
            )
            conn.commit()

    hold = _map_legal_hold_row(row)
    log_event(
        "info",
        "legal_hold_created",
        trace_id=trace_id,
        doc_id=payload.scope_id if payload.scope_type == "document" else None,
        job_id=f"legal-hold:{hold.hold_id}",
        tenant=payload.tenant,
        subject=principal.subject if principal else None,
        scope_type=payload.scope_type,
    )
    return LegalHoldResponse(trace_id=trace_id, hold=hold)


@app.post("/v1/admin/legal-holds/release", response_model=LegalHoldResponse)
def release_legal_hold(payload: LegalHoldReleaseRequest, request: Request) -> LegalHoldResponse:
    principal = require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = payload.trace_id or str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            row = _release_legal_hold(cur, hold_id=payload.hold_id)
            if not row:
                raise HTTPException(status_code=404, detail="Legal hold not found")
            conn.commit()

    hold = _map_legal_hold_row(row)
    log_event(
        "info",
        "legal_hold_released",
        trace_id=trace_id,
        doc_id=hold.scope_id if hold.scope_type == "document" else None,
        job_id=f"legal-hold:{hold.hold_id}",
        tenant=hold.tenant,
        subject=principal.subject if principal else None,
        scope_type=hold.scope_type,
    )
    return LegalHoldResponse(trace_id=trace_id, hold=hold)


@app.get("/v1/admin/legal-holds", response_model=LegalHoldListResponse)
def list_legal_holds(request: Request, tenant: str | None = None, active_only: bool = True) -> LegalHoldListResponse:
    require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            rows = _list_legal_holds(cur, tenant=tenant, active_only=active_only)

    holds = [_map_legal_hold_row(row) for row in rows]
    return LegalHoldListResponse(trace_id=trace_id, tenant=tenant, active_only=active_only, holds=holds)


@app.post("/v1/admin/retention/enforce", response_model=RetentionEnforcementResponse)
def enforce_retention(payload: RetentionEnforcementRequest, request: Request) -> RetentionEnforcementResponse:
    principal = require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = payload.trace_id or str(uuid4())
    actor = principal.subject if principal else "anonymous"
    now = datetime.now(timezone.utc)
    job_id = f"retention-enforce:{trace_id}"

    scanned = 0
    eligible = 0
    deleted = 0
    skipped_not_expired = 0
    skipped_on_hold = 0
    skipped_policy_missing = 0
    failed = 0
    items: list[RetentionEnforcementItem] = []

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            candidates = _list_retention_candidates(
                cur,
                tenant=payload.tenant,
                artifact_type=payload.artifact_type,
                limit=payload.limit,
            )
            holds = _list_legal_holds(cur, tenant=payload.tenant, active_only=True)
            scanned = len(candidates)

            for row in candidates:
                policy = _extract_retention_policy_from_candidate(row)
                metadata = row.get("metadata") or {}
                created_at = row["created_at"]

                if policy is None:
                    skipped_policy_missing += 1
                    items.append(
                        RetentionEnforcementItem(
                            artifact_id=str(row["artifact_id"]),
                            tenant=str(row["tenant"]),
                            artifact_type=str(row["artifact_type"]),
                            gs_uri=str(row["gs_uri"]),
                            created_at=created_at,
                            expires_at=created_at,
                            age_days=max(0, int((now - created_at).total_seconds() // 86400)),
                            action="SKIP_POLICY_MISSING",
                            reason="No retention policy configured for tenant/artifact_type",
                        )
                    )
                    continue

                expires_at = created_at + timedelta(days=policy["retain_days"])
                age_days = max(0, int((now - created_at).total_seconds() // 86400))
                if expires_at > now:
                    skipped_not_expired += 1
                    items.append(
                        RetentionEnforcementItem(
                            artifact_id=str(row["artifact_id"]),
                            tenant=str(row["tenant"]),
                            artifact_type=str(row["artifact_type"]),
                            gs_uri=str(row["gs_uri"]),
                            created_at=created_at,
                            expires_at=expires_at,
                            age_days=age_days,
                            action="SKIP_NOT_EXPIRED",
                            reason="Retention period not expired",
                        )
                    )
                    continue

                eligible += 1
                hold_ids = (
                    _matching_legal_hold_ids_for_artifact(
                        artifact_tenant=str(row["tenant"]),
                        artifact_id=str(row["artifact_id"]),
                        gs_uri=str(row["gs_uri"]),
                        metadata=metadata,
                        holds=holds,
                    )
                    if policy["legal_hold_enabled"]
                    else []
                )
                if hold_ids:
                    skipped_on_hold += 1
                    items.append(
                        RetentionEnforcementItem(
                            artifact_id=str(row["artifact_id"]),
                            tenant=str(row["tenant"]),
                            artifact_type=str(row["artifact_type"]),
                            gs_uri=str(row["gs_uri"]),
                            created_at=created_at,
                            expires_at=expires_at,
                            age_days=age_days,
                            action="SKIP_LEGAL_HOLD",
                            reason="Active legal hold protects artifact",
                            hold_ids=hold_ids,
                        )
                    )
                    continue

                if payload.dry_run:
                    items.append(
                        RetentionEnforcementItem(
                            artifact_id=str(row["artifact_id"]),
                            tenant=str(row["tenant"]),
                            artifact_type=str(row["artifact_type"]),
                            gs_uri=str(row["gs_uri"]),
                            created_at=created_at,
                            expires_at=expires_at,
                            age_days=age_days,
                            action="WOULD_DELETE",
                            reason="Retention expired and no active legal hold",
                        )
                    )
                    continue

                try:
                    storage_deleted = storage_client.delete_gs_uri(
                        str(row["gs_uri"]),
                        if_generation_match=row.get("object_generation"),
                    )
                    _mark_audit_artifact_deleted(
                        cur,
                        artifact_id=str(row["artifact_id"]),
                        tenant=str(row["tenant"]),
                        artifact_type=str(row["artifact_type"]),
                        gs_uri=str(row["gs_uri"]),
                        deletion_reason="retention_expired",
                        deleted_by=actor,
                        delete_job_id=job_id,
                        storage_deleted=storage_deleted,
                    )
                    deleted += 1
                    items.append(
                        RetentionEnforcementItem(
                            artifact_id=str(row["artifact_id"]),
                            tenant=str(row["tenant"]),
                            artifact_type=str(row["artifact_type"]),
                            gs_uri=str(row["gs_uri"]),
                            created_at=created_at,
                            expires_at=expires_at,
                            age_days=age_days,
                            action="DELETED",
                            reason="Retention expired and artifact removed",
                        )
                    )
                except Exception as exc:
                    failed += 1
                    items.append(
                        RetentionEnforcementItem(
                            artifact_id=str(row["artifact_id"]),
                            tenant=str(row["tenant"]),
                            artifact_type=str(row["artifact_type"]),
                            gs_uri=str(row["gs_uri"]),
                            created_at=created_at,
                            expires_at=expires_at,
                            age_days=age_days,
                            action="DELETE_FAILED",
                            reason="Retention expired but deletion failed",
                            error=str(exc),
                        )
                    )
            conn.commit()

    log_event(
        "info",
        "retention_enforcement_completed",
        trace_id=trace_id,
        doc_id=None,
        job_id=job_id,
        tenant=payload.tenant or "*",
        actor=actor,
        dry_run=payload.dry_run,
        scanned=scanned,
        eligible=eligible,
        deleted=deleted,
        skipped_not_expired=skipped_not_expired,
        skipped_on_hold=skipped_on_hold,
        skipped_policy_missing=skipped_policy_missing,
        failed=failed,
    )
    return RetentionEnforcementResponse(
        trace_id=trace_id,
        dry_run=payload.dry_run,
        tenant=payload.tenant,
        artifact_type=payload.artifact_type,
        scanned=scanned,
        eligible=eligible,
        deleted=deleted,
        skipped_not_expired=skipped_not_expired,
        skipped_on_hold=skipped_on_hold,
        skipped_policy_missing=skipped_policy_missing,
        failed=failed,
        items=items,
    )


@app.post("/v1/admin/decisions/query", response_model=AIDecisionAdminQueryResponse)
def query_decisions_admin(payload: AIDecisionAdminQueryRequest, request: Request) -> AIDecisionAdminQueryResponse:
    principal = require_auth(request, config=config)
    _require_admin_api_key(request)
    trace_id = payload.trace_id or str(uuid4())

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            conn.commit()
            rows, total = _query_ai_decisions_admin(cur, payload=payload)

    decisions = [_map_ai_decision_row(row) for row in rows]
    log_event(
        "info",
        "ai_decision_admin_query_completed",
        trace_id=trace_id,
        doc_id=decisions[0].context_docs[0] if decisions and decisions[0].context_docs else None,
        job_id=f"ai-decision-admin-query:{trace_id}",
        tenant="*",
        subject=principal.subject if principal else None,
        tenants=payload.tenants,
        offset=payload.offset,
        limit=payload.limit,
        returned=len(decisions),
        total=total,
    )
    return AIDecisionAdminQueryResponse(
        trace_id=trace_id,
        tenants=payload.tenants,
        decisions=decisions,
        total=total,
        offset=payload.offset,
        limit=payload.limit,
        returned=len(decisions),
    )


@app.post("/v1/admin/replay-dlq", response_model=DlqReplayResponse)
def replay_dlq(request: DlqReplayRequest, raw_request: Request) -> DlqReplayResponse:
    require_auth(raw_request, config=config)
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
    require_auth(request, config=config, tenant=payload.tenant)
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
    require_auth(request, config=config, tenant=tenant)
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


def _ensure_ai_decision_schema(cur: Any) -> None:
    global _ai_schema_initialized
    if _ai_schema_initialized:
        return
    with _ai_schema_lock:
        if _ai_schema_initialized:
            return
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_decisions (
              id BIGSERIAL PRIMARY KEY,
              decision_id TEXT NOT NULL,
              tenant TEXT NOT NULL,
              model TEXT NOT NULL,
              model_version TEXT,
              input_text TEXT NOT NULL,
              output_text TEXT NOT NULL,
              confidence DOUBLE PRECISION,
              trace_id TEXT NOT NULL,
              metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              CONSTRAINT chk_ai_decisions_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
              UNIQUE (tenant, decision_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_decision_context_docs (
              id BIGSERIAL PRIMARY KEY,
              decision_ref_id BIGINT NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE,
              tenant TEXT NOT NULL,
              doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE RESTRICT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (decision_ref_id, doc_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_decision_context_chunks (
              id BIGSERIAL PRIMARY KEY,
              decision_ref_id BIGINT NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE,
              tenant TEXT NOT NULL,
              chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE RESTRICT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (decision_ref_id, chunk_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS retention_policies (
              id BIGSERIAL PRIMARY KEY,
              tenant TEXT NOT NULL,
              artifact_type TEXT NOT NULL,
              retain_days INTEGER NOT NULL CHECK (retain_days > 0),
              legal_hold_enabled BOOLEAN NOT NULL DEFAULT TRUE,
              immutable_required BOOLEAN NOT NULL DEFAULT TRUE,
              created_by TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (tenant, artifact_type)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_holds (
              id BIGSERIAL PRIMARY KEY,
              hold_id TEXT NOT NULL UNIQUE,
              tenant TEXT NOT NULL,
              scope_type TEXT NOT NULL,
              scope_id TEXT NOT NULL,
              reason TEXT NOT NULL,
              case_id TEXT,
              regulator_ref TEXT,
              created_by TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              released_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_artifacts (
              id BIGSERIAL PRIMARY KEY,
              artifact_id TEXT NOT NULL,
              tenant TEXT NOT NULL,
              artifact_type TEXT NOT NULL,
              gs_uri TEXT NOT NULL,
              object_generation BIGINT,
              metageneration BIGINT,
              report_hash_sha256 TEXT NOT NULL,
              signature_alg TEXT NOT NULL,
              signature_key_id TEXT,
              immutable_write BOOLEAN NOT NULL DEFAULT TRUE,
              created_by TEXT NOT NULL,
              trace_id TEXT NOT NULL,
              metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
              deleted_at TIMESTAMPTZ,
              deleted_by TEXT,
              deletion_reason TEXT,
              delete_job_id TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (tenant, artifact_type, gs_uri)
            )
            """
        )
        cur.execute("ALTER TABLE audit_artifacts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE audit_artifacts ADD COLUMN IF NOT EXISTS deleted_by TEXT")
        cur.execute("ALTER TABLE audit_artifacts ADD COLUMN IF NOT EXISTS deletion_reason TEXT")
        cur.execute("ALTER TABLE audit_artifacts ADD COLUMN IF NOT EXISTS delete_job_id TEXT")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_model_created_at ON ai_decisions (tenant, model, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_created_at ON ai_decisions (tenant, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_model_version_created_at ON ai_decisions (tenant, model_version, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_confidence_created_at ON ai_decisions (tenant, confidence, created_at DESC)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_decisions_trace_id ON ai_decisions (trace_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_trace_id ON ai_decisions (tenant, trace_id)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_output_created_at ON ai_decisions (tenant, output_text, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decision_context_docs_tenant_doc ON ai_decision_context_docs (tenant, doc_id, decision_ref_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_decision_context_chunks_tenant_chunk ON ai_decision_context_chunks (tenant, chunk_id, decision_ref_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_retention_policies_tenant_artifact_type ON retention_policies (tenant, artifact_type)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_legal_holds_tenant_active_created_at ON legal_holds (tenant, released_at, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_legal_holds_scope ON legal_holds (tenant, scope_type, scope_id, released_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_artifacts_tenant_type_created_at ON audit_artifacts (tenant, artifact_type, created_at DESC)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_artifacts_trace_id ON audit_artifacts (trace_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_artifacts_deleted_at ON audit_artifacts (deleted_at, created_at)")
        _ai_schema_initialized = True


def _missing_document_ids(cur: Any, *, tenant: str, doc_ids: list[str]) -> list[str]:
    cur.execute(
        "SELECT doc_id FROM documents WHERE tenant = %s AND doc_id = ANY(%s)",
        (tenant, doc_ids),
    )
    found = {str(row["doc_id"]) for row in cur.fetchall()}
    return [doc_id for doc_id in doc_ids if doc_id not in found]


def _validate_context_chunks(
    cur: Any,
    *,
    tenant: str,
    chunk_ids: list[str],
    allowed_doc_ids: list[str],
) -> tuple[list[str], list[str]]:
    if not chunk_ids:
        return [], []
    cur.execute(
        "SELECT chunk_id, doc_id FROM chunks WHERE tenant = %s AND chunk_id = ANY(%s)",
        (tenant, chunk_ids),
    )
    rows = cur.fetchall()
    by_chunk_id = {str(row["chunk_id"]): str(row["doc_id"]) for row in rows}
    missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in by_chunk_id]
    allowed_docs = set(allowed_doc_ids)
    mismatched = [chunk_id for chunk_id, doc_id in by_chunk_id.items() if doc_id not in allowed_docs]
    return missing, mismatched


def _upsert_ai_decision(
    cur: Any,
    *,
    payload: AIDecisionIngestRequest,
    trace_id: str,
) -> tuple[int, datetime, datetime]:
    cur.execute(
        """
        INSERT INTO ai_decisions (
          decision_id, tenant, model, model_version, input_text, output_text,
          confidence, trace_id, metadata, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (tenant, decision_id)
        DO UPDATE SET
          model = EXCLUDED.model,
          model_version = EXCLUDED.model_version,
          input_text = EXCLUDED.input_text,
          output_text = EXCLUDED.output_text,
          confidence = EXCLUDED.confidence,
          trace_id = EXCLUDED.trace_id,
          metadata = EXCLUDED.metadata,
          updated_at = NOW()
        RETURNING id, created_at, updated_at
        """,
        (
            payload.decision_id,
            payload.tenant,
            payload.model,
            payload.model_version,
            payload.input,
            payload.output,
            payload.confidence,
            trace_id,
            Json(payload.metadata or {}),
        ),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Unable to persist AI decision")
    return int(row["id"]), row["created_at"], row["updated_at"]


def _replace_ai_decision_context_docs(cur: Any, *, decision_ref_id: int, tenant: str, doc_ids: list[str]) -> None:
    cur.execute(
        "DELETE FROM ai_decision_context_docs WHERE decision_ref_id = %s AND tenant = %s",
        (decision_ref_id, tenant),
    )
    for doc_id in doc_ids:
        cur.execute(
            """
            INSERT INTO ai_decision_context_docs (decision_ref_id, tenant, doc_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (decision_ref_id, doc_id) DO NOTHING
            """,
            (decision_ref_id, tenant, doc_id),
        )


def _replace_ai_decision_context_chunks(cur: Any, *, decision_ref_id: int, tenant: str, chunk_ids: list[str]) -> None:
    cur.execute(
        "DELETE FROM ai_decision_context_chunks WHERE decision_ref_id = %s AND tenant = %s",
        (decision_ref_id, tenant),
    )
    for chunk_id in chunk_ids:
        cur.execute(
            """
            INSERT INTO ai_decision_context_chunks (decision_ref_id, tenant, chunk_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (decision_ref_id, chunk_id) DO NOTHING
            """,
            (decision_ref_id, tenant, chunk_id),
        )


def _query_ai_decisions(cur: Any, *, payload: AIDecisionQueryRequest) -> tuple[list[dict[str, Any]], int]:
    conditions = ["d.tenant = %s"]
    params: list[Any] = [payload.tenant]

    if payload.decision_id_prefix:
        conditions.append("d.decision_id ILIKE %s")
        params.append(f"{payload.decision_id_prefix.strip()}%")
    if payload.decision_ids:
        conditions.append("d.decision_id = ANY(%s)")
        params.append(payload.decision_ids)
    if payload.model:
        conditions.append("d.model = %s")
        params.append(payload.model)
    if payload.model_version:
        conditions.append("d.model_version = %s")
        params.append(payload.model_version)
    if payload.outputs:
        conditions.append("d.output_text = ANY(%s)")
        params.append(payload.outputs)
    if payload.decision_trace_id:
        conditions.append("d.trace_id = %s")
        params.append(payload.decision_trace_id)
    if payload.query:
        pattern = f"%{payload.query.strip()}%"
        conditions.append("(d.input_text ILIKE %s OR d.output_text ILIKE %s)")
        params.extend([pattern, pattern])
    if payload.min_confidence is not None:
        conditions.append("d.confidence >= %s")
        params.append(payload.min_confidence)
    if payload.max_confidence is not None:
        conditions.append("d.confidence <= %s")
        params.append(payload.max_confidence)
    if payload.confidence_band is not None:
        if payload.confidence_band.value == "low":
            conditions.append("d.confidence IS NOT NULL AND d.confidence < 0.40")
        elif payload.confidence_band.value == "medium":
            conditions.append("d.confidence >= 0.40 AND d.confidence < 0.70")
        else:
            conditions.append("d.confidence >= 0.70")
    if payload.created_from is not None:
        conditions.append("d.created_at >= %s")
        params.append(payload.created_from)
    if payload.created_to is not None:
        conditions.append("d.created_at <= %s")
        params.append(payload.created_to)
    if payload.context_docs:
        for doc_id in payload.context_docs:
            conditions.append(
                "EXISTS (SELECT 1 FROM ai_decision_context_docs filter_docs "
                "WHERE filter_docs.decision_ref_id = d.id AND filter_docs.doc_id = %s)"
            )
            params.append(doc_id)
    if payload.context_chunks:
        for chunk_id in payload.context_chunks:
            conditions.append(
                "EXISTS (SELECT 1 FROM ai_decision_context_chunks filter_chunks "
                "WHERE filter_chunks.decision_ref_id = d.id AND filter_chunks.chunk_id = %s)"
            )
            params.append(chunk_id)

    where_clause = " AND ".join(conditions)
    cur.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM ai_decisions d
        WHERE {where_clause}
        """,
        params,
    )
    total_row = cur.fetchone() or {"total": 0}
    total = int(total_row.get("total") or 0)
    if total == 0:
        return [], 0

    order_sql = "ASC" if payload.order.value == "asc" else "DESC"
    query_params = [*params, payload.limit, payload.offset]
    cur.execute(
        f"""
        SELECT
          d.id,
          d.decision_id,
          d.tenant,
          d.model,
          d.model_version,
          d.input_text,
          d.output_text,
          d.confidence,
          d.trace_id,
          d.metadata,
          d.created_at,
          d.updated_at,
          COALESCE(array_agg(DISTINCT cd.doc_id) FILTER (WHERE cd.doc_id IS NOT NULL), ARRAY[]::TEXT[]) AS context_docs,
          COALESCE(array_agg(DISTINCT cc.chunk_id) FILTER (WHERE cc.chunk_id IS NOT NULL), ARRAY[]::TEXT[]) AS context_chunks
        FROM ai_decisions d
        LEFT JOIN ai_decision_context_docs cd ON cd.decision_ref_id = d.id
        LEFT JOIN ai_decision_context_chunks cc ON cc.decision_ref_id = d.id
        WHERE {where_clause}
        GROUP BY d.id
        ORDER BY d.created_at {order_sql}, d.id {order_sql}
        LIMIT %s OFFSET %s
        """,
        query_params,
    )
    return cur.fetchall(), total


def _query_ai_decisions_admin(cur: Any, *, payload: AIDecisionAdminQueryRequest) -> tuple[list[dict[str, Any]], int]:
    conditions = ["d.tenant = ANY(%s)"]
    params: list[Any] = [payload.tenants]

    if payload.decision_id_prefix:
        conditions.append("d.decision_id ILIKE %s")
        params.append(f"{payload.decision_id_prefix.strip()}%")
    if payload.decision_ids:
        conditions.append("d.decision_id = ANY(%s)")
        params.append(payload.decision_ids)
    if payload.model:
        conditions.append("d.model = %s")
        params.append(payload.model)
    if payload.model_version:
        conditions.append("d.model_version = %s")
        params.append(payload.model_version)
    if payload.outputs:
        conditions.append("d.output_text = ANY(%s)")
        params.append(payload.outputs)
    if payload.decision_trace_id:
        conditions.append("d.trace_id = %s")
        params.append(payload.decision_trace_id)
    if payload.query:
        pattern = f"%{payload.query.strip()}%"
        conditions.append("(d.input_text ILIKE %s OR d.output_text ILIKE %s)")
        params.extend([pattern, pattern])
    if payload.min_confidence is not None:
        conditions.append("d.confidence >= %s")
        params.append(payload.min_confidence)
    if payload.max_confidence is not None:
        conditions.append("d.confidence <= %s")
        params.append(payload.max_confidence)
    if payload.confidence_band is not None:
        if payload.confidence_band.value == "low":
            conditions.append("d.confidence IS NOT NULL AND d.confidence < 0.40")
        elif payload.confidence_band.value == "medium":
            conditions.append("d.confidence >= 0.40 AND d.confidence < 0.70")
        else:
            conditions.append("d.confidence >= 0.70")
    if payload.created_from is not None:
        conditions.append("d.created_at >= %s")
        params.append(payload.created_from)
    if payload.created_to is not None:
        conditions.append("d.created_at <= %s")
        params.append(payload.created_to)
    if payload.context_docs:
        for doc_id in payload.context_docs:
            conditions.append(
                "EXISTS (SELECT 1 FROM ai_decision_context_docs filter_docs "
                "WHERE filter_docs.decision_ref_id = d.id AND filter_docs.doc_id = %s)"
            )
            params.append(doc_id)
    if payload.context_chunks:
        for chunk_id in payload.context_chunks:
            conditions.append(
                "EXISTS (SELECT 1 FROM ai_decision_context_chunks filter_chunks "
                "WHERE filter_chunks.decision_ref_id = d.id AND filter_chunks.chunk_id = %s)"
            )
            params.append(chunk_id)

    where_clause = " AND ".join(conditions)
    cur.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM ai_decisions d
        WHERE {where_clause}
        """,
        params,
    )
    total_row = cur.fetchone() or {"total": 0}
    total = int(total_row.get("total") or 0)
    if total == 0:
        return [], 0

    order_sql = "ASC" if payload.order.value == "asc" else "DESC"
    query_params = [*params, payload.limit, payload.offset]
    cur.execute(
        f"""
        SELECT
          d.id,
          d.decision_id,
          d.tenant,
          d.model,
          d.model_version,
          d.input_text,
          d.output_text,
          d.confidence,
          d.trace_id,
          d.metadata,
          d.created_at,
          d.updated_at,
          COALESCE(array_agg(DISTINCT cd.doc_id) FILTER (WHERE cd.doc_id IS NOT NULL), ARRAY[]::TEXT[]) AS context_docs,
          COALESCE(array_agg(DISTINCT cc.chunk_id) FILTER (WHERE cc.chunk_id IS NOT NULL), ARRAY[]::TEXT[]) AS context_chunks
        FROM ai_decisions d
        LEFT JOIN ai_decision_context_docs cd ON cd.decision_ref_id = d.id
        LEFT JOIN ai_decision_context_chunks cc ON cc.decision_ref_id = d.id
        WHERE {where_clause}
        GROUP BY d.id
        ORDER BY d.created_at {order_sql}, d.id {order_sql}
        LIMIT %s OFFSET %s
        """,
        query_params,
    )
    return cur.fetchall(), total


def _fetch_ai_decision(cur: Any, *, tenant: str, decision_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT
          d.id,
          d.decision_id,
          d.tenant,
          d.model,
          d.model_version,
          d.input_text,
          d.output_text,
          d.confidence,
          d.trace_id,
          d.metadata,
          d.created_at,
          d.updated_at,
          COALESCE(array_agg(DISTINCT cd.doc_id) FILTER (WHERE cd.doc_id IS NOT NULL), ARRAY[]::TEXT[]) AS context_docs,
          COALESCE(array_agg(DISTINCT cc.chunk_id) FILTER (WHERE cc.chunk_id IS NOT NULL), ARRAY[]::TEXT[]) AS context_chunks
        FROM ai_decisions d
        LEFT JOIN ai_decision_context_docs cd ON cd.decision_ref_id = d.id
        LEFT JOIN ai_decision_context_chunks cc ON cc.decision_ref_id = d.id
        WHERE d.tenant = %s AND d.decision_id = %s
        GROUP BY d.id
        """,
        (tenant, decision_id),
    )
    return cur.fetchone()


def _fetch_ai_decision_context_documents(cur: Any, *, tenant: str, decision_ref_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT d.doc_id, d.source_uri, d.mime_type, d.size_bytes, d.updated_at
        FROM ai_decision_context_docs c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE c.decision_ref_id = %s AND c.tenant = %s AND d.tenant = %s
        ORDER BY d.doc_id ASC
        """,
        (decision_ref_id, tenant, tenant),
    )
    return cur.fetchall()


def _fetch_ai_decision_context_chunks(cur: Any, *, tenant: str, decision_ref_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT ch.chunk_id, ch.doc_id, ch.chunk_index, ch.token_count, LEFT(ch.chunk_text, 280) AS preview
        FROM ai_decision_context_chunks c
        JOIN chunks ch ON ch.chunk_id = c.chunk_id
        WHERE c.decision_ref_id = %s AND c.tenant = %s AND ch.tenant = %s
        ORDER BY ch.doc_id ASC, ch.chunk_index ASC
        """,
        (decision_ref_id, tenant, tenant),
    )
    return cur.fetchall()


def _map_ai_decision_row(row: dict[str, Any]) -> AIDecisionRecord:
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return AIDecisionRecord(
        decision_id=str(row["decision_id"]),
        tenant=str(row["tenant"]),
        model=str(row["model"]),
        model_version=row.get("model_version"),
        input=str(row["input_text"]),
        output=str(row["output_text"]),
        confidence=row.get("confidence"),
        trace_id=str(row["trace_id"]),
        metadata=metadata,
        context_docs=[str(item) for item in (row.get("context_docs") or [])],
        context_chunks=[str(item) for item in (row.get("context_chunks") or [])],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _sha256_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _hmac_sha256_b64(secret: str, payload: dict[str, Any]) -> str:
    digest = hmac.new(secret.encode("utf-8"), _canonical_json_bytes(payload), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _resolve_audit_export_object_name(
    *,
    tenant: str,
    requested_object_name: str | None,
    trace_id: str,
    generated_at: datetime,
) -> str:
    if requested_object_name:
        value = requested_object_name.strip().lstrip("/")
        if not value:
            raise HTTPException(status_code=400, detail="object_name cannot be empty")
        return safe_object_name(value)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return safe_object_name(f"reports/{tenant}/audit/decisions_export_{stamp}_{trace_id}.json")


def _resolve_audit_bundle_object_name(
    *,
    tenant: str,
    requested_object_name: str | None,
    trace_id: str,
    generated_at: datetime,
) -> str:
    if requested_object_name:
        value = requested_object_name.strip().lstrip("/")
        if not value:
            raise HTTPException(status_code=400, detail="object_name cannot be empty")
        return safe_object_name(value)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return safe_object_name(f"reports/{tenant}/audit/bundles/decision_bundle_{stamp}_{trace_id}.json")


def _resolve_audit_package_prefix(*, tenant: str, requested_object_prefix: str | None, package_id: str) -> str:
    if requested_object_prefix:
        value = requested_object_prefix.strip().lstrip("/").rstrip("/")
        if not value:
            raise HTTPException(status_code=400, detail="object_prefix cannot be empty")
        return safe_object_name(value)
    return safe_object_name(f"reports/{tenant}/audit/packages/{package_id}")


def _build_policy_snapshot() -> dict[str, Any]:
    return {
        "auth_enabled": config.auth_enabled,
        "auth_issuer": config.auth_issuer,
        "auth_audiences": list(config.auth_audiences),
        "auth_require_tenant_claim": config.auth_require_tenant_claim,
        "enforce_storage_hardening": config.enforce_storage_hardening,
        "pubsub_push_auth_enabled": config.pubsub_push_auth_enabled,
        "cloud_run_revision": os.getenv("K_REVISION", ""),
        "cloud_run_service": os.getenv("K_SERVICE", ""),
    }


def _infer_decision_artifact_type(payload: dict[str, Any]) -> str:
    if "package_id" in payload and "files" in payload:
        return "regulator_package_manifest"
    if "bundle_id" in payload and "decision_reports" in payload:
        return "decision_bundle"
    if "decisions" in payload and "filters" in payload:
        return "decision_export"
    if "decision" in payload and "context_documents" in payload:
        return "decision_report"
    if "auth_enabled" in payload and "cloud_run_revision" in payload:
        return "policy_snapshot"
    return "unknown"


def _serialize_json_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=_json_default).encode("utf-8")


def _upload_json_artifact_immutable(
    *,
    bucket_name: str,
    object_name: str,
    payload: dict[str, Any],
) -> dict[str, str | int]:
    try:
        return storage_client.upload_bytes_immutable(
            bucket_name=bucket_name,
            object_name=object_name,
            payload=_serialize_json_payload(payload),
            content_type="application/json",
        )
    except PreconditionFailed as exc:
        raise HTTPException(status_code=409, detail=f"Artifact already exists at gs://{bucket_name}/{object_name}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to write artifact: {exc}") from exc


def _insert_audit_artifact_records(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            _ensure_ai_decision_schema(cur)
            for item in records:
                cur.execute(
                    """
                    INSERT INTO audit_artifacts (
                      artifact_id, tenant, artifact_type, gs_uri, object_generation, metageneration,
                      report_hash_sha256, signature_alg, signature_key_id, immutable_write,
                      created_by, trace_id, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                    ON CONFLICT (tenant, artifact_type, gs_uri) DO NOTHING
                    """,
                    (
                        item["artifact_id"],
                        item["tenant"],
                        item["artifact_type"],
                        item["gs_uri"],
                        item.get("object_generation"),
                        item.get("metageneration"),
                        item["report_hash_sha256"],
                        item["signature_alg"],
                        item.get("signature_key_id"),
                        item["created_by"],
                        item["trace_id"],
                        Json(item.get("metadata") or {}),
                    ),
                )
            conn.commit()


def _upsert_retention_policy(
    cur: Any,
    *,
    tenant: str,
    artifact_type: str,
    retain_days: int,
    legal_hold_enabled: bool,
    immutable_required: bool,
    created_by: str,
) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO retention_policies (
          tenant, artifact_type, retain_days, legal_hold_enabled, immutable_required, created_by, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (tenant, artifact_type)
        DO UPDATE SET
          retain_days = EXCLUDED.retain_days,
          legal_hold_enabled = EXCLUDED.legal_hold_enabled,
          immutable_required = EXCLUDED.immutable_required,
          created_by = EXCLUDED.created_by,
          updated_at = NOW()
        RETURNING tenant, artifact_type, retain_days, legal_hold_enabled, immutable_required, created_by, created_at, updated_at
        """,
        (tenant, artifact_type, retain_days, legal_hold_enabled, immutable_required, created_by),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Unable to upsert retention policy")
    return row


def _list_retention_policies(cur: Any, *, tenant: str | None = None) -> list[dict[str, Any]]:
    if tenant:
        cur.execute(
            """
            SELECT tenant, artifact_type, retain_days, legal_hold_enabled, immutable_required, created_by, created_at, updated_at
            FROM retention_policies
            WHERE tenant = %s
            ORDER BY artifact_type ASC
            """,
            (tenant,),
        )
    else:
        cur.execute(
            """
            SELECT tenant, artifact_type, retain_days, legal_hold_enabled, immutable_required, created_by, created_at, updated_at
            FROM retention_policies
            ORDER BY tenant ASC, artifact_type ASC
            """
        )
    return cur.fetchall()


def _create_legal_hold(
    cur: Any,
    *,
    hold_id: str,
    tenant: str,
    scope_type: str,
    scope_id: str,
    reason: str,
    case_id: str | None,
    regulator_ref: str | None,
    created_by: str,
) -> dict[str, Any]:
    cur.execute(
        """
        INSERT INTO legal_holds (
          hold_id, tenant, scope_type, scope_id, reason, case_id, regulator_ref, created_by, created_at, released_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NULL)
        RETURNING hold_id, tenant, scope_type, scope_id, reason, case_id, regulator_ref, created_by, created_at, released_at
        """,
        (hold_id, tenant, scope_type, scope_id, reason, case_id, regulator_ref, created_by),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Unable to create legal hold")
    return row


def _release_legal_hold(cur: Any, *, hold_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        UPDATE legal_holds
        SET released_at = COALESCE(released_at, NOW())
        WHERE hold_id = %s
        RETURNING hold_id, tenant, scope_type, scope_id, reason, case_id, regulator_ref, created_by, created_at, released_at
        """,
        (hold_id,),
    )
    return cur.fetchone()


def _list_legal_holds(cur: Any, *, tenant: str | None, active_only: bool) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if tenant:
        conditions.append("tenant = %s")
        params.append(tenant)
    if active_only:
        conditions.append("released_at IS NULL")
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cur.execute(
        f"""
        SELECT hold_id, tenant, scope_type, scope_id, reason, case_id, regulator_ref, created_by, created_at, released_at
        FROM legal_holds
        {where_clause}
        ORDER BY created_at DESC
        """,
        params,
    )
    return cur.fetchall()


def _list_retention_candidates(
    cur: Any,
    *,
    tenant: str | None,
    artifact_type: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    conditions = ["a.deleted_at IS NULL"]
    params: list[Any] = []
    if tenant:
        conditions.append("a.tenant = %s")
        params.append(tenant)
    if artifact_type:
        conditions.append("a.artifact_type = %s")
        params.append(artifact_type)
    where_clause = f"WHERE {' AND '.join(conditions)}"
    params.append(limit)
    cur.execute(
        f"""
        SELECT
          a.artifact_id,
          a.tenant,
          a.artifact_type,
          a.gs_uri,
          a.object_generation,
          a.created_at,
          a.metadata,
          p.retain_days AS policy_retain_days,
          p.legal_hold_enabled AS policy_legal_hold_enabled,
          p.immutable_required AS policy_immutable_required
        FROM audit_artifacts a
        LEFT JOIN retention_policies p
          ON p.tenant = a.tenant
         AND p.artifact_type = a.artifact_type
        {where_clause}
        ORDER BY a.created_at ASC
        LIMIT %s
        """,
        params,
    )
    return cur.fetchall()


def _extract_retention_policy_from_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    retain_days = row.get("policy_retain_days")
    if retain_days is None:
        return None
    return {
        "retain_days": int(retain_days),
        "legal_hold_enabled": bool(row.get("policy_legal_hold_enabled")),
        "immutable_required": bool(row.get("policy_immutable_required", True)),
    }


def _matching_legal_hold_ids_for_artifact(
    *,
    artifact_tenant: str,
    artifact_id: str,
    gs_uri: str,
    metadata: dict[str, Any],
    holds: list[dict[str, Any]],
) -> list[str]:
    hold_ids: list[str] = []
    decision_id = str(metadata.get("decision_id") or "").strip()
    case_id = str(metadata.get("case_id") or "").strip()
    decision_ids = {str(item).strip() for item in (metadata.get("decision_ids") or []) if str(item).strip()}
    context_docs = {str(item).strip() for item in (metadata.get("context_docs") or []) if str(item).strip()}

    for hold in holds:
        if str(hold["tenant"]) != artifact_tenant:
            continue
        scope_type = str(hold["scope_type"]).strip().lower()
        scope_id = str(hold["scope_id"]).strip()
        if not scope_type or not scope_id:
            continue

        matches = False
        if scope_type == "tenant":
            matches = scope_id in {artifact_tenant, "*"}
        elif scope_type == "artifact":
            matches = scope_id in {artifact_id, gs_uri}
        elif scope_type == "decision":
            matches = scope_id == decision_id or scope_id in decision_ids
        elif scope_type == "document":
            matches = scope_id in context_docs
        elif scope_type == "case":
            matches = scope_id == case_id

        if matches:
            hold_ids.append(str(hold["hold_id"]))
    return hold_ids


def _mark_audit_artifact_deleted(
    cur: Any,
    *,
    artifact_id: str,
    tenant: str,
    artifact_type: str,
    gs_uri: str,
    deletion_reason: str,
    deleted_by: str,
    delete_job_id: str,
    storage_deleted: bool,
) -> None:
    cur.execute(
        """
        UPDATE audit_artifacts
        SET
          deleted_at = COALESCE(deleted_at, NOW()),
          deleted_by = %s,
          deletion_reason = %s,
          delete_job_id = %s,
          metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb),
            '{retention_delete,storage_deleted}',
            to_jsonb(%s::boolean),
            true
          )
        WHERE artifact_id = %s
          AND tenant = %s
          AND artifact_type = %s
          AND gs_uri = %s
          AND deleted_at IS NULL
        """,
        (deleted_by, deletion_reason, delete_job_id, storage_deleted, artifact_id, tenant, artifact_type, gs_uri),
    )


def _map_retention_policy_row(row: dict[str, Any]) -> RetentionPolicyRecord:
    return RetentionPolicyRecord(
        tenant=str(row["tenant"]),
        artifact_type=str(row["artifact_type"]),
        retain_days=int(row["retain_days"]),
        legal_hold_enabled=bool(row["legal_hold_enabled"]),
        immutable_required=bool(row["immutable_required"]),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _map_legal_hold_row(row: dict[str, Any]) -> LegalHoldRecord:
    released_at = row.get("released_at")
    return LegalHoldRecord(
        hold_id=str(row["hold_id"]),
        tenant=str(row["tenant"]),
        scope_type=str(row["scope_type"]),
        scope_id=str(row["scope_id"]),
        reason=str(row["reason"]),
        case_id=row.get("case_id"),
        regulator_ref=row.get("regulator_ref"),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        released_at=released_at,
        active=released_at is None,
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


def _require_reports_bucket() -> None:
    if not config.reports_bucket or config.reports_bucket.startswith("TODO"):
        raise HTTPException(status_code=500, detail="REPORTS_BUCKET is not configured")
    if config.enforce_storage_hardening:
        _assert_bucket_hardening(config.reports_bucket)


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
