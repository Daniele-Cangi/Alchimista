resource "google_artifact_registry_repository" "cloud_run_source_deploy" {
  description = "Cloud Run Source Deployments"
  format      = "DOCKER"

  labels = {
    managed-by-cnrm = "true"
  }

  location      = "us-central1"
  mode          = "STANDARD_REPOSITORY"
  project       = "secure-electron-474908-k9"
  repository_id = "cloud-run-source-deploy"
}
# terraform import google_artifact_registry_repository.cloud_run_source_deploy projects/secure-electron-474908-k9/locations/us-central1/repositories/cloud-run-source-deploy
