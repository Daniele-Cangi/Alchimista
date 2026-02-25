#!/usr/bin/env bash
set -euo pipefail

INGEST_URL="${INGEST_URL:-https://ingestion-api-service-pe7qslbcvq-ez.a.run.app}"
TENANT="${TENANT:-default}"
ARTIFACT_TYPE="${ARTIFACT_TYPE:-}"
DRY_RUN_RAW="${DRY_RUN:-true}"
LIMIT="${LIMIT:-200}"
TRACE_ID="${TRACE_ID:-}"
TOKEN="${TOKEN:-${BENCHMARK_BEARER_TOKEN:-}}"
ADMIN_API_KEY="${ADMIN_API_KEY:-}"
ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-}"
PROJECT_ID="${PROJECT_ID:-secure-electron-474908-k9}"
FAIL_ON_ERRORS_RAW="${FAIL_ON_ERRORS:-true}"
OUTPUT_JSON_PATH="${OUTPUT_JSON_PATH:-/tmp/p6_retention_enforce.json}"

normalize_bool() {
  local value
  value="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1|true|yes|y|on) echo "true" ;;
    0|false|no|n|off) echo "false" ;;
    *)
      echo "Invalid boolean value: $1" >&2
      exit 1
      ;;
  esac
}

DRY_RUN="$(normalize_bool "$DRY_RUN_RAW")"
FAIL_ON_ERRORS="$(normalize_bool "$FAIL_ON_ERRORS_RAW")"

if [[ -z "$TOKEN" ]]; then
  echo "TOKEN (or BENCHMARK_BEARER_TOKEN) is required" >&2
  exit 1
fi

if [[ -z "$ADMIN_API_KEY" && -n "$ADMIN_API_KEY_SECRET" ]]; then
  ADMIN_API_KEY="$(
    gcloud secrets versions access latest \
      --secret "$ADMIN_API_KEY_SECRET" \
      --project "$PROJECT_ID"
  )"
fi

if [[ -z "$ADMIN_API_KEY" ]]; then
  echo "ADMIN_API_KEY is required (or set ADMIN_API_KEY_SECRET)" >&2
  exit 1
fi

ARTIFACT_JSON="null"
if [[ -n "$ARTIFACT_TYPE" ]]; then
  ARTIFACT_JSON="$(jq -Rn --arg v "$ARTIFACT_TYPE" '$v')"
fi

TRACE_JSON="null"
if [[ -n "$TRACE_ID" ]]; then
  TRACE_JSON="$(jq -Rn --arg v "$TRACE_ID" '$v')"
fi

PAYLOAD="$(
  jq -n \
    --arg tenant "$TENANT" \
    --argjson artifact_type "$ARTIFACT_JSON" \
    --argjson dry_run "$DRY_RUN" \
    --argjson limit "$LIMIT" \
    --argjson trace_id "$TRACE_JSON" \
    '{
      tenant: $tenant,
      artifact_type: $artifact_type,
      dry_run: $dry_run,
      limit: $limit,
      trace_id: $trace_id
    }'
)"

HTTP_CODE="$(
  curl -sS -o "$OUTPUT_JSON_PATH" -w "%{http_code}" \
    -X POST "${INGEST_URL}/v1/admin/retention/enforce" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "x-admin-key: ${ADMIN_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"
)"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "Retention enforcement failed with HTTP ${HTTP_CODE}" >&2
  cat "$OUTPUT_JSON_PATH" >&2 || true
  exit 1
fi

jq '{
  trace_id,
  dry_run,
  tenant,
  artifact_type,
  scanned,
  eligible,
  deleted,
  skipped_not_expired,
  skipped_on_hold,
  skipped_policy_missing,
  failed,
  items_preview: (.items | .[0:5])
}' "$OUTPUT_JSON_PATH"

FAILED_COUNT="$(jq -r '.failed // 0' "$OUTPUT_JSON_PATH")"
if [[ "$FAIL_ON_ERRORS" == "true" && "$FAILED_COUNT" != "0" ]]; then
  echo "Retention enforcement returned failed=${FAILED_COUNT}" >&2
  exit 1
fi
