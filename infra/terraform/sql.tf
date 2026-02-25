resource "google_sql_database_instance" "alchimista_test_db" {
  name             = var.sql_instance_name
  project          = var.project_id
  region           = var.region
  database_version = var.sql_database_version

  settings {
    tier                        = var.sql_tier
    availability_type           = "ZONAL"
    activation_policy           = "ALWAYS"
    disk_autoresize             = true
    disk_autoresize_limit       = 0
    disk_size                   = var.sql_disk_size_gb
    disk_type                   = "PD_SSD"
    edition                     = "ENTERPRISE"
    pricing_plan                = "PER_USE"
    connector_enforcement       = "NOT_REQUIRED"
    deletion_protection_enabled = true

    backup_configuration {
      enabled                        = true
      start_time                     = var.sql_backup_start_time_utc
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.sql_transaction_log_retention_days

      backup_retention_settings {
        retained_backups = var.sql_retained_backups
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.alchimista_vpc.id
    }

    location_preference {
      zone = var.zone
    }
  }

  depends_on = [
    google_project_service.required["sqladmin.googleapis.com"],
    google_service_networking_connection.private_vpc_connection
  ]

  lifecycle {
    ignore_changes = [
      maintenance_version,
      settings[0].user_labels
    ]
  }
}
