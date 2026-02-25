#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"
SECRET_NAME="${SECRET_NAME:-alchimista-admin-api-key}"
INGEST_SERVICE="${INGEST_SERVICE:-ingestion-api-service}"
INGEST_SA="${INGEST_SA:-ingestion-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

echo "Ensuring secret ${SECRET_NAME} exists..."
if ! gcloud secrets describe "$SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET_NAME" \
    --project "$PROJECT_ID" \
    --replication-policy="automatic" \
    --quiet >/dev/null
fi

echo "Granting Secret Manager access to ${INGEST_SA}..."
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project "$PROJECT_ID" \
  --member="serviceAccount:${INGEST_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet >/dev/null || true

echo "Rotating ADMIN_API_KEY secret version..."
NEW_KEY="$(openssl rand -hex 24)"
printf "%s" "$NEW_KEY" | gcloud secrets versions add "$SECRET_NAME" \
  --project "$PROJECT_ID" \
  --data-file=- \
  --quiet >/dev/null
unset NEW_KEY

echo "Updating ${INGEST_SERVICE} to use Secret Manager env binding..."
gcloud run services update "$INGEST_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-secrets "ADMIN_API_KEY=${SECRET_NAME}:latest" \
  --quiet >/dev/null

echo "ADMIN_API_KEY rotated and bound via Secret Manager."
echo "secret_name=${SECRET_NAME}"
echo "ingestion_service=${INGEST_SERVICE}"
