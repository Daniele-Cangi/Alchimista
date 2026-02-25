resource "google_kms_key_ring" "alchimista_data" {
  name     = var.cmek_key_ring_name
  project  = var.project_id
  location = var.region

  depends_on = [
    google_project_service.required["cloudkms.googleapis.com"]
  ]
}

resource "google_kms_crypto_key" "alchimista_data" {
  name            = var.cmek_crypto_key_name
  key_ring        = google_kms_key_ring.alchimista_data.id
  rotation_period = "2592000s"

  lifecycle {
    prevent_destroy = true
  }
}

data "google_storage_project_service_account" "gcs_service_account" {
  project = var.project_id
}

resource "google_kms_crypto_key_iam_member" "gcs_service_agent_key_access" {
  crypto_key_id = google_kms_crypto_key.alchimista_data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs_service_account.email_address}"
}

resource "google_storage_bucket" "raw" {
  project                     = var.project_id
  name                        = var.raw_bucket_name
  location                    = var.bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.alchimista_data.id
  }

  versioning {
    enabled = true
  }

  force_destroy = false

  depends_on = [
    google_project_service.required["storage.googleapis.com"],
    google_kms_crypto_key_iam_member.gcs_service_agent_key_access
  ]
}

resource "google_storage_bucket" "processed" {
  project                     = var.project_id
  name                        = var.processed_bucket_name
  location                    = var.bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.alchimista_data.id
  }

  versioning {
    enabled = true
  }

  force_destroy = false

  depends_on = [
    google_project_service.required["storage.googleapis.com"],
    google_kms_crypto_key_iam_member.gcs_service_agent_key_access
  ]
}

resource "google_storage_bucket" "reports" {
  project                     = var.project_id
  name                        = var.reports_bucket_name
  location                    = var.bucket_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.alchimista_data.id
  }

  versioning {
    enabled = true
  }

  force_destroy = false

  depends_on = [
    google_project_service.required["storage.googleapis.com"],
    google_kms_crypto_key_iam_member.gcs_service_agent_key_access
  ]
}
