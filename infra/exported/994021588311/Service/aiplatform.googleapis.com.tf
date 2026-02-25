resource "google_project_service" "aiplatform_googleapis_com" {
  project = "994021588311"
  service = "aiplatform.googleapis.com"
}
# terraform import google_project_service.aiplatform_googleapis_com 994021588311/aiplatform.googleapis.com
