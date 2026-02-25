#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"
SECRET_NAME="${SECRET_NAME:-alchimista-audit-report-signing-key}"
INGEST_SERVICE="${INGEST_SERVICE:-ingestion-api-service}"
INGEST_SA="${INGEST_SA:-ingestion-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
KEY_ID_PREFIX="${KEY_ID_PREFIX:-audit-key}"
SKIP_SECRET_BOOTSTRAP="${SKIP_SECRET_BOOTSTRAP:-false}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

if [[ "${SKIP_SECRET_BOOTSTRAP}" != "true" ]]; then
  echo "Ensuring secret ${SECRET_NAME} exists..."
  if ! gcloud secrets describe "${SECRET_NAME}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${SECRET_NAME}" \
      --project "${PROJECT_ID}" \
      --replication-policy="automatic" \
      --quiet >/dev/null
  fi

  echo "Granting Secret Manager access to ${INGEST_SA}..."
  gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
    --project "${PROJECT_ID}" \
    --member="serviceAccount:${INGEST_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null || true
else
  echo "Skipping secret bootstrap (SKIP_SECRET_BOOTSTRAP=true)"
fi

echo "Rotating AUDIT_REPORT_SIGNING_KEY secret version..."
NEW_KEY="$(openssl rand -hex 32)"
printf "%s" "${NEW_KEY}" | gcloud secrets versions add "${SECRET_NAME}" \
  --project "${PROJECT_ID}" \
  --data-file=- \
  --quiet >/dev/null
unset NEW_KEY

KEY_ID="${KEY_ID_PREFIX}-$(date -u +%Y%m%dT%H%M%SZ)"

echo "Updating ${INGEST_SERVICE} env + secret bindings..."
set +e
UPDATE_OUTPUT="$(
  gcloud run services update "${INGEST_SERVICE}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --update-secrets "AUDIT_REPORT_SIGNING_KEY=${SECRET_NAME}:latest" \
    --update-env-vars "AUDIT_REPORT_SIGNING_KEY_ID=${KEY_ID}" \
    --quiet 2>&1
)"
UPDATE_EXIT=$?
set -e
if [[ ${UPDATE_EXIT} -ne 0 ]]; then
  if grep -q "different type" <<<"${UPDATE_OUTPUT}"; then
    echo "Converting AUDIT_REPORT_SIGNING_KEY from plain env var to secret binding..."
    gcloud run services update "${INGEST_SERVICE}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --remove-env-vars "AUDIT_REPORT_SIGNING_KEY" \
      --quiet >/dev/null
    gcloud run services update "${INGEST_SERVICE}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --update-secrets "AUDIT_REPORT_SIGNING_KEY=${SECRET_NAME}:latest" \
      --update-env-vars "AUDIT_REPORT_SIGNING_KEY_ID=${KEY_ID}" \
      --quiet >/dev/null
  else
    echo "${UPDATE_OUTPUT}" >&2
    exit ${UPDATE_EXIT}
  fi
fi

echo "AUDIT_REPORT_SIGNING_KEY rotated and bound via Secret Manager."
echo "secret_name=${SECRET_NAME}"
echo "service=${INGEST_SERVICE}"
echo "key_id=${KEY_ID}"
