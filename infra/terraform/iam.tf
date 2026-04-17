# Service account + IAM for the Nexus-Hive Cloud Run runtime.
#
# The SA has minimum privileges: Secret Manager accessor on the secrets it
# owns, logs writer, monitoring metric writer, and (optionally) access to a
# GKE namespace via Workload Identity.

resource "google_service_account" "nexus_hive" {
  account_id   = "${var.service_name}-runtime"
  display_name = "Nexus-Hive Cloud Run runtime"
  description  = "Runtime identity for the ${var.service_name} service"
  project      = var.project_id
  depends_on   = [google_project_service.required]
}

# Project-level roles required for Cloud Run, Cloud Logging, and Monitoring.
resource "google_project_iam_member" "logs_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.nexus_hive.email}"
}

resource "google_project_iam_member" "monitoring_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.nexus_hive.email}"
}

resource "google_project_iam_member" "trace_writer" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.nexus_hive.email}"
}

resource "google_project_iam_member" "artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.nexus_hive.email}"
}

# Workload Identity binding. Lets a GKE ServiceAccount impersonate the
# Cloud Run runtime SA so the same identity works across Cloud Run and GKE
# deployments. Controlled by var.enable_workload_identity.
resource "google_service_account_iam_member" "workload_identity_binding" {
  count              = var.enable_workload_identity ? 1 : 0
  service_account_id = google_service_account.nexus_hive.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.workload_identity_namespace}/${var.workload_identity_ksa}]"
}

# Deployer service account used by CI/CD to push revisions.
resource "google_service_account" "deployer" {
  count        = var.create_deployer_sa ? 1 : 0
  account_id   = "${var.service_name}-deployer"
  display_name = "Nexus-Hive CI/CD deployer"
  description  = "Pushes new revisions from GitHub Actions / Cloud Build"
  project      = var.project_id
}

resource "google_project_iam_member" "deployer_run_admin" {
  count   = var.create_deployer_sa ? 1 : 0
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}

resource "google_project_iam_member" "deployer_sa_user" {
  count   = var.create_deployer_sa ? 1 : 0
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}

resource "google_project_iam_member" "deployer_artifact_writer" {
  count   = var.create_deployer_sa ? 1 : 0
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}
