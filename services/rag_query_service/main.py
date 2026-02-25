from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from services.shared.config import get_env_int, load_runtime_config
from services.shared.contracts import Citation, QueryAnswer, QueryRequest, QueryResponse
from services.shared.db import get_connection
from services.shared.embeddings import deterministic_embedding
from services.shared.logging_utils import log_event
from services.shared.vector_search import rank_chunks


config = load_runtime_config()
app = FastAPI(title="rag-query-service", version="0.1.0")
MAX_CANDIDATES = get_env_int("RAG_MAX_CANDIDATES", 5000)


@app.get("/v1/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/v1/readyz")
def readyz() -> dict:
    try:
        with get_connection(config.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ready"}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=f"Database not ready: {exc}") from exc


@app.post("/v1/query", response_model=QueryResponse)
def query(payload: QueryRequest) -> QueryResponse:
    trace_id = payload.trace_id or str(uuid4())
    query_embedding = deterministic_embedding(payload.query)

    with get_connection(config.database_url) as conn:
        with conn.cursor() as cur:
            if payload.doc_ids:
                cur.execute(
                    """
                    SELECT doc_id, chunk_id, chunk_text, embedding
                    FROM chunks
                    WHERE tenant = %s AND doc_id = ANY(%s)
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (payload.tenant, payload.doc_ids, MAX_CANDIDATES),
                )
            else:
                cur.execute(
                    """
                    SELECT doc_id, chunk_id, chunk_text, embedding
                    FROM chunks
                    WHERE tenant = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (payload.tenant, MAX_CANDIDATES),
                )
            rows = cur.fetchall()

    if not rows:
        log_event(
            "info",
            "rag_query_no_chunks",
            trace_id=trace_id,
            tenant=payload.tenant,
            top_k=payload.top_k,
        )
        return QueryResponse(answers=[], trace_id=trace_id)

    candidates = []
    for row in rows:
        emb = row.get("embedding")
        if emb is None:
            continue
        candidates.append(
            {
                "doc_id": row["doc_id"],
                "chunk_id": row["chunk_id"],
                "chunk_text": row["chunk_text"],
                "embedding": list(emb),
            }
        )

    hits = rank_chunks(query_embedding, candidates, payload.top_k)
    if not hits:
        return QueryResponse(answers=[], trace_id=trace_id)

    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    snippets: list[str] = []

    for idx, hit in enumerate(hits, start=1):
        key = (hit["doc_id"], hit["chunk_id"])
        if key not in seen:
            citations.append(Citation(doc_id=hit["doc_id"], chunk_id=hit["chunk_id"]))
            seen.add(key)
        snippets.append(f"[{idx}] {hit['chunk_text'][:280]}")

    answer_text = "Evidence-based answer candidate:\n" + "\n".join(snippets)
    answer = QueryAnswer(text=answer_text, score=float(hits[0]["score"]), citations=citations)

    log_event(
        "info",
        "rag_query_completed",
        trace_id=trace_id,
        tenant=payload.tenant,
        top_k=payload.top_k,
        answers=1,
    )
    return QueryResponse(answers=[answer], trace_id=trace_id)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("services.rag_query_service.main:app", host="0.0.0.0", port=port)
