resource "google_project_service" "storage_googleapis_com" {
  project = "994021588311"
  service = "storage.googleapis.com"
}
# terraform import google_project_service.storage_googleapis_com 994021588311/storage.googleapis.com
