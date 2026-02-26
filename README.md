# Alchimista Engine

Alchimista is an enterprise **Document Processing + RAG + AI Audit Trail Engine** (not a generic chatbot).

## North Star
Upload documents and AI decisions, convert them into auditable knowledge (chunks, entities, embeddings, metadata), answer with mandatory citations (`doc_id`, `chunk_id`), and enforce governance controls (retention policies, legal holds, immutable artifacts, traceability via `trace_id`/`job_id`).

## What The Software Does
- Document intake and processing pipeline (`/v1/ingest` -> Pub/Sub -> processor -> SQL + vector index).
- RAG query engine with mandatory citations (`/v1/query`).
- AI decision trail ingestion/query/export/package (`/v1/decisions*`) for regulator-grade evidence.
- Governance controls for retention policies and legal holds (`/v1/admin/retention-policies`, `/v1/admin/legal-holds`).
- Retention enforcement engine (`/v1/admin/retention/enforce`) with dry-run, hold-aware deletion, and audit trail of deletion actions.
- Web control plane (`services/dashboard_service`) to operate ingest/query/decision/governance flows from one UI.

## License
This repository is distributed under a proprietary commercial license.
See:
- `LICENSE`
- `NOTICE`
- `TERMS.md`

## Repository layout
- `spec/project.yaml`: single source of truth for project direction and infrastructure contract
- `sql/schema.sql`: canonical relational schema (`documents`, `jobs`, `chunks`, `entities`, `ai_decisions`, decision context tables)
- `services/ingestion_api_service`: ingest API (`/v1/ingest`, `/v1/ingest/complete`, `/v1/doc/{id}`)
- `services/document_processor_service`: parser/chunker/embedder/DB writer (`/v1/process`, `/v1/process/pubsub`)
- `services/rag_query_service`: retrieval + answer with citations (`/v1/query`)
- `services/dashboard_service`: management UI + proxy (`/dashboard`, `/ingest`, `/query`, `/decisions`, `/governance`)
- `services/shared`: shared contracts, DB helpers, chunking, embeddings, logging
- `infra/terraform`: IaC baseline aligned to current GCP resources
- `_archive/`: preserved historical Cloud Run sample recovered from GCS

## Invariants
- Single source of truth: `spec/project.yaml`
- Stable contracts: Pub/Sub + HTTP + SQL
- Idempotency: no duplicate processing for same `doc_id`/hash
- Mandatory citations in query answers
- End-to-end traceability via `trace_id` and `job_id`

## Local quickstart
1. Copy env:
```bash
cp .env.example .env
```
2. Export env values:
```bash
set -a
source .env
set +a
```
3. Apply SQL schema:
```bash
./scripts/apply_schema.sh
```
4. Run services (separate terminals):
```bash
uvicorn services.ingestion_api_service.main:app --reload --port 8011
uvicorn services.document_processor_service.main:app --reload --port 8012
uvicorn services.rag_query_service.main:app --reload --port 8013
uvicorn services.dashboard_service.app:app --reload --port 8000
```

## P1 Definition of Done
- Upload `test.pdf` and publish ingest event
- Processor marks job as `SUCCEEDED`
- `chunks` populated in SQL
- `/v1/query` returns `answers[]` with non-empty `citations[]`

## Runtime hardening operations
- Cut over Cloud Run services to dedicated service accounts:
```bash
./scripts/cutover_service_accounts.sh secure-electron-474908-k9 europe-west4
```
- Run end-to-end smoke test against deployed services:
```bash
INGEST_URL='https://ingestion-api-service-pe7qslbcvq-ez.a.run.app' \
PROCESSOR_URL='https://document-processor-service-pe7qslbcvq-ez.a.run.app' \
RAG_URL='https://rag-query-service-pe7qslbcvq-ez.a.run.app' \
./scripts/smoke_p1.sh
```
- Apply P2 backpressure limits on Cloud Run + Pub/Sub:
```bash
./scripts/apply_p2_backpressure.sh secure-electron-474908-k9 europe-west4
```
- Replay messages from DLQ (requires `ADMIN_API_KEY` configured on ingestion service):
```bash
ADMIN_API_KEY='REPLACE_ME' MAX_MESSAGES=25 ./scripts/replay_dlq.sh
```
or directly from Secret Manager:
```bash
PROJECT_ID='secure-electron-474908-k9' \
ADMIN_API_KEY_SECRET='alchimista-admin-api-key' \
MAX_MESSAGES=25 ./scripts/replay_dlq.sh
```
- Rotate and bind `ADMIN_API_KEY` through Secret Manager:
```bash
./scripts/rotate_admin_api_key_secret.sh secure-electron-474908-k9 europe-west4
```
- Apply P2 observability dashboard and alert policies:
```bash
./scripts/apply_p2_observability.sh secure-electron-474908-k9 europe-west4
```

## Vertex Vector Search operations
- Provision index + endpoint + deployment (idempotent, waits until active):
```bash
./scripts/setup_vertex_vector_search.sh secure-electron-474908-k9 europe-west4
```
- Switch processor + rag services to Vertex retrieval + Vertex text embeddings:
```bash
./scripts/enable_vertex_backend.sh secure-electron-474908-k9 europe-west4 \
  3994068346873053184 5596857233007706112 alchimista_chunks_deployed_v3
```

## P3.3 OIDC/JWT auth rollout
- Apply OIDC verification settings to runtime services:
```bash
./scripts/apply_p3_auth_oidc.sh \
  secure-electron-474908-k9 europe-west4 \
  'https://YOUR_ISSUER' 'YOUR_AUDIENCE' \
  '' 'tenant,tenants' true
```
- Current transitional behavior:
  - `/v1/healthz` and `/v1/readyz` remain open.
- Enforce authenticated Pub/Sub push to `/v1/process/pubsub` (recommended for enterprise hardening):
```bash
./scripts/apply_p3_pubsub_push_oidc.sh secure-electron-474908-k9 europe-west4
```
- Get an Auth0 M2M access token for Alchimista API:
```bash
TOKEN="$(./scripts/get_auth0_m2m_token.sh \
  alchimista.eu.auth0.com \
  '<AUTH0_CLIENT_ID>' \
  '<AUTH0_CLIENT_SECRET>' \
  'https://api.alchimista.ai')"
```
- Run authenticated smoke query:
```bash
./scripts/smoke_p3_auth.sh "$TOKEN" default
```

## P3.1 Benchmark
- Dataset baseline: `benchmark/dataset_v1.json`
- Run benchmark and generate report:
```bash
./scripts/run_p3_benchmark.py --dataset benchmark/dataset_v1.json --output-dir reports/benchmarks
```
- Processing defaults to `event-driven` (no direct `/v1/process` call; waits for terminal job status via `/v1/doc/{id}`).
- Optional explicit processing controls:
```bash
./scripts/run_p3_benchmark.py \
  --processing-mode event-driven \
  --processing-timeout-seconds 300 \
  --poll-interval-seconds 2
```
- If auth is enabled, pass token:
```bash
BENCHMARK_BEARER_TOKEN='REPLACE_ME' ./scripts/run_p3_benchmark.py
```

## P3.4 CI/CD
- CI workflows:
  - `.github/workflows/ci.yml`
  - `.github/workflows/benchmark-gate.yml`
  - `.github/workflows/deploy-cloud-run.yml`
- GitHub Environment used for secrets:
  - `test` and `prod`
  - benchmark-gate schedule resolves to `prod`; manual runs can target `test`/`prod`
- Bootstrap deploy IAM prerequisites:
```bash
./scripts/bootstrap_github_deploy_iam.sh secure-electron-474908-k9
```
- Deploy one service from terminal:
```bash
./scripts/deploy_cloud_run_service.sh ingestion-api-service secure-electron-474908-k9 europe-west4
```
- Enforce benchmark gate on latest report:
```bash
python scripts/check_benchmark_gate.py --spec spec/project.yaml --report reports/benchmarks/latest.json
```
- Full operational details:
  - `docs/p4-cicd.md`

## P5 Governance + Connectors
- Register an AI decision linked to existing context documents/chunks:
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id":"d-001",
    "model":"gpt-4",
    "model_version":"2024-01",
    "input":"customer request payload",
    "output":"approved",
    "confidence":0.94,
    "context_docs":["default::bench-alpha-v1","default::bench-beta-v1"],
    "tenant":"default",
    "trace_id":"'"$(uuidgen)"'"
  }'
```
- Query decisions with advanced enterprise filters:
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions/query" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "model":"gpt-4",
    "model_version":"2024-01",
    "outputs":["approved"],
    "query":"kyc case",
    "min_confidence":0.8,
    "confidence_band":"high",
    "created_from":"2026-02-01T00:00:00Z",
    "created_to":"2026-02-28T23:59:59Z",
    "context_docs":["default::bench-alpha-v1"],
    "limit":20,
    "offset":0,
    "order":"desc"
  }'
```
- Generate a regulator-friendly decision trail report:
```bash
curl -sS -H "Authorization: Bearer ${TOKEN}" \
  "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions/d-001/report?tenant=default"
```
- Export a signed audit snapshot to GCS (`REPORTS_BUCKET`):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions/export" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "model":"gpt-4",
    "min_confidence":0.8,
    "limit":200,
    "include_context":true
  }'
```
- Build a regulator-ready signed bundle (decision reports + optional policy snapshot):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions/bundle" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "decision_ids":["d-001"],
    "case_id":"kyc-case-001",
    "regulator_ref":"eu-ai-act-art-12",
    "include_context":true,
    "include_policy_snapshot":true
  }'
```
- Build a regulator package with manifest + evidence files:
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions/package" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "decision_ids":["d-001"],
    "case_id":"kyc-case-001",
    "regulator_ref":"eu-ai-act-art-12",
    "include_context":true,
    "include_policy_snapshot":true
  }'
```
- Verify integrity/signature of an audit artifact already stored in GCS:
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/decisions/verify" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "gs_uri":"gs://alchimista-reports-994021588311/reports/default/audit/packages/pkg-.../manifest.json",
    "strict_tenant_path":true
  }'
```
- Admin-only cross-tenant decision query (requires `x-admin-key`):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/decisions/query" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenants":["default","vendor-x"],
    "model":"gpt-4",
    "outputs":["approved"],
    "limit":50
  }'
```
- Import document via enterprise connector (`gs://` source -> `raw/` + optional publish):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/connectors/gcs/import" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "source_gcs_uri":"gs://external-vendor-dropzone/kyc/case-001.pdf",
    "tenant":"default",
    "publish":true
  }'
```
- Upsert retention policy (admin endpoint, requires `x-admin-key`):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/retention-policies" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "artifact_type":"audit_artifacts",
    "retain_days":3650,
    "legal_hold_enabled":true,
    "immutable_required":true
  }'
```
- Create legal hold (admin endpoint, requires `x-admin-key`):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/legal-holds" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "scope_type":"document",
    "scope_id":"default::bench-alpha-v1",
    "reason":"regulatory_audit_open"
  }'
```
- List active legal holds:
```bash
curl -sS "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/legal-holds?tenant=default&active_only=true" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}"
```
- Artifact writes are immutable (write-once): reusing the same `object_name`/`object_prefix` now returns `409`.
- Full P5 details: `docs/p5-governance-and-connectors.md`.
- Optional signing (HMAC) for exported reports:
```bash
AUDIT_REPORT_SIGNING_KEY='REPLACE_WITH_STRONG_SECRET'
AUDIT_REPORT_SIGNING_KEY_ID='audit-key-v1'
```
- Rotate signing key manually:
```bash
./scripts/rotate_audit_report_signing_key_secret.sh secure-electron-474908-k9 europe-west4
```
- Rotate signing key via GitHub Actions (manual or monthly schedule):
```bash
gh workflow run rotate-audit-signing-key.yml -f environment_name=test -f project_id=secure-electron-474908-k9 -f region=europe-west4
```

## P6 Retention Enforcement
- Prerequisites (auth for admin endpoints):
```bash
TOKEN="$(./scripts/get_auth0_m2m_token.sh \
  alchimista.eu.auth0.com \
  '<AUTH0_CLIENT_ID>' \
  '<AUTH0_CLIENT_SECRET>' \
  'https://api.alchimista.ai')"

ADMIN_API_KEY="$(gcloud secrets versions access latest \
  --secret alchimista-admin-api-key \
  --project secure-electron-474908-k9)"
```
- Seed retention policies by artifact type (recommended before first enforcement run):
```bash
for TYPE in decision_report policy_snapshot regulator_package_manifest; do
  curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/retention-policies" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "x-admin-key: ${ADMIN_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{
      \"tenant\":\"default\",
      \"artifact_type\":\"${TYPE}\",
      \"retain_days\":3650,
      \"legal_hold_enabled\":true,
      \"immutable_required\":true
    }"
done
```
- List active retention policies:
```bash
curl -sS "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/retention-policies?tenant=default" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}"
```
- Execute retention enforcement in dry-run mode (`artifact_type:null` scans all tenant artifact types):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/retention/enforce" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "artifact_type":null,
    "dry_run":true,
    "limit":200
  }'
```
- Execute real retention deletion (expired artifacts only, legal-hold aware):
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/retention/enforce" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "artifact_type":null,
    "dry_run":false,
    "limit":200
  }'
```
- Optional legal hold for protection before deletion:
```bash
curl -sS -X POST "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app/v1/admin/legal-holds" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant":"default",
    "scope_type":"artifact",
    "scope_id":"gs://alchimista-reports-994021588311/reports/default/audit/packages/pkg-.../manifest.json",
    "reason":"regulatory_hold"
  }'
```
- Enforcement behavior:
  - only artifacts with configured `retention_policies` are considered eligible
  - active legal holds block deletion
  - deleted artifacts are soft-marked in SQL (`deleted_at`, `deleted_by`, `deletion_reason`, `delete_job_id`)
  - GCS object deletion is generation-aware when generation metadata exists
- Observed production validation on 2026-02-25:
  - `dry_run` smoke: `HTTP 200`, trace_id `6ef64f51-fb5a-4539-b58a-9964bc4791e1`
  - `delete` smoke: `HTTP 200`, trace_id `52698ca4-3e2c-4971-b0ce-e0bfcd8ee094`
  - post-policy-seed dry-run: `HTTP 200`, trace_id `882ce2d8-e8dc-4bf9-a596-60cb8b6ad525`, `skipped_policy_missing=0`
- Run from CLI with helper script:
```bash
TOKEN="${TOKEN}" ADMIN_API_KEY="${ADMIN_API_KEY}" \
TENANT=default ARTIFACT_TYPE='' DRY_RUN=true LIMIT=200 \
./scripts/run_p6_retention_enforcement.sh
```
- Scheduled automation:
  - `.github/workflows/retention-enforce.yml` runs:
    - daily dry-run at `03:40 UTC` (`cron: 40 3 * * *`)
    - maintenance window at `02:10 UTC` on Sunday (`cron: 10 2 * * 0`)
  - delete mode in scheduled maintenance window is controlled by feature flag secret `RETENTION_DELETE_WINDOW_ENABLED`.
  - if the feature flag is missing or different from `true`, scheduled maintenance run falls back to `dry_run=true`.
  - market environment (`prod`) is set to `RETENTION_DELETE_WINDOW_ENABLED=true` (market mode active).
  - workflow schedule resolves automatically to GitHub environment `prod`; manual runs can still target `test` or `prod`.
  - enable maintenance delete window:
```bash
gh secret set RETENTION_DELETE_WINDOW_ENABLED --env prod --body true
```
  - disable maintenance delete window:
```bash
gh secret set RETENTION_DELETE_WINDOW_ENABLED --env prod --body false
```
- First validated run: `22417582060` (2026-02-25, status `success`).
- Latest delete validation run: `22417964263` (2026-02-25, `dry_run=false`, status `success`).
- First `prod` validation run: `22418533597` (2026-02-25, `dry_run=false`, status `success`).
  - Manual delete run example:
```bash
gh workflow run retention-enforce.yml \
  -f environment_name=test \
  -f project_id=secure-electron-474908-k9 \
  -f tenant=default \
  -f artifact_type= \
  -f dry_run=false \
  -f limit=200 \
  -f fail_on_errors=true
```
- Full P6 details: `docs/p6-retention-enforcement.md`.
