#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"
VERTEX_INDEX_ID="${3:-3994068346873053184}"
VERTEX_INDEX_ENDPOINT_ID="${4:-5596857233007706112}"
VERTEX_DEPLOYED_INDEX_ID="${5:-alchimista_chunks_deployed_v3}"
VERTEX_EMBEDDING_MODEL="${VERTEX_EMBEDDING_MODEL:-text-embedding-004}"
EMBEDDING_DIMENSIONS="${EMBEDDING_DIMENSIONS:-128}"

COMMON_VERTEX_ENV="VECTOR_BACKEND=vertex_ai_vector_search,VERTEX_INDEX_ID=${VERTEX_INDEX_ID},VERTEX_INDEX_ENDPOINT_ID=${VERTEX_INDEX_ENDPOINT_ID},VERTEX_DEPLOYED_INDEX_ID=${VERTEX_DEPLOYED_INDEX_ID},EMBEDDING_BACKEND=vertex_text_embedding,VERTEX_EMBEDDING_MODEL=${VERTEX_EMBEDDING_MODEL},EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS}"

echo "Switching document-processor-service to Vertex backend..."
gcloud run services update document-processor-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "$COMMON_VERTEX_ENV" \
  --quiet >/dev/null

echo "Switching rag-query-service to Vertex backend..."
gcloud run services update rag-query-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "$COMMON_VERTEX_ENV" \
  --quiet >/dev/null

echo "Vertex backend enabled on processor and rag-query services."
