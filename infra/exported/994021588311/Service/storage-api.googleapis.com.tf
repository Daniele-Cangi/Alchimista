resource "google_project_service" "storage_api_googleapis_com" {
  project = "994021588311"
  service = "storage-api.googleapis.com"
}
# terraform import google_project_service.storage_api_googleapis_com 994021588311/storage-api.googleapis.com
