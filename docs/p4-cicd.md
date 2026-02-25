# P3.4 CI/CD Discipline

This stage introduces objective quality gates before release and controlled Cloud Run deployment.

## Workflows
- `.github/workflows/ci.yml`
  - Runs `pytest` on push and pull request.
  - Validates benchmark gate config exists in `spec/project.yaml`.
- `.github/workflows/benchmark-gate.yml`
  - Runs benchmark against deployed services (manual + nightly schedule).
  - Uses GitHub Environment secrets (`environment=test` by default).
  - Enforces gate thresholds from `spec/project.yaml`.
  - Uploads `reports/benchmarks/latest.json` as artifact.
- `.github/workflows/deploy-cloud-run.yml`
  - Manual deploy workflow (`workflow_dispatch`).
  - Uses GitHub Environment secrets (`environment_name` input, default `test`).
  - Builds each service image with Cloud Build and deploys to Cloud Run.
  - Executes `/v1/readyz` checks after deployment.
- `.github/workflows/rotate-audit-signing-key.yml`
  - Manual and scheduled (`monthly`) secret rotation workflow for `AUDIT_REPORT_SIGNING_KEY`.
  - Runs `scripts/rotate_audit_report_signing_key_secret.sh` and updates `ingestion-api-service`.
- `.github/workflows/retention-enforce.yml`
  - Manual and scheduled (`daily`) governance workflow for `POST /v1/admin/retention/enforce`.
  - Scheduled mode is safe by default (`dry_run=true`).
  - Manual dispatch supports `dry_run=false` for controlled deletion windows.

## Required GitHub environment secrets
- Environment: `test`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `AUTH0_CLIENT_ID` (M2M app authorized on `https://api.alchimista.ai`)
- `AUTH0_CLIENT_SECRET`
- `ADMIN_API_KEY` (optional but recommended; if absent, workflow attempts Secret Manager fallback)

## Required GCP IAM for deploy service account
The service account referenced by `GCP_DEPLOY_SERVICE_ACCOUNT` must have at least:
- Project roles:
  - `roles/run.admin`
  - `roles/cloudbuild.builds.editor`
  - `roles/artifactregistry.reader`
  - `roles/serviceusage.serviceUsageConsumer`
  - `roles/storage.objectAdmin` (Cloud Build source staging bucket access)
- Service account level role (`roles/iam.serviceAccountUser`) on:
  - `ingestion-api-sa@<project>.iam.gserviceaccount.com`
  - `document-processor-sa@<project>.iam.gserviceaccount.com`
  - `rag-query-sa@<project>.iam.gserviceaccount.com`
  - Cloud Build execution SA used by your project (often `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`)
- Secret-level role for rotation workflow:
  - `roles/secretmanager.secretVersionAdder` on `alchimista-audit-report-signing-key`

## Helper scripts
- `scripts/deploy_cloud_run_service.sh`: build + deploy one service.
- `scripts/check_benchmark_gate.py`: validates benchmark metrics against spec gates.
- `scripts/bootstrap_github_deploy_iam.sh`: grants IAM roles required by `deploy-cloud-run`.
- `scripts/rotate_audit_report_signing_key_secret.sh`: rotates HMAC signing key in Secret Manager and rebinds ingestion service.
- `scripts/run_p6_retention_enforcement.sh`: executes retention enforcement with consistent payload, summary output, and error gate.

## Operator notes
- Keep `benchmark.gates` in `spec/project.yaml` as the single source of truth.
- Use `deploy-cloud-run` with `target=all` for synchronized revision rollout.
- Keep `benchmark-gate` green before major production changes.
