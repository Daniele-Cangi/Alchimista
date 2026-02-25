resource "google_compute_network" "alchimista_vpc" {
  name                                      = var.network_name
  project                                   = var.project_id
  auto_create_subnetworks                   = false
  routing_mode                              = "REGIONAL"
  network_firewall_policy_enforcement_order = "AFTER_CLASSIC_FIREWALL"
}

resource "google_compute_global_address" "alchimista_private_ip_alloc" {
  name          = var.private_service_range_name
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  network       = google_compute_network.alchimista_vpc.id
  address       = var.private_service_range_address
  prefix_length = var.private_service_range_prefix_length
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.alchimista_vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.alchimista_private_ip_alloc.name]

  depends_on = [
    google_project_service.required["servicenetworking.googleapis.com"]
  ]
}

resource "google_vpc_access_connector" "alchimista_connector" {
  name          = var.connector_name
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.alchimista_vpc.name
  ip_cidr_range = var.connector_ip_cidr_range
  machine_type  = var.connector_machine_type
  min_instances = var.connector_min_instances
  max_instances = var.connector_max_instances

  depends_on = [
    google_project_service.required["vpcaccess.googleapis.com"]
  ]
}
