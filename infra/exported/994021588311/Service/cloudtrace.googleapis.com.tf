resource "google_project_service" "cloudtrace_googleapis_com" {
  project = "994021588311"
  service = "cloudtrace.googleapis.com"
}
# terraform import google_project_service.cloudtrace_googleapis_com 994021588311/cloudtrace.googleapis.com
