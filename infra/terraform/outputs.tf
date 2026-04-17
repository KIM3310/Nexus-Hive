output "service_uri" {
  value       = google_cloud_run_v2_service.this.uri
  description = "Cloud Run URL"
}

output "service_name" {
  value       = google_cloud_run_v2_service.this.name
  description = "Cloud Run service name"
}

output "service_account_email" {
  value       = google_service_account.nexus_hive.email
  description = "Email of the runtime service account"
}

output "deployer_service_account_email" {
  value       = var.create_deployer_sa ? google_service_account.deployer[0].email : null
  description = "Email of the CI/CD deployer service account (null when not created)"
}

output "secret_ids" {
  value       = { for k, v in google_secret_manager_secret.app_secrets : k => v.secret_id }
  description = "Map from env-var name to Secret Manager secret ID"
}

output "uptime_check_id" {
  value       = google_monitoring_uptime_check_config.health.uptime_check_id
  description = "ID of the Cloud Monitoring uptime check"
}

output "vpc_connector_id" {
  value       = var.create_vpc_connector ? google_vpc_access_connector.connector[0].id : null
  description = "Serverless VPC Access connector ID (null when not created)"
}
