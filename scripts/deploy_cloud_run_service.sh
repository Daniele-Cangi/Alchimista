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
SUBMIT_OUTPUT="$(gcloud builds submit \
  --project "$PROJECT_ID" \
  --config "$TMP_CONFIG" \
  --async \
  . 2>&1)"
echo "$SUBMIT_OUTPUT"

BUILD_ID="$(printf '%s\n' "$SUBMIT_OUTPUT" | sed -nE 's#.*\/builds/([a-z0-9-]+)\].*#\1#p' | tail -n1)"

if [[ -z "$BUILD_ID" ]]; then
  echo "Failed to obtain Cloud Build ID for ${SERVICE}" >&2
  exit 1
fi

echo "Build started for ${SERVICE}: ${BUILD_ID}"
while true; do
  STATUS="$(gcloud builds describe "$BUILD_ID" --project "$PROJECT_ID" --format='value(status)')"
  case "$STATUS" in
    SUCCESS)
      echo "Build succeeded for ${SERVICE}"
      break
      ;;
    QUEUED|PENDING|WORKING)
      sleep 5
      ;;
    *)
      LOG_URL="$(gcloud builds describe "$BUILD_ID" --project "$PROJECT_ID" --format='value(logUrl)')"
      echo "Build failed for ${SERVICE}: status=${STATUS} log_url=${LOG_URL}" >&2
      exit 1
      ;;
  esac
done

echo "Deploying ${SERVICE}..."
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --image "$IMAGE" \
  --quiet >/dev/null

REVISION="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.latestReadyRevisionName)')"
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
echo "{\"service\":\"${SERVICE}\",\"image\":\"${IMAGE}\",\"revision\":\"${REVISION}\",\"url\":\"${URL}\"}"
