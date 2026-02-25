# P4 AI Audit Trail Engine

P4 extends Alchimista with auditable AI decision trails linked to document context already ingested by P1-P3.

## Endpoints
- `POST /v1/decisions`
  - Writes or updates a decision (`UNIQUE (tenant, decision_id)` idempotency key).
  - Requires `context_docs` that already exist for the same tenant.
  - Optional `context_chunks` are validated against `chunks` and must belong to the provided `context_docs`.
- `POST /v1/decisions/query`
  - Filters by tenant, decision ID prefix, model/version, output labels, decision trace ID, text (`input`/`output`), context docs/chunks, confidence range/band, creation window.
  - Supports pagination (`offset`, `limit`) and sorting (`order: asc|desc`), returning `total`, `returned`, `offset`, `limit`.
- `GET /v1/decisions/{decision_id}/report?tenant=...`
  - Returns a report payload with:
    - decision record
    - context document metadata (`doc_id`, `source_uri`, `mime_type`, `size_bytes`)
    - context chunk previews (`chunk_id`, `doc_id`, `chunk_index`, `token_count`, `preview`)
    - immutable `report_hash_sha256`
    - optional `signature` (`hmac-sha256`) when signing key is configured
- `POST /v1/decisions/export`
  - Persists a signed audit export JSON into `REPORTS_BUCKET`.
  - Reuses the same filters as query plus:
    - `include_context` to embed full context document/chunk snapshots in the export
    - optional `object_name` to control destination path (`reports/<tenant>/audit/...` default)
  - Returns `gs_uri`, `total`, `returned`, `report_hash_sha256`, `signature_*`.
- `POST /v1/decisions/bundle`
  - Produces a regulator-oriented signed bundle in `REPORTS_BUCKET`.
  - Supports explicit `decision_ids` selection and optional controls:
    - `case_id`
    - `regulator_ref`
    - `include_policy_snapshot`
  - Stores per-decision `report_hash_sha256` entries and one top-level signed bundle hash.
- `POST /v1/admin/decisions/query`
  - Cross-tenant search endpoint for operations/compliance teams.
  - Requires both:
    - valid JWT/OIDC bearer token
    - `x-admin-key` (same control used by `/v1/admin/replay-dlq`)
  - Accepts `tenants[]` + full advanced filter set.

## SQL tables
- `ai_decisions`
- `ai_decision_context_docs`
- `ai_decision_context_chunks`
- Canonical migration source remains `sql/schema.sql`.
- Runtime safety net: ingestion service ensures these tables exist on first decision operation (`CREATE TABLE IF NOT EXISTS`).

## Security and tenancy
- Same JWT/OIDC tenant authorization model used by ingestion/query endpoints.
- Decision writes/reads are tenant-scoped.
- Pub/Sub hardening from P3.3 remains active (`AUTH_ALLOW_UNAUTHENTICATED_PUBSUB=false`).
- Report signing key is injected from Secret Manager and can be rotated with:
  - `scripts/rotate_audit_report_signing_key_secret.sh`
  - `.github/workflows/rotate-audit-signing-key.yml` (manual + schedule)
- Admin cross-tenant query is intentionally isolated behind JWT + `x-admin-key` dual control.

## Notes
- Current database still has global `documents.doc_id` primary key.
- P4.0 enforces tenant consistency at application layer when linking context.
- Report signing config:
  - `AUDIT_REPORT_SIGNING_KEY`
  - `AUDIT_REPORT_SIGNING_KEY_ID`
