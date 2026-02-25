# Alchimista Engine

Alchimista is a Document Processing + RAG Engine (not a generic chatbot).

## North Star
Upload a document, convert it into structured knowledge (chunks, entities, embeddings, metadata), and answer queries with mandatory citations (`doc_id`, `chunk_id`) and full auditability (`trace_id`, `job_id`).

## Repository layout
- `spec/project.yaml`: single source of truth for project direction and infrastructure contract
- `sql/schema.sql`: canonical relational schema (`documents`, `jobs`, `chunks`, `entities`)
- `services/ingestion_api_service`: ingest API (`/v1/ingest`, `/v1/ingest/complete`, `/v1/doc/{id}`)
- `services/document_processor_service`: parser/chunker/embedder/DB writer (`/v1/process`, `/v1/process/pubsub`)
- `services/rag_query_service`: retrieval + answer with citations (`/v1/query`)
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
  - `/v1/process/pubsub` can remain unauthenticated until Pub/Sub push OIDC is configured.
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
- If auth is enabled, pass token:
```bash
BENCHMARK_BEARER_TOKEN='REPLACE_ME' ./scripts/run_p3_benchmark.py
```

## P3.4 CI/CD
- CI workflows:
  - `.github/workflows/ci.yml`
  - `.github/workflows/benchmark-gate.yml`
  - `.github/workflows/deploy-cloud-run.yml`
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
