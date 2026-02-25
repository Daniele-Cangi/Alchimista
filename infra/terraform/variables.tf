variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "secure-electron-474908-k9"
}

variable "project_number" {
  description = "GCP project number"
  type        = string
  default     = "994021588311"
}

variable "region" {
  description = "Primary region"
  type        = string
  default     = "europe-west4"
}

variable "zone" {
  description = "Primary zone"
  type        = string
  default     = "europe-west4-a"
}

variable "network_name" {
  description = "VPC network name"
  type        = string
  default     = "alchimista-vpc"
}

variable "private_service_range_name" {
  description = "Name of private service networking range"
  type        = string
  default     = "alchimista-private-ip-alloc"
}

variable "private_service_range_address" {
  description = "Base address for private service range"
  type        = string
  default     = "172.26.0.0"
}

variable "private_service_range_prefix_length" {
  description = "Prefix length for private service range"
  type        = number
  default     = 16
}

variable "connector_name" {
  description = "Serverless VPC connector name"
  type        = string
  default     = "alchimista-connector"
}

variable "connector_ip_cidr_range" {
  description = "Serverless VPC connector CIDR"
  type        = string
  default     = "10.8.0.0/28"
}

variable "connector_machine_type" {
  description = "Serverless VPC connector machine type"
  type        = string
  default     = "e2-micro"
}

variable "connector_min_instances" {
  description = "Minimum connector instances"
  type        = number
  default     = 2
}

variable "connector_max_instances" {
  description = "Maximum connector instances"
  type        = number
  default     = 3
}

variable "ingest_topic_name" {
  description = "Pub/Sub topic for document ingest events"
  type        = string
  default     = "doc-ingest-topic"
}

variable "ingest_dlq_topic_name" {
  description = "Pub/Sub dead-letter topic for ingest failures"
  type        = string
  default     = "doc-ingest-topic-dlq"
}

variable "ingest_subscription_name" {
  description = "Pub/Sub subscription consumed by document processor"
  type        = string
  default     = "doc-ingest-sub"
}

variable "ingest_subscription_ack_deadline_seconds" {
  description = "Ack deadline for ingest subscription"
  type        = number
  default     = 30
}

variable "ingest_subscription_retention_duration" {
  description = "Retention duration for ingest subscription messages"
  type        = string
  default     = "1209600s"
}

variable "ingest_dlq_max_delivery_attempts" {
  description = "Max delivery attempts before routing to DLQ"
  type        = number
  default     = 5
}

variable "raw_bucket_name" {
  description = "Raw documents bucket"
  type        = string
  default     = "alchimista-raw-994021588311"
}

variable "processed_bucket_name" {
  description = "Processed artifacts bucket"
  type        = string
  default     = "alchimista-processed-994021588311"
}

variable "reports_bucket_name" {
  description = "Reports bucket"
  type        = string
  default     = "alchimista-reports-994021588311"
}

variable "bucket_location" {
  description = "Primary storage bucket location"
  type        = string
  default     = "EUROPE-WEST4"
}

variable "cmek_key_ring_name" {
  description = "KMS key ring for storage encryption"
  type        = string
  default     = "alchimista-data-kr"
}

variable "cmek_crypto_key_name" {
  description = "KMS crypto key for storage encryption"
  type        = string
  default     = "alchimista-data-key"
}

variable "sql_instance_name" {
  description = "Cloud SQL instance name"
  type        = string
  default     = "alchimista-test-db"
}

variable "sql_database_version" {
  description = "Cloud SQL engine/version"
  type        = string
  default     = "POSTGRES_15"
}

variable "sql_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro"
}

variable "sql_disk_size_gb" {
  description = "Cloud SQL disk size in GB"
  type        = number
  default     = 10
}

variable "sql_backup_start_time_utc" {
  description = "Daily backup start time in UTC"
  type        = string
  default     = "02:00"
}

variable "sql_retained_backups" {
  description = "Number of retained backups"
  type        = number
  default     = 7
}

variable "sql_transaction_log_retention_days" {
  description = "Transaction log retention days"
  type        = number
  default     = 7
}

variable "run_service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "my-first-app"
}

variable "run_image" {
  description = "Container image for Cloud Run service"
  type        = string
  default     = "us-central1-docker.pkg.dev/secure-electron-474908-k9/cloud-run-source-deploy/my-first-app@sha256:7dc189eadbbc49ebf32d4196b9d02957fa5729fa44601a374f04f5aa7a24dd5f"
}

variable "run_service_account" {
  description = "Service account used by Cloud Run"
  type        = string
  default     = "994021588311-compute@developer.gserviceaccount.com"
}

variable "run_max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 20
}

variable "allow_unauthenticated" {
  description = "Allow public unauthenticated invoke"
  type        = bool
  default     = true
}
