resource "google_project_service" "datastore_googleapis_com" {
  project = "994021588311"
  service = "datastore.googleapis.com"
}
# terraform import google_project_service.datastore_googleapis_com 994021588311/datastore.googleapis.com
