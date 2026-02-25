resource "google_project_service" "recommender_googleapis_com" {
  project = "994021588311"
  service = "recommender.googleapis.com"
}
# terraform import google_project_service.recommender_googleapis_com 994021588311/recommender.googleapis.com
