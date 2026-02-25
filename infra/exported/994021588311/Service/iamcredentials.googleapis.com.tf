resource "google_project_service" "iamcredentials_googleapis_com" {
  project = "994021588311"
  service = "iamcredentials.googleapis.com"
}
# terraform import google_project_service.iamcredentials_googleapis_com 994021588311/iamcredentials.googleapis.com
