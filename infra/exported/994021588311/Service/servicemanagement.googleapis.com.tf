resource "google_project_service" "servicemanagement_googleapis_com" {
  project = "994021588311"
  service = "servicemanagement.googleapis.com"
}
# terraform import google_project_service.servicemanagement_googleapis_com 994021588311/servicemanagement.googleapis.com
