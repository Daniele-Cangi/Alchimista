resource "google_project_service" "logging_googleapis_com" {
  project = "994021588311"
  service = "logging.googleapis.com"
}
# terraform import google_project_service.logging_googleapis_com 994021588311/logging.googleapis.com
