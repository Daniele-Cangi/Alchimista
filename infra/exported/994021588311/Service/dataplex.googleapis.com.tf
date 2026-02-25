resource "google_project_service" "dataplex_googleapis_com" {
  project = "994021588311"
  service = "dataplex.googleapis.com"
}
# terraform import google_project_service.dataplex_googleapis_com 994021588311/dataplex.googleapis.com
