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
  description = "Runtime environment variables"
  default     = {}
}
