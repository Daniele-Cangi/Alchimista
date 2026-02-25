resource "google_project_service" "monitoring_googleapis_com" {
  project = "994021588311"
  service = "monitoring.googleapis.com"
}
# terraform import google_project_service.monitoring_googleapis_com 994021588311/monitoring.googleapis.com
