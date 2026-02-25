resource "google_cloud_run_service" "my_first_app" {
  name     = var.run_service_name
  project  = var.project_id
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress"  = "all"
      "run.googleapis.com/maxScale" = tostring(var.run_max_instances)
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale"        = tostring(var.run_max_instances)
        "run.googleapis.com/startup-cpu-boost"    = "true"
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.alchimista_connector.name
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }

    spec {
      service_account_name = var.run_service_account

      containers {
        image = var.run_image
      }
    }
  }

  autogenerate_revision_name = true

  lifecycle {
    ignore_changes = [
      template[0].metadata[0].annotations["run.googleapis.com/client-name"],
      template[0].metadata[0].annotations["run.googleapis.com/client-version"],
    ]
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  depends_on = [
    google_project_service.required["run.googleapis.com"],
    google_vpc_access_connector.alchimista_connector
  ]
}

resource "google_cloud_run_service_iam_member" "my_first_app_public_invoker" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  service  = google_cloud_run_service.my_first_app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
