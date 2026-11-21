# hiru-assemble (infra/assemble): ffmpeg for a take's last frame, probe and still. Internal only. Two
# callers, each with an ID token and the shared secret: the API (its account holds run.invoker
# project-wide) and hiru-video-render, which inspects each take it stores (plan/2026-11-21 D8; invoker
# on this service only, below). Terraform owns its configuration; deploy-assemble.yml owns the image.

resource "google_cloud_run_v2_service" "assemble" {
  name                = "${local.name}-assemble"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.environment == "prod"

  template {
    service_account                  = google_service_account.functions.email
    max_instance_request_concurrency = 4
    timeout                          = "300s"
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      # Placeholder until the first deploy-assemble.yml run replaces it.
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      ports { container_port = 8080 }
      resources {
        limits   = { cpu = "1", memory = "1Gi" }
        cpu_idle = true
      }

      env {
        name  = "SUPABASE__URL"
        value = var.supabase_url
      }
      env {
        name = "SUPABASE__SERVICE_ROLE_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["supabase-service-role-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ASSEMBLE__SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["assemble-secret"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.apis]
}

# hiru-video-render calls /inspect once per stored take (plan/2026-11-21 D8). The functions run as
# this account; the binding is on this one service, not project-wide.
resource "google_cloud_run_v2_service_iam_member" "functions_invoke_assemble" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.assemble.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.functions.email}"
}
