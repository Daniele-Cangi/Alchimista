#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"

INDEX_DISPLAY_NAME="${INDEX_DISPLAY_NAME:-alchimista-doc-chunks-v2}"
ENDPOINT_DISPLAY_NAME="${ENDPOINT_DISPLAY_NAME:-alchimista-doc-chunks-endpoint-v2}"
DEPLOYED_INDEX_ID="${DEPLOYED_INDEX_ID:-alchimista_chunks_deployed_v3}"

DIMENSIONS="${DIMENSIONS:-128}"
PROCESSED_BUCKET="${PROCESSED_BUCKET:-alchimista-processed-994021588311}"
CONTENTS_DELTA_PATH="${CONTENTS_DELTA_PATH:-vertex/index-data-v2}"

INDEX_META_FILE="/tmp/alchimista-vertex-index-metadata.json"
cat > "$INDEX_META_FILE" <<JSON
{
  "contentsDeltaUri": "gs://${PROCESSED_BUCKET}/${CONTENTS_DELTA_PATH}",
  "config": {
    "dimensions": ${DIMENSIONS},
    "approximateNeighborsCount": 20,
    "distanceMeasureType": "DOT_PRODUCT_DISTANCE",
    "algorithmConfig": {
      "treeAhConfig": {
        "leafNodeEmbeddingCount": 1000,
        "leafNodesToSearchPercent": 7
      }
    },
    "shardSize": "SHARD_SIZE_SMALL"
  }
}
JSON

find_index_name() {
  gcloud ai indexes list \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format=json | jq -r --arg n "$INDEX_DISPLAY_NAME" '.[] | select(.displayName==$n) | .name' | head -n1
}

find_endpoint_name() {
  gcloud ai index-endpoints list \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format=json | jq -r --arg n "$ENDPOINT_DISPLAY_NAME" '.[] | select(.displayName==$n) | .name' | head -n1
}

echo "Ensuring Vertex index exists..."
INDEX_NAME="$(find_index_name)"
if [[ -z "$INDEX_NAME" ]]; then
  gcloud ai indexes create \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --display-name "$INDEX_DISPLAY_NAME" \
    --description "Alchimista chunk embeddings index (stream update)" \
    --index-update-method stream-update \
    --metadata-file "$INDEX_META_FILE" \
    --quiet >/dev/null
fi

for _ in $(seq 1 60); do
  INDEX_NAME="$(find_index_name)"
  [[ -n "$INDEX_NAME" ]] && break
  sleep 10
done
if [[ -z "$INDEX_NAME" ]]; then
  echo "Index was not found after create wait loop" >&2
  exit 1
fi

echo "Ensuring Vertex index endpoint exists..."
ENDPOINT_NAME="$(find_endpoint_name)"
if [[ -z "$ENDPOINT_NAME" ]]; then
  gcloud ai index-endpoints create \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --display-name "$ENDPOINT_DISPLAY_NAME" \
    --description "Public endpoint for Alchimista vector search" \
    --public-endpoint-enabled \
    --quiet >/dev/null
fi

for _ in $(seq 1 60); do
  ENDPOINT_NAME="$(find_endpoint_name)"
  [[ -n "$ENDPOINT_NAME" ]] && break
  sleep 10
done
if [[ -z "$ENDPOINT_NAME" ]]; then
  echo "Index endpoint was not found after create wait loop" >&2
  exit 1
fi

INDEX_ID="${INDEX_NAME##*/}"
ENDPOINT_ID="${ENDPOINT_NAME##*/}"

DEPLOYED_ALREADY="$(
  gcloud ai index-endpoints describe "$ENDPOINT_ID" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format=json | jq -r --arg did "$DEPLOYED_INDEX_ID" 'any((.deployedIndexes // [])[]?; .id == $did)'
)"

if [[ "$DEPLOYED_ALREADY" != "true" ]]; then
  echo "Submitting deploy-index operation..."
  set +e
  DEPLOY_OUTPUT="$(
    gcloud ai index-endpoints deploy-index "$ENDPOINT_ID" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --index "$INDEX_NAME" \
      --deployed-index-id "$DEPLOYED_INDEX_ID" \
      --display-name "$DEPLOYED_INDEX_ID" \
      --min-replica-count 1 \
      --max-replica-count 1 \
      --enable-access-logging \
      --quiet 2>&1
  )"
  DEPLOY_EXIT=$?
  set -e
  if [[ $DEPLOY_EXIT -ne 0 ]]; then
    if grep -q "ALREADY_EXISTS" <<<"$DEPLOY_OUTPUT"; then
      echo "Deploy already exists; continuing wait loop..."
    else
      echo "$DEPLOY_OUTPUT" >&2
      exit $DEPLOY_EXIT
    fi
  fi
fi

echo "Waiting for deployed index to become active..."
for _ in $(seq 1 180); do
  READY="$(
    gcloud ai index-endpoints describe "$ENDPOINT_ID" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --format=json | jq -r --arg did "$DEPLOYED_INDEX_ID" 'any((.deployedIndexes // [])[]?; .id == $did)'
  )"
  if [[ "$READY" == "true" ]]; then
    break
  fi
  sleep 10
done

READY="$(
  gcloud ai index-endpoints describe "$ENDPOINT_ID" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format=json | jq -r --arg did "$DEPLOYED_INDEX_ID" 'any((.deployedIndexes // [])[]?; .id == $did)'
)"

if [[ "$READY" != "true" ]]; then
  echo "Deployed index did not become ready within timeout" >&2
  exit 1
fi

echo "vertex_index_id=${INDEX_ID}"
echo "vertex_index_endpoint_id=${ENDPOINT_ID}"
echo "vertex_deployed_index_id=${DEPLOYED_INDEX_ID}"
