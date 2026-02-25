resource "google_pubsub_topic" "doc_ingest_topic" {
  project = var.project_id
  name    = var.ingest_topic_name

  depends_on = [
    google_project_service.required["pubsub.googleapis.com"]
  ]
}

resource "google_pubsub_topic" "doc_ingest_topic_dlq" {
  project = var.project_id
  name    = var.ingest_dlq_topic_name

  depends_on = [
    google_project_service.required["pubsub.googleapis.com"]
  ]
}

resource "google_pubsub_topic_iam_member" "doc_ingest_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.doc_ingest_topic_dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription" "doc_ingest_sub" {
  project                    = var.project_id
  name                       = var.ingest_subscription_name
  topic                      = google_pubsub_topic.doc_ingest_topic.name
  ack_deadline_seconds       = var.ingest_subscription_ack_deadline_seconds
  message_retention_duration = var.ingest_subscription_retention_duration

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.doc_ingest_topic_dlq.id
    max_delivery_attempts = var.ingest_dlq_max_delivery_attempts
  }

  depends_on = [
    google_project_service.required["pubsub.googleapis.com"],
    google_pubsub_topic_iam_member.doc_ingest_dlq_publisher
  ]
}

resource "google_pubsub_subscription" "doc_ingest_dlq_sub" {
  project                    = var.project_id
  name                       = "${var.ingest_dlq_topic_name}-sub"
  topic                      = google_pubsub_topic.doc_ingest_topic_dlq.name
  ack_deadline_seconds       = 30
  message_retention_duration = "1209600s"

  depends_on = [
    google_project_service.required["pubsub.googleapis.com"]
  ]
}
