resource "google_project_service" "run_googleapis_com" {
  project = "994021588311"
  service = "run.googleapis.com"
}
# terraform import google_project_service.run_googleapis_com 994021588311/run.googleapis.com
