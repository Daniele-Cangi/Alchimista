resource "google_project_service" "secretmanager_googleapis_com" {
  project = "994021588311"
  service = "secretmanager.googleapis.com"
}
# terraform import google_project_service.secretmanager_googleapis_com 994021588311/secretmanager.googleapis.com
