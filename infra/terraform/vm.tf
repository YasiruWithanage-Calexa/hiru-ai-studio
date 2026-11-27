# The API on one Compute Engine VM (plan/2026-11-27 §2): Docker Compose runs the API container and Caddy, which holds
# the HTTPS certificate. Terraform owns the machine, its network and its identity; scripts/deploy_api.ps1 owns what
# runs on it (the image, the env file, the Compose and Caddy files). The VM keeps no data of its own.

resource "google_compute_network" "main" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "main" {
  name          = "${local.name}-${var.region}"
  region        = var.region
  network       = google_compute_network.main.id
  ip_cidr_range = "10.10.0.0/24"
  # The API calls internal-only functions through Google's private route (plan F4; verified after the first deploy).
  private_ip_google_access = true
}

resource "google_compute_address" "api" {
  name       = "${local.name}-api"
  region     = var.region
  depends_on = [google_project_service.apis]
}

locals {
  # Without a domain of your own, a free name that points at the address (plan D1).
  api_host = var.api_domain != "" ? var.api_domain : "${replace(google_compute_address.api.address, ".", "-")}.sslip.io"
  api_url  = "https://${local.api_host}"
}

resource "google_compute_firewall" "web" {
  name          = "${local.name}-web"
  network       = google_compute_network.main.id
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["${local.name}-api"]
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  allow {
    protocol = "udp"
    ports    = ["443"]
  }
}

# SSH only from Google's identity-aware tunnel (`gcloud compute ssh --tunnel-through-iap`), never from the internet.
resource "google_compute_firewall" "ssh_iap" {
  name          = "${local.name}-ssh-iap"
  network       = google_compute_network.main.id
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["${local.name}-api"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance" "api" {
  name                      = "${local.name}-api"
  zone                      = "${var.region}-${var.zone_suffix}"
  machine_type              = var.api_machine_type
  tags                      = ["${local.name}-api"]
  allow_stopping_for_update = true # a bigger machine is a restart, not a rebuild
  deletion_protection       = var.environment == "prod"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = var.api_disk_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.id
    access_config {
      nat_ip = google_compute_address.api.address
    }
  }

  # The API's identity: what it may do is the account's roles (main.tf, storage.tf), not a key on disk.
  service_account {
    email  = google_service_account.api.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  # No OS Login: for an account from another organization it needs a grant on the organization itself. Instead
  # `gcloud compute ssh` puts a key on this machine only, and port 22 is reachable only through the tunnel.
  metadata = {
    enable-oslogin         = "FALSE"
    block-project-ssh-keys = "TRUE"
  }

  metadata_startup_script = file("${path.module}/../vm/startup.sh")

  lifecycle {
    ignore_changes = [
      boot_disk[0].initialize_params[0].image, # a newer Debian image never rebuilds the machine
      metadata["ssh-keys"],                    # added by `gcloud compute ssh`
    ]
  }

  depends_on = [google_project_iam_member.api_vm, google_secret_manager_secret_iam_member.api_reads]
}

# ── is it up? ────────────────────────────────────────────────────────────────────────────

resource "google_monitoring_uptime_check_config" "api" {
  display_name = "${local.name} API /healthz"
  timeout      = "10s"
  period       = "300s"
  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = local.api_host
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  display_name = "${local.name} alerts"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "api_down" {
  count        = var.alert_email == "" ? 0 : 1
  display_name = "${local.name} API is down"
  combiner     = "OR"
  conditions {
    display_name = "The uptime check fails"
    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.api.uptime_check_id}\"",
        "resource.type=\"uptime_url\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "300s"
      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }
      trigger {
        count = 1
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email[0].id]
}
