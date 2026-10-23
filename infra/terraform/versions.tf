terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # State lives in a GCS bucket in the Hiru project. Create it once, by hand, before `init`:
  #   gcloud storage buckets create gs://<project_id>-tfstate --location=asia-south1 \
  #     --uniform-bucket-level-access --public-access-prevention
  #   gcloud storage buckets update gs://<project_id>-tfstate --versioning
  # then: terraform init -backend-config="bucket=<project_id>-tfstate"
  backend "gcs" {
    prefix = "hiru-ai-studio"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
