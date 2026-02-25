# Recovery Notes (2026-02-25)

## Facts verified
- Local machine had no Alchimista repository.
- Cloud Run deployed source was retrievable from `run-sources-*` bucket.
- Retrieved source was Google sample service (`hello.go`), not domain product logic.
- Live production-like resources existed in project `secure-electron-474908-k9`.

## Current infra baseline
- Region: `europe-west4`
- Cloud Run: `my-first-app`
- Cloud SQL: `alchimista-test-db` (PostgreSQL 15, private IP)
- VPC: `alchimista-vpc`
- VPC Connector: `alchimista-connector`
- Artifact Registry: `cloud-run-source-deploy`

## Risk statement
Without the original code repository/history, exact business logic cannot be reconstructed automatically from GCP runtime resources alone.
