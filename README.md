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
