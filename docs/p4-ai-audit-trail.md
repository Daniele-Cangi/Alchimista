# P4.0 AI Audit Trail Engine

P4.0 extends Alchimista with auditable AI decision trails linked to document context already ingested by P1-P3.

## Endpoints
- `POST /v1/decisions`
  - Writes or updates a decision (`UNIQUE (tenant, decision_id)` idempotency key).
  - Requires `context_docs` that already exist for the same tenant.
  - Optional `context_chunks` are validated against `chunks` and must belong to the provided `context_docs`.
- `POST /v1/decisions/query`
  - Filters by tenant, model, version, text (`input`/`output`), context docs, confidence, creation window.
- `GET /v1/decisions/{decision_id}/report?tenant=...`
  - Returns a report payload with:
    - decision record
    - context document metadata (`doc_id`, `source_uri`, `mime_type`, `size_bytes`)
    - context chunk previews (`chunk_id`, `doc_id`, `chunk_index`, `token_count`, `preview`)

## SQL tables
- `ai_decisions`
- `ai_decision_context_docs`
- `ai_decision_context_chunks`

## Security and tenancy
- Same JWT/OIDC tenant authorization model used by ingestion/query endpoints.
- Decision writes/reads are tenant-scoped.
- Pub/Sub hardening from P3.3 remains active (`AUTH_ALLOW_UNAUTHENTICATED_PUBSUB=false`).

## Notes
- Current database still has global `documents.doc_id` primary key.
- P4.0 enforces tenant consistency at application layer when linking context.
