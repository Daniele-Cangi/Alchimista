#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-}"
PROJECT_ID="${2:-}"
REGION="${3:-}"
IMAGE_TAG="${4:-}"

if [[ -z "$SERVICE" || -z "$PROJECT_ID" || -z "$REGION" ]]; then
  echo "Usage: $0 <service> <project_id> <region> [image_tag]" >&2
  exit 1
fi

DOCKERFILE=""
case "$SERVICE" in
  ingestion-api-service)
    DOCKERFILE="services/ingestion_api_service/Dockerfile"
    ;;
  document-processor-service)
    DOCKERFILE="services/document_processor_service/Dockerfile"
    ;;
  rag-query-service)
    DOCKERFILE="services/rag_query_service/Dockerfile"
    ;;
  *)
    echo "Unsupported service: $SERVICE" >&2
    exit 1
    ;;
esac

if [[ -z "$IMAGE_TAG" ]]; then
  IMAGE_TAG="$(date -u +%Y%m%d-%H%M%S)-${SERVICE}"
fi

IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/${SERVICE}:${IMAGE_TAG}"
TMP_CONFIG="$(mktemp)"
trap 'rm -f "$TMP_CONFIG"' EXIT

cat >"$TMP_CONFIG" <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', '${IMAGE}', '-f', '${DOCKERFILE}', '.']
images:
- '${IMAGE}'
EOF

echo "Building image for ${SERVICE}..."
gcloud builds submit --project "$PROJECT_ID" --config "$TMP_CONFIG" .

echo "Deploying ${SERVICE}..."
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --image "$IMAGE" \
  --quiet >/dev/null

REVISION="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.latestReadyRevisionName)')"
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
echo "{\"service\":\"${SERVICE}\",\"image\":\"${IMAGE}\",\"revision\":\"${REVISION}\",\"url\":\"${URL}\"}"
