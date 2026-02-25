resource "google_project_service" "cloudapis_googleapis_com" {
  project = "994021588311"
  service = "cloudapis.googleapis.com"
}
# terraform import google_project_service.cloudapis_googleapis_com 994021588311/cloudapis.googleapis.com
