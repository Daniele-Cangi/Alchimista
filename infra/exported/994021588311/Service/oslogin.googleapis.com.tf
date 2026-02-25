resource "google_project_service" "oslogin_googleapis_com" {
  project = "994021588311"
  service = "oslogin.googleapis.com"
}
# terraform import google_project_service.oslogin_googleapis_com 994021588311/oslogin.googleapis.com
