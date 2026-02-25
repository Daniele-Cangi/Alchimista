#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"

INGEST_SUBSCRIPTION="${INGEST_SUBSCRIPTION:-doc-ingest-sub}"
DLQ_TOPIC="${DLQ_TOPIC:-doc-ingest-topic-dlq}"

INGEST_MAX_INSTANCES="${INGEST_MAX_INSTANCES:-10}"
INGEST_CONCURRENCY="${INGEST_CONCURRENCY:-80}"
PROCESSOR_MAX_INSTANCES="${PROCESSOR_MAX_INSTANCES:-4}"
PROCESSOR_CONCURRENCY="${PROCESSOR_CONCURRENCY:-4}"
PROCESSOR_TIMEOUT="${PROCESSOR_TIMEOUT:-900}"
PROCESSOR_MAX_INFLIGHT="${PROCESSOR_MAX_INFLIGHT:-8}"
RAG_MAX_INSTANCES="${RAG_MAX_INSTANCES:-8}"
RAG_CONCURRENCY="${RAG_CONCURRENCY:-40}"

ACK_DEADLINE_SECONDS="${ACK_DEADLINE_SECONDS:-60}"
MAX_DELIVERY_ATTEMPTS="${MAX_DELIVERY_ATTEMPTS:-5}"
MIN_RETRY_DELAY="${MIN_RETRY_DELAY:-10s}"
MAX_RETRY_DELAY="${MAX_RETRY_DELAY:-300s}"

echo "Applying Cloud Run backpressure settings..."
gcloud run services update ingestion-api-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --max-instances "$INGEST_MAX_INSTANCES" \
  --concurrency "$INGEST_CONCURRENCY" \
  --quiet >/dev/null

gcloud run services update document-processor-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --max-instances "$PROCESSOR_MAX_INSTANCES" \
  --concurrency "$PROCESSOR_CONCURRENCY" \
  --timeout "$PROCESSOR_TIMEOUT" \
  --update-env-vars "PROCESSOR_MAX_INFLIGHT=$PROCESSOR_MAX_INFLIGHT" \
  --quiet >/dev/null

gcloud run services update rag-query-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --max-instances "$RAG_MAX_INSTANCES" \
  --concurrency "$RAG_CONCURRENCY" \
  --quiet >/dev/null

echo "Applying Pub/Sub retry budget settings..."
gcloud pubsub subscriptions update "$INGEST_SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --ack-deadline "$ACK_DEADLINE_SECONDS" \
  --dead-letter-topic "$DLQ_TOPIC" \
  --max-delivery-attempts "$MAX_DELIVERY_ATTEMPTS" \
  --min-retry-delay "$MIN_RETRY_DELAY" \
  --max-retry-delay "$MAX_RETRY_DELAY" \
  --quiet >/dev/null

echo "P2 backpressure applied."
echo "processor_max_inflight=$PROCESSOR_MAX_INFLIGHT"
echo "processor_concurrency=$PROCESSOR_CONCURRENCY"
echo "processor_max_instances=$PROCESSOR_MAX_INSTANCES"
echo "subscription_max_delivery_attempts=$MAX_DELIVERY_ATTEMPTS"
