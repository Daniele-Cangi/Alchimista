from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from services.shared.contracts import JobStatus


@contextmanager
def get_connection(database_url: str):
    conn = psycopg.connect(database_url, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_document_by_hash(cur: psycopg.Cursor, tenant: str, content_hash: str) -> dict[str, Any] | None:
    cur.execute(
        "SELECT * FROM documents WHERE tenant = %s AND content_hash = %s",
        (tenant, content_hash),
    )
    return cur.fetchone()


def upsert_document(
    cur: psycopg.Cursor,
    *,
    doc_id: str,
    tenant: str,
    source_uri: str,
    mime_type: str | None,
    size_bytes: int | None,
    content_hash: str | None,
) -> None:
    cur.execute(
        """
        INSERT INTO documents (doc_id, tenant, source_uri, mime_type, size_bytes, content_hash, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (doc_id)
        DO UPDATE SET
          source_uri = EXCLUDED.source_uri,
          mime_type = EXCLUDED.mime_type,
          size_bytes = EXCLUDED.size_bytes,
          content_hash = COALESCE(EXCLUDED.content_hash, documents.content_hash),
          updated_at = NOW()
        """,
        (doc_id, tenant, source_uri, mime_type, size_bytes, content_hash),
    )


def upsert_process_job(
    cur: psycopg.Cursor,
    *,
    doc_id: str,
    tenant: str,
    trace_id: str,
    status: JobStatus,
    metrics: dict[str, Any] | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> str:
    cur.execute(
        """
        INSERT INTO jobs (doc_id, tenant, type, status, trace_id, started_at, finished_at, metrics, error, updated_at)
        VALUES (%s, %s, 'PROCESS', %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (doc_id, type)
        DO UPDATE SET
          status = EXCLUDED.status,
          trace_id = EXCLUDED.trace_id,
          started_at = COALESCE(EXCLUDED.started_at, jobs.started_at),
          finished_at = EXCLUDED.finished_at,
          metrics = EXCLUDED.metrics,
          error = EXCLUDED.error,
          updated_at = NOW()
        RETURNING job_id
        """,
        (
            doc_id,
            tenant,
            status.value,
            trace_id,
            started_at,
            finished_at,
            Json(metrics or {}),
            error,
        ),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Unable to persist process job")
    return str(row["job_id"])


def fetch_document_status(cur: psycopg.Cursor, doc_id: str, tenant: str) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT
          d.doc_id,
          d.tenant,
          d.source_uri,
          d.mime_type,
          d.size_bytes,
          d.content_hash,
          d.updated_at,
          j.job_id,
          j.type,
          j.status,
          j.trace_id,
          j.started_at,
          j.finished_at,
          j.metrics,
          j.error
        FROM documents d
        LEFT JOIN jobs j
          ON d.doc_id = j.doc_id
         AND j.type = 'PROCESS'
        WHERE d.doc_id = %s AND d.tenant = %s
        """,
        (doc_id, tenant),
    )
    return cur.fetchone()


def replace_chunks(
    cur: psycopg.Cursor,
    *,
    doc_id: str,
    tenant: str,
    chunks: list[dict[str, Any]],
) -> None:
    cur.execute("DELETE FROM chunks WHERE doc_id = %s AND tenant = %s", (doc_id, tenant))
    for chunk in chunks:
        cur.execute(
            """
            INSERT INTO chunks (chunk_id, doc_id, tenant, chunk_index, chunk_text, token_count, embedding, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                chunk["chunk_id"],
                doc_id,
                tenant,
                chunk["chunk_index"],
                chunk["chunk_text"],
                chunk["token_count"],
                chunk["embedding"],
                Json(chunk.get("metadata", {})),
            ),
        )


def replace_entities(
    cur: psycopg.Cursor,
    *,
    doc_id: str,
    tenant: str,
    entities: list[dict[str, str]],
) -> None:
    cur.execute("DELETE FROM entities WHERE doc_id = %s AND tenant = %s", (doc_id, tenant))
    for entity in entities:
        cur.execute(
            """
            INSERT INTO entities (doc_id, tenant, chunk_id, entity_type, entity_value)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                doc_id,
                tenant,
                entity["chunk_id"],
                entity["entity_type"],
                entity["entity_value"],
            ),
        )


def replace_pii_findings(
    cur: psycopg.Cursor,
    *,
    doc_id: str,
    tenant: str,
    findings: list[dict[str, Any]],
) -> None:
    cur.execute("DELETE FROM pii_findings WHERE doc_id = %s AND tenant = %s", (doc_id, tenant))
    for finding in findings:
        cur.execute(
            """
            INSERT INTO pii_findings (
              tenant, doc_id, chunk_id, entity_type, detector, confidence,
              start_offset, end_offset, placeholder, value_hash, validation_metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant,
                doc_id,
                finding.get("chunk_id"),
                finding["type"],
                finding["detector"],
                finding["confidence"],
                finding["start"],
                finding["end"],
                finding["placeholder"],
                finding["value_hash"],
                Json(finding.get("metadata") or {}),
            ),
        )


def upsert_document_privacy(
    cur: psycopg.Cursor,
    *,
    tenant: str,
    doc_id: str,
    privacy_policy: str,
    pii_detected: int,
    pii_types: list[str],
    external_payload_pseudonymized: bool,
    privacy_engine: str | None,
    privacy_engine_version: str | None,
    privacy_engine_source_revision: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO document_privacy (
          tenant, doc_id, privacy_policy, pii_detected, pii_types,
          external_payload_pseudonymized, mapping_exported, privacy_engine,
          privacy_engine_version, privacy_engine_source_revision, metadata, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, FALSE, %s, %s, %s, %s, NOW())
        ON CONFLICT (tenant, doc_id)
        DO UPDATE SET
          privacy_policy = EXCLUDED.privacy_policy,
          pii_detected = EXCLUDED.pii_detected,
          pii_types = EXCLUDED.pii_types,
          external_payload_pseudonymized = EXCLUDED.external_payload_pseudonymized,
          mapping_exported = FALSE,
          privacy_engine = EXCLUDED.privacy_engine,
          privacy_engine_version = EXCLUDED.privacy_engine_version,
          privacy_engine_source_revision = EXCLUDED.privacy_engine_source_revision,
          metadata = EXCLUDED.metadata,
          updated_at = NOW()
        """,
        (
            tenant,
            doc_id,
            privacy_policy,
            pii_detected,
            pii_types,
            external_payload_pseudonymized,
            privacy_engine,
            privacy_engine_version,
            privacy_engine_source_revision,
            Json(metadata or {}),
        ),
    )


def fetch_document_privacy(
    cur: psycopg.Cursor,
    *,
    tenant: str,
    doc_ids: list[str],
) -> list[dict[str, Any]]:
    if not doc_ids:
        return []
    cur.execute(
        """
        SELECT tenant, doc_id, privacy_policy, pii_detected, pii_types,
               external_payload_pseudonymized, mapping_exported, privacy_engine,
               privacy_engine_version, privacy_engine_source_revision, metadata, updated_at
        FROM document_privacy
        WHERE tenant = %s AND doc_id = ANY(%s)
        ORDER BY doc_id
        """,
        (tenant, doc_ids),
    )
    return cur.fetchall()


def get_chunk_ids_for_doc(cur: psycopg.Cursor, doc_id: str, tenant: str) -> list[str]:
    cur.execute(
        """
        SELECT chunk_id
        FROM chunks
        WHERE doc_id = %s AND tenant = %s
        ORDER BY chunk_index ASC
        """,
        (doc_id, tenant),
    )
    rows = cur.fetchall()
    return [row["chunk_id"] for row in rows]


def fetch_chunks_by_ids(
    cur: psycopg.Cursor,
    *,
    tenant: str,
    chunk_ids: list[str],
    doc_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []

    if doc_ids:
        cur.execute(
            """
            SELECT doc_id, chunk_id, chunk_text, embedding
            FROM chunks
            WHERE tenant = %s AND chunk_id = ANY(%s) AND doc_id = ANY(%s)
            """,
            (tenant, chunk_ids, doc_ids),
        )
        return cur.fetchall()

    cur.execute(
        """
        SELECT doc_id, chunk_id, chunk_text, embedding
        FROM chunks
        WHERE tenant = %s AND chunk_id = ANY(%s)
        """,
        (tenant, chunk_ids),
    )
    return cur.fetchall()
