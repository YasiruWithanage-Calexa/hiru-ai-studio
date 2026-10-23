output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "tasks_queue" {
  value = google_cloud_tasks_queue.jobs.name
}

# Values for the GitHub environment's variables (deploy-*.yml).
output "github_variables" {
  value = {
    GCP_PROJECT_ID   = var.project_id
    GCP_REGION       = var.region
    GCP_WIF_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOYER_SA  = google_service_account.deployer.email
    GCP_FUNCTIONS_SA = google_service_account.functions.email
    API_SERVICE      = google_cloud_run_v2_service.api.name
    SECRET_PREFIX    = local.name
  }
}
