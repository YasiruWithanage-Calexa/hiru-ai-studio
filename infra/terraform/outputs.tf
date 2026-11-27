# What the deploy scripts need (`terraform output -json deploy`). No secret is ever an output.
output "deploy" {
  value = {
    project_id       = var.project_id
    project_number   = data.google_project.this.number
    region           = var.region
    environment      = var.environment
    secret_prefix    = local.name
    supabase_url     = var.supabase_url
    images           = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
    api_vm           = google_compute_instance.api.name
    api_zone         = google_compute_instance.api.zone
    api_host         = local.api_host
    api_url          = local.api_url
    api_ip           = google_compute_address.api.address
    tasks_queue      = google_cloud_tasks_queue.jobs.name
    tasks_invoker_sa = google_service_account.tasks_invoker.email
    functions_sa     = google_service_account.functions.email
    build_sa         = google_service_account.build.name
    # gen2 functions are served at https://<name>-<project-number>.<region>.run.app
    functions_base_url = "https://{function_name}-${data.google_project.this.number}.${var.region}.run.app"
    assemble_service   = google_cloud_run_v2_service.assemble.name
    assemble_url       = google_cloud_run_v2_service.assemble.uri
    media_bucket       = google_storage_bucket.media.name
  }
}
