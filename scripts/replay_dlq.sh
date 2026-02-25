#!/usr/bin/env bash
set -euo pipefail

INGEST_URL="${INGEST_URL:-https://ingestion-api-service-pe7qslbcvq-ez.a.run.app}"
MAX_MESSAGES="${MAX_MESSAGES:-10}"
ADMIN_API_KEY="${ADMIN_API_KEY:-}"
ADMIN_API_KEY_SECRET="${ADMIN_API_KEY_SECRET:-}"
PROJECT_ID="${PROJECT_ID:-secure-electron-474908-k9}"

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

curl -fsS -X POST "${INGEST_URL}/v1/admin/replay-dlq" \
  -H "content-type: application/json" \
  -H "x-admin-key: ${ADMIN_API_KEY}" \
  -d "{\"max_messages\":${MAX_MESSAGES}}"
echo
