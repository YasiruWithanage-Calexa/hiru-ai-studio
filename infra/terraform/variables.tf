variable "project_id" {
  description = "The separate GCP project for Hiru AI Studio."
  type        = string
}

variable "region" {
  description = "Region for the VM, Cloud Run, functions, Cloud Tasks, the media bucket and Artifact Registry. Next to the database (plan/2026-11-27 G3)."
  type        = string
  default     = "asia-southeast1"
}

variable "zone_suffix" {
  description = "The VM's zone inside the region (asia-southeast1-b)."
  type        = string
  default     = "b"
}

variable "environment" {
  description = "staging or prod. Names resources and picks infra/env/<environment>.env."
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be staging or prod."
  }
}

variable "supabase_url" {
  description = "https://<ref>.supabase.co of the Hiru Supabase project for this environment."
  type        = string
}

variable "media_bucket" {
  description = "The Cloud Storage bucket for media (globally unique). Must equal FILES__GCS_BUCKET in infra/env/<environment>.env."
  type        = string
}

variable "api_domain" {
  description = "The API's own host name (api.example.com), pointed at the VM. Empty: <address>.sslip.io."
  type        = string
  default     = ""
}

variable "api_machine_type" {
  type    = string
  default = "e2-small"
}

variable "api_disk_gb" {
  type    = number
  default = 30
}

variable "alert_email" {
  description = "Who is e-mailed when the API's health check fails. Empty: the check runs, nobody is mailed."
  type        = string
  default     = ""
}

variable "enable_github" {
  description = "Create the identity GitHub Actions deploys with (needs roles/iam.workloadIdentityPoolAdmin)."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy (only with enable_github)."
  type        = string
  default     = ""
}
