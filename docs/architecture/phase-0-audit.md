# Phase 0 implementation audit

Audit date: 2026-08-11. Baseline Alchimista revision:
`17b54393cf` (`main` at audit time).

## Before this revision

| Concern | Actual implementation and dependency |
| --- | --- |
| runtime config | `services/shared/config.py` required `PROJECT_ID` and `DATABASE_URL` during every service import |
| object storage | `services/shared/storage.py` implemented GCS only; ingestion, reports, retention deletion, and processor downloads used `gs://` |
| message delivery | `services/shared/pubsub_client.py` implemented Pub/Sub only; ingestion and DLQ paths instantiated Google clients eagerly |
| processor | `services/document_processor_service/main.py` downloaded from GCS, extracted text, stored chunks/entities, embedded, and optionally synchronized Vertex |
| RAG | `services/rag_query_service/main.py` already had a usable tenant-filtered SQL scan and optional Vertex fallback |
| embeddings | deterministic offline embeddings already existed; Vertex was selected by configuration |
| authentication | general JWT/OIDC verification was provider-independent, but configuration was a boolean and dashboard convenience code was Auth0-specific |
| service identity | Google Pub/Sub push validation was implemented in the general auth module but was logically distinct |
| database | PostgreSQL/psycopg was already the canonical store; schema bootstrap required a manual `psql` command |
| entity privacy | `entities.entity_value` stored regex matches in cleartext |
| audit artifacts | report/export/package writes required GCS; decision context previews could contain raw chunk text |
| dashboard | default URLs were local, but the operational guidance and token helper centered on Cloud Run/Auth0 |
| deployment | four service Dockerfiles existed; there was no supported multi-service Compose stack |
| CI | unit tests were secret-free, while benchmark/deploy/retention workflows were separate GCP workflows |

The useful cloud dependencies were already reasonably centralized in
`services/shared`, so a small set of factories was sufficient. A general
rewrite or plugin framework was not justified.

## Rizzo comparison

- Fork inspected: `Daniele-Cangi/rizzo-pii` at
  `ca22525fa98e696c48d34ba1a3c096dc5e4e1fe6`.
- Upstream inspected: `Rizzo-AI-Academy/rizzo-pii` at
  `42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5`.
- Git comparison: fork was 0 commits ahead and 17 commits behind upstream.
- GitHub API reported upstream source license `MIT`.
- Upstream added Compose, model pin `v1.5.0`, release changes, and
  `THIRD_PARTY_LICENSES.md` after the fork revision.

Decision: incorporate only the pinned text-only regex/checksum module with its
MIT notice. Keep the full ML/PDF/UI application external and optional through
a pinned HTTP adapter. This avoids PyMuPDF and duplicate PDF parsing in the
default image.

## Boundaries introduced

- `ALCHIMISTA_PROFILE=local|gcp`
- `STORAGE_BACKEND=filesystem|gcs`
- `QUEUE_BACKEND=direct_http|pubsub`
- `AUTH_MODE=local|oidc|disabled`
- `PRIVACY_POLICY=off|detect|protect_egress|strict`
- narrow privacy API and AES-GCM vault
- explicit external-text egress guard

Existing API contracts, PostgreSQL, SQL RAG, decision evidence, retention,
legal holds, GCS, Pub/Sub, Vertex, Cloud Run, and OIDC code were retained.
