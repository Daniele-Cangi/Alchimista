# Terraform Baseline (Alchimista)

This folder is a clean Terraform baseline aligned with the current GCP project state.

## Important
- The resources already exist in GCP.
- Import before first `plan/apply` to avoid create conflicts.

## Usage
```bash
cp terraform.tfvars.example terraform.tfvars
# one-time ADC for Terraform provider auth
gcloud auth application-default login
terraform init
./import_existing.sh secure-electron-474908-k9 europe-west4
terraform plan
```

To apply only queue + storage hardening without touching Cloud Run service drift:

```bash
terraform apply \
  -target=google_pubsub_subscription.doc_ingest_sub \
  -target=google_pubsub_subscription.doc_ingest_dlq_sub \
  -target=google_kms_key_ring.alchimista_data \
  -target=google_kms_crypto_key.alchimista_data \
  -target=google_kms_crypto_key_iam_member.gcs_service_agent_key_access \
  -target=google_storage_bucket.raw \
  -target=google_storage_bucket.processed \
  -target=google_storage_bucket.reports
```

## Managed resources
- Project API enablement (minimum required services)
- VPC network (`alchimista-vpc`)
- Private service range and service networking peering
- Serverless VPC connector (`alchimista-connector`)
- Cloud SQL instance (`alchimista-test-db`)
- Pub/Sub ingest topic, subscription, DLQ topic, DLQ subscription
- KMS key ring/key for data buckets CMEK
- Raw/Processed/Reports buckets with UBLA + PAP enforced
- Cloud Run service (`my-first-app`)
- Artifact Registry repo (`cloud-run-source-deploy`)

## Notes
- `google_cloud_run_service_iam_member` is managed by apply and is not imported by default.
- `maintenance_version` for Cloud SQL is ignored to reduce noisy drift.
- First `plan` may show minor in-place drift for Cloud Run metadata annotations and Terraform labels.
