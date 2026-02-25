resource "google_project_service" "compute_googleapis_com" {
  project = "994021588311"
  service = "compute.googleapis.com"
}
# terraform import google_project_service.compute_googleapis_com 994021588311/compute.googleapis.com
