#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"
INGEST_SUBSCRIPTION="${3:-doc-ingest-sub}"
PUSH_SERVICE_ACCOUNT="${4:-ingestion-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
PUSH_AUDIENCE="${5:-}"

if [[ "${PUSH_SERVICE_ACCOUNT}" != *@* ]]; then
  PUSH_SERVICE_ACCOUNT="${PUSH_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
fi

PROCESSOR_SERVICE="document-processor-service"
PROCESSOR_URL="$(gcloud run services describe "${PROCESSOR_SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --format='value(status.url)')"

if [[ -z "${PROCESSOR_URL}" ]]; then
  echo "Unable to resolve ${PROCESSOR_SERVICE} URL" >&2
  exit 1
fi

PUSH_ENDPOINT="${PROCESSOR_URL}/v1/process/pubsub"
if [[ -z "${PUSH_AUDIENCE}" ]]; then
  PUSH_AUDIENCE="${PUSH_ENDPOINT}"
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
if [[ -z "${PROJECT_NUMBER}" ]]; then
  echo "Unable to resolve project number for ${PROJECT_ID}" >&2
  exit 1
fi
PUBSUB_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

echo "Granting roles/iam.serviceAccountTokenCreator on ${PUSH_SERVICE_ACCOUNT} to ${PUBSUB_SERVICE_AGENT}..."
gcloud iam service-accounts add-iam-policy-binding "${PUSH_SERVICE_ACCOUNT}" \
  --project "${PROJECT_ID}" \
  --member "serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role "roles/iam.serviceAccountTokenCreator" \
  --quiet >/dev/null

echo "Updating Pub/Sub push subscription ${INGEST_SUBSCRIPTION}..."
gcloud pubsub subscriptions update "${INGEST_SUBSCRIPTION}" \
  --project "${PROJECT_ID}" \
  --push-endpoint "${PUSH_ENDPOINT}" \
  --push-auth-service-account "${PUSH_SERVICE_ACCOUNT}" \
  --push-auth-token-audience "${PUSH_AUDIENCE}" \
  --quiet >/dev/null

echo "Enforcing authenticated Pub/Sub push on ${PROCESSOR_SERVICE}..."
gcloud run services update "${PROCESSOR_SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --update-env-vars "^#^AUTH_ALLOW_UNAUTHENTICATED_PUBSUB=false#PUBSUB_PUSH_AUTH_ENABLED=true#PUBSUB_PUSH_AUDIENCE=${PUSH_AUDIENCE}#PUBSUB_PUSH_SERVICE_ACCOUNTS=${PUSH_SERVICE_ACCOUNT}" \
  --quiet >/dev/null

echo "Pub/Sub push OIDC configured."
echo "subscription=${INGEST_SUBSCRIPTION}"
echo "push_endpoint=${PUSH_ENDPOINT}"
echo "push_service_account=${PUSH_SERVICE_ACCOUNT}"
echo "push_audience=${PUSH_AUDIENCE}"
