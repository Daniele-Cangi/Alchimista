# P3.4 CI/CD Discipline

This stage introduces objective quality gates before release and controlled Cloud Run deployment.

## Workflows
- `.github/workflows/ci.yml`
  - Runs `pytest` on push and pull request.
  - Validates benchmark gate config exists in `spec/project.yaml`.
- `.github/workflows/benchmark-gate.yml`
  - Runs benchmark against deployed services (manual + nightly schedule).
  - Enforces gate thresholds from `spec/project.yaml`.
  - Uploads `reports/benchmarks/latest.json` as artifact.
- `.github/workflows/deploy-cloud-run.yml`
  - Manual deploy workflow (`workflow_dispatch`).
  - Builds each service image with Cloud Build and deploys to Cloud Run.
  - Executes `/v1/readyz` checks after deployment.

## Required GitHub secrets
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `AUTH0_CLIENT_ID` (M2M app authorized on `https://api.alchimista.ai`)
- `AUTH0_CLIENT_SECRET`

## Helper scripts
- `scripts/deploy_cloud_run_service.sh`: build + deploy one service.
- `scripts/check_benchmark_gate.py`: validates benchmark metrics against spec gates.

## Operator notes
- Keep `benchmark.gates` in `spec/project.yaml` as the single source of truth.
- Use `deploy-cloud-run` with `target=all` for synchronized revision rollout.
- Keep `benchmark-gate` green before major production changes.
