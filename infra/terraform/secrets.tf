# Secret Manager secrets for Nexus-Hive runtime credentials.
#
# Each map key becomes an env var inside the Cloud Run container. The
# corresponding secret must be populated out-of-band (via `gcloud secrets
# versions add` or a CI job). Terraform manages the Secret resource but
# NOT its plaintext payload.

locals {
  # Map of env-var-name -> secret-id. Used both here and in cloud-run.tf.
  secret_env_map = {
    SNOWFLAKE_PASSWORD  = "nexus-hive-snowflake-password"
    SNOWFLAKE_USER      = "nexus-hive-snowflake-user"
    SNOWFLAKE_ACCOUNT   = "nexus-hive-snowflake-account"
    DATABRICKS_TOKEN    = "nexus-hive-databricks-token"
    DATABRICKS_HOST     = "nexus-hive-databricks-host"
    OPENAI_API_KEY      = "nexus-hive-openai-api-key"
    ANTHROPIC_API_KEY   = "nexus-hive-anthropic-api-key"
    NEXUS_OPERATOR_TOKEN = "nexus-hive-operator-token"
  }
}

resource "google_secret_manager_secret" "app_secrets" {
  for_each  = local.secret_env_map
  project   = var.project_id
  secret_id = each.value

  labels = {
    app         = "nexus-hive"
    environment = var.environment
    managed-by  = "terraform"
  }

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

# Grant the Nexus-Hive runtime SA read access to each secret.
resource "google_secret_manager_secret_iam_member" "runtime_accessor" {
  for_each  = google_secret_manager_secret.app_secrets
  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.nexus_hive.email}"
}

# Optional: stub placeholder versions so the Cloud Run revision starts even
# before secrets are populated. Controlled by var.create_stub_secret_versions
# (defaults false; only useful in sandboxes).
resource "google_secret_manager_secret_version" "stub" {
  for_each    = var.create_stub_secret_versions ? local.secret_env_map : {}
  secret      = google_secret_manager_secret.app_secrets[each.key].id
  secret_data = "REPLACE_ME"
  # Lifecycle: never recreate a stub if the operator has pushed a real value.
  lifecycle {
    ignore_changes = [secret_data]
  }
}
