#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

echo "Importing existing Alchimista resources into Terraform state..."

test -f versions.tf || {
  echo "Run this script from infra/terraform" >&2
  exit 1
}

terraform init

terraform import google_compute_network.alchimista_vpc "projects/${PROJECT_ID}/global/networks/alchimista-vpc" || true
terraform import google_compute_global_address.alchimista_private_ip_alloc "projects/${PROJECT_ID}/global/addresses/alchimista-private-ip-alloc" || true
terraform import google_service_networking_connection.private_vpc_connection "projects/${PROJECT_ID}/global/networks/alchimista-vpc:servicenetworking.googleapis.com" || true
terraform import google_vpc_access_connector.alchimista_connector "projects/${PROJECT_ID}/locations/${REGION}/connectors/alchimista-connector" || true
terraform import google_sql_database_instance.alchimista_test_db "projects/${PROJECT_ID}/instances/alchimista-test-db" || true
terraform import google_artifact_registry_repository.cloud_run_source_deploy "projects/${PROJECT_ID}/locations/us-central1/repositories/cloud-run-source-deploy" || true
terraform import google_cloud_run_service.my_first_app "locations/${REGION}/namespaces/${PROJECT_ID}/services/my-first-app" || true
terraform import google_pubsub_topic.doc_ingest_topic "projects/${PROJECT_ID}/topics/doc-ingest-topic" || true
terraform import google_pubsub_topic.doc_ingest_topic_dlq "projects/${PROJECT_ID}/topics/doc-ingest-topic-dlq" || true
terraform import google_pubsub_topic_iam_member.doc_ingest_dlq_publisher "projects/${PROJECT_ID}/topics/doc-ingest-topic-dlq roles/pubsub.publisher serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" || true
terraform import google_pubsub_subscription.doc_ingest_sub "projects/${PROJECT_ID}/subscriptions/doc-ingest-sub" || true
terraform import google_pubsub_subscription.doc_ingest_dlq_sub "projects/${PROJECT_ID}/subscriptions/doc-ingest-topic-dlq-sub" || true
terraform import google_kms_key_ring.alchimista_data "projects/${PROJECT_ID}/locations/${REGION}/keyRings/alchimista-data-kr" || true
terraform import google_kms_crypto_key.alchimista_data "projects/${PROJECT_ID}/locations/${REGION}/keyRings/alchimista-data-kr/cryptoKeys/alchimista-data-key" || true
terraform import google_storage_bucket.raw "alchimista-raw-${PROJECT_NUMBER}" || true
terraform import google_storage_bucket.processed "alchimista-processed-${PROJECT_NUMBER}" || true
terraform import google_storage_bucket.reports "alchimista-reports-${PROJECT_NUMBER}" || true
terraform import 'google_cloud_run_service_iam_member.my_first_app_public_invoker[0]' "v1/projects/${PROJECT_ID}/locations/${REGION}/services/my-first-app/roles/run.invoker/allUsers" || true

for api in \
  artifactregistry.googleapis.com \
  cloudkms.googleapis.com \
  cloudresourcemanager.googleapis.com \
  compute.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  servicenetworking.googleapis.com \
  serviceusage.googleapis.com \
  storage.googleapis.com \
  sqladmin.googleapis.com \
  vpcaccess.googleapis.com
  do
  terraform import "google_project_service.required[\"${api}\"]" "${PROJECT_ID}/${api}" || true
done

echo "Import completed. Run: terraform plan"
