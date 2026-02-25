output "cloud_run_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_service.my_first_app.status[0].url
}

output "sql_instance_connection_name" {
  description = "Cloud SQL instance connection name"
  value       = google_sql_database_instance.alchimista_test_db.connection_name
}

output "sql_private_ip" {
  description = "Cloud SQL private IP"
  value       = google_sql_database_instance.alchimista_test_db.private_ip_address
}

output "raw_bucket_name" {
  description = "Raw bucket name"
  value       = google_storage_bucket.raw.name
}

output "processed_bucket_name" {
  description = "Processed bucket name"
  value       = google_storage_bucket.processed.name
}

output "reports_bucket_name" {
  description = "Reports bucket name"
  value       = google_storage_bucket.reports.name
}

output "cmek_crypto_key_id" {
  description = "CMEK key id used by data buckets"
  value       = google_kms_crypto_key.alchimista_data.id
}

output "ingest_topic_name" {
  description = "Pub/Sub ingest topic"
  value       = google_pubsub_topic.doc_ingest_topic.name
}

output "ingest_subscription_name" {
  description = "Pub/Sub ingest subscription"
  value       = google_pubsub_subscription.doc_ingest_sub.name
}
