resource "google_project_service" "notebooks_googleapis_com" {
  project = "994021588311"
  service = "notebooks.googleapis.com"
}
# terraform import google_project_service.notebooks_googleapis_com 994021588311/notebooks.googleapis.com
