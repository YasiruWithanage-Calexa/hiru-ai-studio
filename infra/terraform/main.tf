locals {
  name = "hiru-${var.environment}"
  apis = [
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iap.googleapis.com",
    "storage.googleapis.com",
    "monitoring.googleapis.com",
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
  secrets = ["supabase-service-role-key", "api-internal-secret", "openai-api-key", "supabase-db-url",
  "assemble-secret", "google-api-key"]
  # What the API itself reads. The Google key only tells it whether video can be made (plan/2026-11-06c).
  api_secrets = ["supabase-service-role-key", "api-internal-secret", "assemble-secret", "openai-api-key",
  "google-api-key"]
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
  display_name = "Hiru API (VM)"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "functions" {
  account_id   = "${local.name}-functions"
  display_name = "Hiru functions runtime"
  depends_on   = [google_project_service.apis]
}

# Functions are built by Cloud Build as this account, not the project's default one (which a new project may leave
# without rights).
resource "google_service_account" "build" {
  account_id   = "${local.name}-build"
  display_name = "Hiru function builds"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "build" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${google_service_account.build.email}"
}

# Cloud Tasks signs OIDC tokens as this account; it may only invoke Cloud Run.
resource "google_service_account" "tasks_invoker" {
  account_id   = "${local.name}-tasks"
  display_name = "Hiru Cloud Tasks invoker"
  depends_on   = [google_project_service.apis]
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
  for_each  = toset(local.api_secrets)
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
  # At most ten jobs at once, and each function may run ten instances (scripts/deploy_functions.ps1): a burst waits in
  # the queue instead of being refused until its retries run out, and AI spending has a ceiling (plan F11).
  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 10
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

# The director chat is synchronous and streamed: the API calls that function itself (not through
# Cloud Tasks) with an ID token minted for its own identity.
resource "google_project_iam_member" "api_invokes_functions" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.api.email}"
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

data "google_project" "this" {}

# What the API's VM does besides: write its logs and metrics, and pull its own image.
resource "google_project_iam_member" "api_vm" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.api.email}"
}

resource "google_artifact_registry_repository_iam_member" "api_pulls" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.api.email}"
}
