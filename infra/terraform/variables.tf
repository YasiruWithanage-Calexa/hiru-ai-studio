variable "project_id" {
  description = "The separate GCP project for Hiru AI Studio."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, functions, Cloud Tasks and Artifact Registry (PLAN.md Q5)."
  type        = string
  default     = "asia-south1"
}

variable "environment" {
  description = "staging or prod. Names resources and sets the API's ENVIRONMENT."
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be staging or prod."
  }
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy (Workload Identity Federation)."
  type        = string
}

variable "supabase_url" {
  description = "https://<ref>.supabase.co of the Hiru Supabase project for this environment."
  type        = string
}

variable "cors_origins" {
  description = "Comma-separated frontend origins allowed by CORS."
  type        = string
}

variable "api_public_url" {
  description = "Public base URL of the API (used in /files/{ticket} links). Empty until the first deploy prints it."
  type        = string
  default     = ""
}

variable "invite_redirect_url" {
  description = "Frontend page that accepts a Supabase invite."
  type        = string
}

variable "api_min_instances" {
  description = "Keep one warm instance in prod to avoid cold starts for the crew."
  type        = number
  default     = 1
}
