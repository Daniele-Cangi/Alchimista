resource "google_compute_network" "alchimista_vpc" {
  auto_create_subnetworks                   = false
  name                                      = "alchimista-vpc"
  network_firewall_policy_enforcement_order = "AFTER_CLASSIC_FIREWALL"
  project                                   = "secure-electron-474908-k9"
  routing_mode                              = "REGIONAL"
}
# terraform import google_compute_network.alchimista_vpc projects/secure-electron-474908-k9/global/networks/alchimista-vpc
