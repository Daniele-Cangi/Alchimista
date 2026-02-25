resource "google_project_service" "cloudkms_googleapis_com" {
  project = "994021588311"
  service = "cloudkms.googleapis.com"
}
# terraform import google_project_service.cloudkms_googleapis_com 994021588311/cloudkms.googleapis.com
