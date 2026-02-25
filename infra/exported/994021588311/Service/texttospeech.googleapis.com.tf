resource "google_project_service" "texttospeech_googleapis_com" {
  project = "994021588311"
  service = "texttospeech.googleapis.com"
}
# terraform import google_project_service.texttospeech_googleapis_com 994021588311/texttospeech.googleapis.com
