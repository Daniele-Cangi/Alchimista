resource "google_artifact_registry_repository" "cloud_run_source_deploy" {
  project       = var.project_id
  location      = "us-central1"
  repository_id = "cloud-run-source-deploy"
  format        = "DOCKER"
  mode          = "STANDARD_REPOSITORY"
  description   = "Cloud Run Source Deployments"
}
