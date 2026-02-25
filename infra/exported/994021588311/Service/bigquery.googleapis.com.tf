resource "google_project_service" "bigquery_googleapis_com" {
  project = "994021588311"
  service = "bigquery.googleapis.com"
}
# terraform import google_project_service.bigquery_googleapis_com 994021588311/bigquery.googleapis.com
