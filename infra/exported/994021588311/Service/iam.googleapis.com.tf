resource "google_project_service" "iam_googleapis_com" {
  project = "994021588311"
  service = "iam.googleapis.com"
}
# terraform import google_project_service.iam_googleapis_com 994021588311/iam.googleapis.com
