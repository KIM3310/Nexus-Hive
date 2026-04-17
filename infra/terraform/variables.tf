variable "project_id" {
  type        = string
  description = "Google Cloud project id"
}

variable "region" {
  type        = string
  description = "Cloud Run region"
  default     = "asia-northeast3"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name"
  default     = "nexus-hive"
}

variable "image" {
  type        = string
  description = "Container image URL"
}

variable "env" {
  type        = map(string)
  description = "Runtime environment variables (non-secret). Secret-backed vars live in secrets.tf."
  default     = {}
}

variable "environment" {
  type        = string
  description = "Deployment environment label (dev, staging, prod)"
  default     = "prod"
}

variable "min_instances" {
  type        = number
  description = "Cloud Run minimum instance count (keep > 0 to avoid cold starts)"
  default     = 1
}

variable "max_instances" {
  type        = number
  description = "Cloud Run maximum instance count"
  default     = 10
}

variable "concurrency" {
  type        = number
  description = "Max concurrent requests per instance"
  default     = 40
}

variable "request_timeout_seconds" {
  type        = number
  description = "Cloud Run request timeout in seconds"
  default     = 120
}

variable "cpu_limit" {
  type        = string
  description = "CPU limit (e.g. \"1\", \"2\")"
  default     = "1"
}

variable "memory_limit" {
  type        = string
  description = "Memory limit (e.g. \"512Mi\", \"1Gi\")"
  default     = "1Gi"
}

variable "ingress" {
  type        = string
  description = "Cloud Run ingress setting: INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_ONLY, INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  default     = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Bind allUsers to roles/run.invoker. Leave false for IAP-gated deployments."
  default     = false
}

variable "authenticated_invokers" {
  type        = list(string)
  description = "Additional IAM members granted roles/run.invoker (e.g. user:, group:, serviceAccount:)"
  default     = []
}

variable "deletion_protection" {
  type        = bool
  description = "Prevents accidental terraform destroy. Set false only to tear down."
  default     = true
}

variable "create_vpc_connector" {
  type        = bool
  description = "Whether to create a Serverless VPC Access connector for private egress"
  default     = false
}

variable "vpc_network_name" {
  type        = string
  description = "VPC network name used by the VPC connector"
  default     = "default"
}

variable "vpc_connector_cidr" {
  type        = string
  description = "CIDR range for the Serverless VPC Access connector"
  default     = "10.8.0.0/28"
}

variable "vpc_egress" {
  type        = string
  description = "Cloud Run egress: PRIVATE_RANGES_ONLY or ALL_TRAFFIC"
  default     = "PRIVATE_RANGES_ONLY"
}

variable "enable_workload_identity" {
  type        = bool
  description = "Grant workloadIdentityUser to a GKE KSA so the same identity spans Cloud Run + GKE"
  default     = false
}

variable "workload_identity_namespace" {
  type        = string
  description = "Kubernetes namespace containing the KSA bound to this runtime"
  default     = "analytics"
}

variable "workload_identity_ksa" {
  type        = string
  description = "KSA name bound to this runtime via Workload Identity"
  default     = "nexus-hive"
}

variable "create_deployer_sa" {
  type        = bool
  description = "Whether to provision a CI/CD deployer service account"
  default     = false
}

variable "create_stub_secret_versions" {
  type        = bool
  description = "Populate each Secret Manager secret with a REPLACE_ME stub to allow first deploy. Only use in sandboxes."
  default     = false
}

variable "notification_channels" {
  type        = list(string)
  description = "google_monitoring_notification_channel.id values to notify on alert"
  default     = []
}
