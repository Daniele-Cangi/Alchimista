resource "google_project_service" "pubsub_googleapis_com" {
  project = "994021588311"
  service = "pubsub.googleapis.com"
}
# terraform import google_project_service.pubsub_googleapis_com 994021588311/pubsub.googleapis.com
