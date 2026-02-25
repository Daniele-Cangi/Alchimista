resource "google_project_service" "bigquerystorage_googleapis_com" {
  project = "994021588311"
  service = "bigquerystorage.googleapis.com"
}
# terraform import google_project_service.bigquerystorage_googleapis_com 994021588311/bigquerystorage.googleapis.com
