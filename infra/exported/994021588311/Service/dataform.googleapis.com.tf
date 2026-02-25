resource "google_project_service" "dataform_googleapis_com" {
  project = "994021588311"
  service = "dataform.googleapis.com"
}
# terraform import google_project_service.dataform_googleapis_com 994021588311/dataform.googleapis.com
