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
) -> None:
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
