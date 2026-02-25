resource "google_project_service" "vpcaccess_googleapis_com" {
  project = "994021588311"
  service = "vpcaccess.googleapis.com"
}
# terraform import google_project_service.vpcaccess_googleapis_com 994021588311/vpcaccess.googleapis.com
