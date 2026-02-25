resource "google_project_service" "containerregistry_googleapis_com" {
  project = "994021588311"
  service = "containerregistry.googleapis.com"
}
# terraform import google_project_service.containerregistry_googleapis_com 994021588311/containerregistry.googleapis.com
