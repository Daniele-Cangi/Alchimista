# P5 Governance and Connectors

P5 extends Alchimista from audit trail generation to operational governance and controlled intake.

## Connector ingest
- `POST /v1/connectors/gcs/import`
  - Reads source bytes from `source_gcs_uri`.
  - Writes into tenant raw prefix: `raw/<tenant>/<doc_id>/...`.
  - Applies hash-based idempotency (`DEDUPLICATED` if same content and `force_reprocess=false`).
  - Optionally publishes ingest event (`publish=true`).

## Governance endpoints (admin)
All admin governance endpoints require:
- valid JWT/OIDC bearer token
- `x-admin-key`

Endpoints:
- `POST /v1/admin/retention-policies`
- `GET /v1/admin/retention-policies`
- `POST /v1/admin/legal-holds`
- `POST /v1/admin/legal-holds/release`
- `GET /v1/admin/legal-holds`

## Artifact immutability and verification
- Export/bundle/package artifacts are now written with storage precondition `if_generation_match=0` (write-once).
- Existing object path reuse returns `409`.
- `POST /v1/decisions/verify` validates:
  - `report_hash_sha256`
  - HMAC signature (`hmac-sha256`) when present
  - tenant path guard (`reports/<tenant>/audit/`) by default

## New SQL entities
- `retention_policies`
- `legal_holds`
- `audit_artifacts`

These are created by canonical migration (`sql/schema.sql`) and runtime safety net (`_ensure_ai_decision_schema`).
