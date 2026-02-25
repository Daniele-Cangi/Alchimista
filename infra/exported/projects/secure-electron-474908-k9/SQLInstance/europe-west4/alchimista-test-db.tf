resource "google_sql_database_instance" "alchimista_test_db" {
  database_version    = "POSTGRES_15"
  instance_type       = "CLOUD_SQL_INSTANCE"
  maintenance_version = "POSTGRES_15_15.R20260108.01_01"
  name                = "alchimista-test-db"
  project             = "secure-electron-474908-k9"
  region              = "europe-west4"

  settings {
    activation_policy = "ALWAYS"
    availability_type = "ZONAL"

    backup_configuration {
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }

      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "02:00"
      transaction_log_retention_days = 7
    }

    connector_enforcement       = "NOT_REQUIRED"
    deletion_protection_enabled = true
    disk_autoresize             = true
    disk_autoresize_limit       = 0
    disk_size                   = 10
    disk_type                   = "PD_SSD"
    edition                     = "ENTERPRISE"

    ip_configuration {
      ipv4_enabled    = false
      private_network = "projects/secure-electron-474908-k9/global/networks/alchimista-vpc"
    }

    location_preference {
      zone = "europe-west4-a"
    }

    pricing_plan = "PER_USE"
    tier         = "db-f1-micro"

    user_labels = {
      managed-by-cnrm = "true"
    }
  }
}
# terraform import google_sql_database_instance.alchimista_test_db projects/secure-electron-474908-k9/instances/alchimista-test-db
