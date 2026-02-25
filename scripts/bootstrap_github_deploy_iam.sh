#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
DEPLOY_SA="${2:-github-deploy-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
INGEST_SA_ID="${INGEST_SA_ID:-ingestion-api-sa}"
PROCESSOR_SA_ID="${PROCESSOR_SA_ID:-document-processor-sa}"
RAG_SA_ID="${RAG_SA_ID:-rag-query-sa}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Usage: $0 <project_id> [deploy_service_account_email]" >&2
  exit 1
fi

if [[ "${DEPLOY_SA}" != *@* ]]; then
  DEPLOY_SA="${DEPLOY_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
INGEST_SA="${INGEST_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
PROCESSOR_SA="${PROCESSOR_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
RAG_SA="${RAG_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_BUILD_EXEC_SA="${CLOUD_BUILD_EXEC_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"

echo "Configuring project roles for ${DEPLOY_SA}"
for ROLE in \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.reader \
  roles/serviceusage.serviceUsageConsumer \
  roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOY_SA}" \
    --role="${ROLE}" \
    --quiet >/dev/null
  echo "  granted ${ROLE}"
done

echo "Configuring serviceAccountUser bindings"
for TARGET_SA in "${INGEST_SA}" "${PROCESSOR_SA}" "${RAG_SA}" "${CLOUD_BUILD_EXEC_SA}"; do
  if ! gcloud iam service-accounts describe "${TARGET_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "  skip ${TARGET_SA} (not found)"
    continue
  fi
  gcloud iam service-accounts add-iam-policy-binding "${TARGET_SA}" \
    --member="serviceAccount:${DEPLOY_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null
  echo "  granted roles/iam.serviceAccountUser on ${TARGET_SA}"
done

echo "Done."
