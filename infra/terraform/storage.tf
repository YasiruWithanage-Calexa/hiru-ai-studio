# Media (plan/2026-11-27 §4): one private bucket; `documents/`, `frames/`, `references/` and `takes/` are folders in
# it. Browsers never get its addresses: they read through the API's /files links. The services reach it as their own
# service accounts, with rights on this bucket only.

resource "google_storage_bucket" "media" {
  name                        = var.media_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false # a bucket with files is never destroyed by Terraform

  soft_delete_policy {
    retention_duration_seconds = 604800 # a removed file can be brought back for 7 days
  }

  depends_on = [google_project_service.apis]
}

# objectUser: read, write, replace and delete objects; nothing about the bucket itself.
resource "google_storage_bucket_iam_member" "media" {
  for_each = {
    api       = google_service_account.api.email
    functions = google_service_account.functions.email # `assemble` runs as this account too
  }
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${each.value}"
}
