# Root composition for Nexus-Hive on GCP Cloud Run.
# Actual resources are split across files for enterprise maintainability:
#   cloud-run.tf  - Cloud Run service + VPC connector + revision settings
#   secrets.tf    - Secret Manager entries for warehouse credentials
#   iam.tf        - Service account + IAM bindings + Workload Identity
#   monitoring.tf - Uptime checks, log-based metrics, alerting policies

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enabling required APIs is kept explicit so `terraform apply` works on a
# fresh project. Cloud Run, Secret Manager, IAM, Monitoring, Logging, and
# VPC Access APIs are all enabled up-front.
resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "iam.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "vpcaccess.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])
  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}
