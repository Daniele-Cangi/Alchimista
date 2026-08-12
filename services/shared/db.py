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
            SELECT ch.doc_id, ch.chunk_id, ch.chunk_index, ch.chunk_text, ch.embedding, d.source_uri
            FROM chunks ch
            JOIN documents d ON d.doc_id = ch.doc_id AND d.tenant = ch.tenant
            WHERE ch.tenant = %s AND ch.chunk_id = ANY(%s) AND ch.doc_id = ANY(%s)
            """,
            (tenant, chunk_ids, doc_ids),
        )
        return cur.fetchall()

    cur.execute(
        """
        SELECT ch.doc_id, ch.chunk_id, ch.chunk_index, ch.chunk_text, ch.embedding, d.source_uri
        FROM chunks ch
        JOIN documents d ON d.doc_id = ch.doc_id AND d.tenant = ch.tenant
        WHERE ch.tenant = %s AND ch.chunk_id = ANY(%s)
        """,
        (tenant, chunk_ids),
    )
    return cur.fetchall()


def list_documents(
    cur: psycopg.Cursor,
    *,
    tenant: str,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    cur.execute("SELECT COUNT(*) AS total FROM documents WHERE tenant = %s", (tenant,))
    total_row = cur.fetchone() or {"total": 0}
    cur.execute(
        """
        SELECT
          d.doc_id, d.tenant, d.source_uri, d.mime_type, d.size_bytes,
          d.content_hash, d.created_at, d.updated_at,
          j.status,
          COALESCE(ch.chunk_count, 0) AS chunks,
          COALESCE(dp.pii_detected, 0) AS pii_detected,
          COALESCE(dp.pii_types, ARRAY[]::TEXT[]) AS pii_types,
          COALESCE(dp.privacy_policy, 'off') AS privacy_policy,
          COALESCE(dp.metadata->>'privacy_detector', dp.privacy_engine) AS privacy_detector,
          dp.privacy_engine_version,
          dp.privacy_engine_source_revision
        FROM documents d
        LEFT JOIN jobs j ON j.doc_id = d.doc_id AND j.type = 'PROCESS'
        LEFT JOIN document_privacy dp ON dp.doc_id = d.doc_id AND dp.tenant = d.tenant
        LEFT JOIN (
          SELECT doc_id, COUNT(*)::INTEGER AS chunk_count
          FROM chunks WHERE tenant = %s GROUP BY doc_id
        ) ch ON ch.doc_id = d.doc_id
        WHERE d.tenant = %s
        ORDER BY d.created_at DESC
        LIMIT %s OFFSET %s
        """,
        (tenant, tenant, limit, offset),
    )
    return cur.fetchall(), int(total_row["total"])


def fetch_document_detail(cur: psycopg.Cursor, *, tenant: str, doc_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT
          d.doc_id, d.tenant, d.source_uri, d.mime_type, d.size_bytes,
          d.content_hash, d.created_at, d.updated_at,
          j.status,
          COALESCE(dp.pii_detected, 0) AS pii_detected,
          COALESCE(dp.pii_types, ARRAY[]::TEXT[]) AS pii_types,
          COALESCE(dp.privacy_policy, 'off') AS privacy_policy,
          COALESCE(dp.metadata->>'privacy_detector', dp.privacy_engine) AS privacy_detector,
          dp.privacy_engine_version,
          dp.privacy_engine_source_revision,
          COALESCE((SELECT COUNT(*) FROM chunks ch WHERE ch.tenant = d.tenant AND ch.doc_id = d.doc_id), 0)::INTEGER AS chunks,
          COALESCE((
            SELECT COUNT(DISTINCT refs.decision_ref_id)
            FROM (
              SELECT dc.decision_ref_id
              FROM ai_decision_context_docs dc
              WHERE dc.tenant = d.tenant AND dc.doc_id = d.doc_id
              UNION
              SELECT cc.decision_ref_id
              FROM ai_decision_context_chunks cc
              JOIN chunks context_chunk
                ON context_chunk.chunk_id = cc.chunk_id AND context_chunk.tenant = cc.tenant
              WHERE context_chunk.tenant = d.tenant AND context_chunk.doc_id = d.doc_id
            ) refs
          ), 0)::INTEGER AS decisions_referencing
        FROM documents d
        LEFT JOIN jobs j ON j.doc_id = d.doc_id AND j.type = 'PROCESS'
        LEFT JOIN document_privacy dp ON dp.doc_id = d.doc_id AND dp.tenant = d.tenant
        WHERE d.tenant = %s AND d.doc_id = %s
        """,
        (tenant, doc_id),
    )
    row = cur.fetchone()
    if row is None:
        return None
    cur.execute(
        """
        SELECT chunk_id, chunk_index, LEFT(chunk_text, 1200) AS preview, token_count
        FROM chunks
        WHERE tenant = %s AND doc_id = %s
        ORDER BY chunk_index ASC
        """,
        (tenant, doc_id),
    )
    row["evidence"] = cur.fetchall()
    return row


def fetch_chunk_evidence(
    cur: psycopg.Cursor,
    *,
    tenant: str,
    doc_id: str,
    chunk_id: str,
) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT ch.chunk_id, ch.doc_id, ch.chunk_index, ch.chunk_text AS preview,
               ch.token_count, d.source_uri
        FROM chunks ch
        JOIN documents d ON d.doc_id = ch.doc_id AND d.tenant = ch.tenant
        WHERE ch.tenant = %s AND ch.doc_id = %s AND ch.chunk_id = %s
        """,
        (tenant, doc_id, chunk_id),
    )
    return cur.fetchone()
