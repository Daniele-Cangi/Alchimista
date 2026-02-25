resource "google_project_service" "serviceusage_googleapis_com" {
  project = "994021588311"
  service = "serviceusage.googleapis.com"
}
# terraform import google_project_service.serviceusage_googleapis_com 994021588311/serviceusage.googleapis.com
