# Cloud Run v2 service for Nexus-Hive.
#
# The service runs a single container image pinned via var.image. Secrets
# are projected from Secret Manager via env_from_source so no plaintext
# credentials live in the revision spec.

resource "google_vpc_access_connector" "connector" {
  count          = var.create_vpc_connector ? 1 : 0
  name           = "${var.service_name}-connector"
  project        = var.project_id
  region         = var.region
  ip_cidr_range  = var.vpc_connector_cidr
  network        = var.vpc_network_name
  min_throughput = 200
  max_throughput = 1000
  depends_on     = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "this" {
  name     = var.service_name
  project  = var.project_id
  location = var.region
  ingress  = var.ingress

  deletion_protection = var.deletion_protection

  labels = {
    app         = "nexus-hive"
    environment = var.environment
    managed-by  = "terraform"
  }

  template {
    service_account = google_service_account.nexus_hive.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    timeout                          = "${var.request_timeout_seconds}s"
    max_instance_request_concurrency = var.concurrency

    dynamic "vpc_access" {
      for_each = var.create_vpc_connector ? [1] : []
      content {
        connector = google_vpc_access_connector.connector[0].id
        egress    = var.vpc_egress
      }
    }

    containers {
      image = var.image

      ports {
        container_port = 8000
        name           = "http1"
      }

      resources {
        limits = {
          cpu    = var.cpu_limit
          memory = var.memory_limit
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 30
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 20
        period_seconds        = 15
        timeout_seconds       = 5
        failure_threshold     = 3
      }

      # Non-secret environment variables.
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secret-backed environment variables projected from Secret Manager.
      dynamic "env" {
        for_each = local.secret_env_map
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app_secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.required,
    google_service_account.nexus_hive,
    google_secret_manager_secret.app_secrets,
  ]
}

# Public invoker binding (toggle with var.allow_unauthenticated).
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = google_cloud_run_v2_service.this.project
  location = google_cloud_run_v2_service.this.location
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Authenticated invokers (IAP, internal groups).
resource "google_cloud_run_v2_service_iam_member" "authenticated_invokers" {
  for_each = toset(var.authenticated_invokers)
  project  = google_cloud_run_v2_service.this.project
  location = google_cloud_run_v2_service.this.location
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = each.value
}
