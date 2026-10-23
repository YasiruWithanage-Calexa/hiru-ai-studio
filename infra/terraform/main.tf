locals {
  name = "hiru-${var.environment}"
  apis = [
    "run.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtasks.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudtrace.googleapis.com",
    "logging.googleapis.com",
  ]
  # Secret values are added by hand (`gcloud secrets versions add`), never through Terraform,
  # so they never enter Terraform state.
  secrets = ["supabase-service-role-key", "api-internal-secret", "openai-api-key", "supabase-db-url"]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "hiru"
  format        = "DOCKER"
  description   = "Hiru AI Studio container images"
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 20 }
  }
  depends_on = [google_project_service.apis]
}

# ── service accounts (one per role, least privilege) ─────────────────────────────────────

resource "google_service_account" "api" {
  account_id   = "${local.name}-api"
  display_name = "Hiru API (Cloud Run)"
}

resource "google_service_account" "functions" {
  account_id   = "${local.name}-functions"
  display_name = "Hiru functions runtime"
}

# Cloud Tasks signs OIDC tokens as this account; it may only invoke Cloud Run.
resource "google_service_account" "tasks_invoker" {
  account_id   = "${local.name}-tasks"
  display_name = "Hiru Cloud Tasks invoker"
}

resource "google_service_account" "deployer" {
  account_id   = "${local.name}-deployer"
  display_name = "Hiru GitHub Actions deployer"
}

# ── secrets ──────────────────────────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(local.secrets)
  secret_id = "${local.name}-${each.value}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "api_reads" {
  for_each  = toset(["supabase-service-role-key", "api-internal-secret"])
  secret_id = google_secret_manager_secret.secrets[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "functions_read" {
  for_each  = toset(local.secrets)
  secret_id = google_secret_manager_secret.secrets[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.functions.email}"
}

# ── Cloud Tasks ──────────────────────────────────────────────────────────────────────────

resource "google_cloud_tasks_queue" "jobs" {
  name     = "${local.name}-jobs"
  location = var.region
  rate_limits {
    max_dispatches_per_second = 20
    max_concurrent_dispatches = 50
  }
  retry_config {
    max_attempts       = 5
    min_backoff        = "10s"
    max_backoff        = "300s"
    max_doublings      = 4
    max_retry_duration = "3600s"
  }
  depends_on = [google_project_service.apis]
}

# The API enqueues tasks and must be allowed to mint OIDC tokens as the invoker account.
resource "google_cloud_tasks_queue_iam_member" "api_enqueues" {
  name     = google_cloud_tasks_queue.jobs.name
  location = var.region
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.api.email}"
}

resource "google_service_account_iam_member" "api_acts_as_tasks_invoker" {
  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.api.email}"
}

# Functions are gen2 (Cloud Run services). The invoker binding is project-wide so a newly
# deployed function is callable by Cloud Tasks without another Terraform run; the functions
# themselves are internal-ingress only and require authentication.
resource "google_project_iam_member" "tasks_invoke_run" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.tasks_invoker.email}"
}

resource "google_project_iam_member" "observability" {
  for_each = toset([
    "serviceAccount:${google_service_account.api.email}",
    "serviceAccount:${google_service_account.functions.email}",
  ])
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = each.value
}
