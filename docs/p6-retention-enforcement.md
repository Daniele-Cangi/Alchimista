# P6 Retention Enforcement

P6 makes governance executable: retention policies and legal holds are now enforced by an admin endpoint, with dry-run support and traceable deletion metadata.

## Endpoint
- `POST /v1/admin/retention/enforce`

## Auth
- valid JWT/OIDC bearer token
- `x-admin-key`

## Request
```json
{
  "tenant": "default",
  "artifact_type": "decision_export",
  "dry_run": true,
  "limit": 200,
  "trace_id": "optional-uuid"
}
```

Notes:
- `tenant` optional. If omitted, enforcement scans all tenants.
- `artifact_type` defaults to `audit_artifacts`.
- `dry_run=true` computes actions without deleting objects.

## Response summary
- `scanned`: artifacts evaluated.
- `eligible`: artifacts expired by retention policy.
- `deleted`: artifacts deleted from GCS and soft-marked in SQL.
- `skipped_not_expired`: retention window not reached.
- `skipped_on_hold`: blocked by active legal hold.
- `skipped_policy_missing`: no policy configured for that tenant/artifact type.
- `failed`: delete attempt failed.
- `items[]`: per-artifact decision with action and reason.

## Legal hold matching rules
Active legal holds are enforced when policy `legal_hold_enabled=true`.

Supported scope mapping:
- `scope_type=tenant`: matches tenant (or `*`).
- `scope_type=artifact`: matches `artifact_id` or `gs_uri`.
- `scope_type=decision`: matches `metadata.decision_id` or `metadata.decision_ids[]`.
- `scope_type=document`: matches `metadata.context_docs[]`.
- `scope_type=case`: matches `metadata.case_id`.

## SQL lifecycle changes
`audit_artifacts` now tracks soft-delete state:
- `deleted_at`
- `deleted_by`
- `deletion_reason`
- `delete_job_id`

Objects are deleted from GCS with generation precondition when generation metadata is available.

## Automation
- GitHub workflow: `.github/workflows/retention-enforce.yml`
- Schedule:
  - daily at `03:40 UTC` (`cron: 40 3 * * *`, `dry_run=true`)
  - maintenance window at `02:10 UTC` on Sunday (`cron: 10 2 * * 0`)
- Maintenance delete window feature flag:
  - GitHub Environment secret `RETENTION_DELETE_WINDOW_ENABLED`
  - only when set to `true`, Sunday maintenance schedule runs with `dry_run=false`
  - otherwise it degrades safely to `dry_run=true`
- Manual dispatch supports deletion mode (`dry_run=false`) for controlled maintenance windows.
