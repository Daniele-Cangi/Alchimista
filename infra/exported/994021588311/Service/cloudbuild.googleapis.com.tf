resource "google_project_service" "cloudbuild_googleapis_com" {
  project = "994021588311"
  service = "cloudbuild.googleapis.com"
}
# terraform import google_project_service.cloudbuild_googleapis_com 994021588311/cloudbuild.googleapis.com
