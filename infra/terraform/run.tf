# The API service. Terraform owns its configuration (identity, scaling, env, secrets);
# GitHub Actions owns which image runs (deploy-api.yml), hence ignore_changes on the image.

resource "google_cloud_run_v2_service" "api" {
  name                = "${local.name}-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.environment == "prod"

  template {
    service_account                  = google_service_account.api.email
    max_instance_request_concurrency = 80
    timeout                          = "300s"
    scaling {
      min_instance_count = var.environment == "prod" ? var.api_min_instances : 0
      max_instance_count = 10
    }

    containers {
      # Placeholder until the first deploy-api.yml run replaces it.
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      startup_probe {
        http_get { path = "/healthz" }
        period_seconds    = 3
        failure_threshold = 10
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "LOCAL_FUNCTIONS"
        value = "false"
      }
      env {
        name  = "SUPABASE__URL"
        value = var.supabase_url
      }
      env {
        name  = "SUPABASE__INVITE_REDIRECT_URL"
        value = var.invite_redirect_url
      }
      env {
        name  = "API__CORS_ORIGINS"
        value = var.cors_origins
      }
      env {
        name  = "API__PUBLIC_URL"
        value = var.api_public_url
      }
      env {
        name  = "GCP__PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP__REGION"
        value = var.region
      }
      env {
        name  = "GCP__TASKS_QUEUE"
        value = google_cloud_tasks_queue.jobs.name
      }
      env {
        name  = "GCP__TASKS_INVOKER_SA"
        value = google_service_account.tasks_invoker.email
      }
      env {
        # gen2 functions are served at https://<name>-<project-number>.<region>.run.app
        name  = "GCP__FUNCTIONS_BASE_URL"
        value = "https://{function_name}-${data.google_project.this.number}.${var.region}.run.app"
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
        name  = "ASSEMBLE__URL"
        value = google_cloud_run_v2_service.assemble.uri
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
      env {
        name = "API__INTERNAL_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["api-internal-secret"].secret_id
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

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.api_reads,
  ]
}

data "google_project" "this" {}

# Public at the network layer; every route except /healthz and /files/{ticket} requires a
# Supabase JWT, checked by the app.
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
