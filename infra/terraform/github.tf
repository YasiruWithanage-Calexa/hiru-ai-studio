# GitHub Actions deploys through Workload Identity Federation: no service-account keys exist.
#
# Off until `enable_github = true` (plan/2026-11-27 D3): creating the identity pool needs
# `roles/iam.workloadIdentityPoolAdmin`, which the basic Admin role does not include. Until then the deploys are the
# PowerShell scripts, run by a person. The workflows still have to be updated for the VM before they are used.

resource "google_service_account" "deployer" {
  count        = var.enable_github ? 1 : 0
  account_id   = "${local.name}-deployer"
  display_name = "Hiru GitHub Actions deployer"
}

resource "google_iam_workload_identity_pool" "github" {
  count                     = var.enable_github ? 1 : 0
  workload_identity_pool_id = "${local.name}-github"
  display_name              = "GitHub Actions (${var.environment})"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.enable_github ? 1 : 0
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only this repository can authenticate at all.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonates_deployer" {
  count              = var.enable_github ? 1 : 0
  service_account_id = google_service_account.deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repository}"
}

resource "google_project_iam_member" "deployer" {
  for_each = var.enable_github ? toset([
    "roles/run.developer",
    "roles/cloudfunctions.developer",
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/storage.objectAdmin", # function source uploads
  ]) : toset([])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}

# The deployer must "act as" the runtime identities it deploys services with.
resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each = var.enable_github ? {
    api       = google_service_account.api.name
    functions = google_service_account.functions.name
    build     = google_service_account.build.name
  } : {}
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer[0].email}"
}
