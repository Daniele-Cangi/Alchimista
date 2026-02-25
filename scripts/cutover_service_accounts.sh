#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"

RAW_BUCKET="${RAW_BUCKET:-alchimista-raw-994021588311}"
PROCESSED_BUCKET="${PROCESSED_BUCKET:-alchimista-processed-994021588311}"
REPORTS_BUCKET="${REPORTS_BUCKET:-alchimista-reports-994021588311}"
INGEST_TOPIC="${INGEST_TOPIC:-doc-ingest-topic}"
DLQ_TOPIC="${DLQ_TOPIC:-doc-ingest-topic-dlq}"
DLQ_SUBSCRIPTION="${DLQ_SUBSCRIPTION:-doc-ingest-topic-dlq-sub}"
DB_SECRET="${DB_SECRET:-alchimista-db-url}"

INGEST_SA_ID="${INGEST_SA_ID:-ingestion-api-sa}"
PROCESSOR_SA_ID="${PROCESSOR_SA_ID:-document-processor-sa}"
RAG_SA_ID="${RAG_SA_ID:-rag-query-sa}"

INGEST_SA="${INGEST_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
PROCESSOR_SA="${PROCESSOR_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
RAG_SA="${RAG_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

create_sa_if_missing() {
  local sa_id="$1"
  local display="$2"
  local sa_email="${sa_id}@${PROJECT_ID}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$sa_email" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$sa_id" --project "$PROJECT_ID" --display-name "$display" --quiet
  fi
}

echo "Creating service accounts if missing..."
create_sa_if_missing "$INGEST_SA_ID" "Ingestion API Service SA"
create_sa_if_missing "$PROCESSOR_SA_ID" "Document Processor Service SA"
create_sa_if_missing "$RAG_SA_ID" "RAG Query Service SA"

echo "Granting secret and Cloud SQL access..."
for SA in "$INGEST_SA" "$PROCESSOR_SA" "$RAG_SA"; do
  gcloud secrets add-iam-policy-binding "$DB_SECRET" \
    --project "$PROJECT_ID" \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null || true

  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" \
    --role="roles/cloudsql.client" \
    --quiet >/dev/null || true
done

echo "Granting ingestion service permissions..."
for ROLE in roles/storage.objectAdmin roles/storage.bucketViewer; do
  gcloud storage buckets add-iam-policy-binding "gs://${RAW_BUCKET}" \
    --member="serviceAccount:${INGEST_SA}" \
    --role="$ROLE" \
    --project "$PROJECT_ID" \
    --quiet >/dev/null || true
done

gcloud pubsub topics add-iam-policy-binding "$INGEST_TOPIC" \
  --project "$PROJECT_ID" \
  --member="serviceAccount:${INGEST_SA}" \
  --role="roles/pubsub.publisher" \
  --quiet >/dev/null || true

gcloud pubsub subscriptions add-iam-policy-binding "$DLQ_SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --member="serviceAccount:${INGEST_SA}" \
  --role="roles/pubsub.subscriber" \
  --quiet >/dev/null || true

gcloud iam service-accounts add-iam-policy-binding "$INGEST_SA" \
  --project "$PROJECT_ID" \
  --member="serviceAccount:${INGEST_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --quiet >/dev/null || true

echo "Granting processor service permissions..."
for ROLE in roles/storage.objectViewer roles/storage.bucketViewer; do
  gcloud storage buckets add-iam-policy-binding "gs://${RAW_BUCKET}" \
    --member="serviceAccount:${PROCESSOR_SA}" \
    --role="$ROLE" \
    --project "$PROJECT_ID" \
    --quiet >/dev/null || true
done

for ROLE in roles/storage.objectAdmin roles/storage.bucketViewer; do
  gcloud storage buckets add-iam-policy-binding "gs://${PROCESSED_BUCKET}" \
    --member="serviceAccount:${PROCESSOR_SA}" \
    --role="$ROLE" \
    --project "$PROJECT_ID" \
    --quiet >/dev/null || true
  gcloud storage buckets add-iam-policy-binding "gs://${REPORTS_BUCKET}" \
    --member="serviceAccount:${PROCESSOR_SA}" \
    --role="$ROLE" \
    --project "$PROJECT_ID" \
    --quiet >/dev/null || true
done

gcloud pubsub topics add-iam-policy-binding "$DLQ_TOPIC" \
  --project "$PROJECT_ID" \
  --member="serviceAccount:${PROCESSOR_SA}" \
  --role="roles/pubsub.publisher" \
  --quiet >/dev/null || true

echo "Switching Cloud Run services to dedicated service accounts..."
gcloud run services update ingestion-api-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$INGEST_SA" \
  --quiet

gcloud run services update document-processor-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$PROCESSOR_SA" \
  --quiet

gcloud run services update rag-query-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$RAG_SA" \
  --quiet

echo "Cutover complete."
echo "ingestion_api_sa=${INGEST_SA}"
echo "document_processor_sa=${PROCESSOR_SA}"
echo "rag_query_sa=${RAG_SA}"
