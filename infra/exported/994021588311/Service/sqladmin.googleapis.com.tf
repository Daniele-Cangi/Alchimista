resource "google_project_service" "sqladmin_googleapis_com" {
  project = "994021588311"
  service = "sqladmin.googleapis.com"
}
# terraform import google_project_service.sqladmin_googleapis_com 994021588311/sqladmin.googleapis.com
