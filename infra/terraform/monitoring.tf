# Uptime, log-based metrics, and alerting for Nexus-Hive on Cloud Run.

# Monitored group for all Nexus-Hive resources (useful for aggregated views).
resource "google_monitoring_group" "nexus_hive" {
  display_name = "Nexus-Hive ${var.environment}"
  project      = var.project_id
  filter       = "resource.labels.service_name=\"${var.service_name}\" resource.type=\"cloud_run_revision\""
  depends_on   = [google_project_service.required]
}

# Uptime check hitting /health.
resource "google_monitoring_uptime_check_config" "health" {
  display_name = "${var.service_name}-health"
  project      = var.project_id
  timeout      = "10s"
  period       = "60s"

  http_check {
    path           = "/health"
    port           = "443"
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = replace(replace(google_cloud_run_v2_service.this.uri, "https://", ""), "/", "")
    }
  }

  depends_on = [google_cloud_run_v2_service.this]
}

# Log-based metric: count 5xx responses from the service logs.
resource "google_logging_metric" "http_5xx" {
  name    = "${var.service_name}-http-5xx"
  project = var.project_id
  filter  = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.service_name}"
    httpRequest.status>=500
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "status"
      value_type  = "STRING"
      description = "HTTP status code"
    }
  }

  label_extractors = {
    "status" = "EXTRACT(httpRequest.status)"
  }
}

# Log-based metric: count policy denials (emitted by the Executor node).
resource "google_logging_metric" "policy_deny" {
  name    = "${var.service_name}-policy-deny"
  project = var.project_id
  filter  = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.service_name}"
    jsonPayload.event="policy_verdict"
    jsonPayload.verdict="deny"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Notification channel. Provide channel IDs via var.notification_channels.
resource "google_monitoring_alert_policy" "uptime" {
  display_name = "${var.service_name} - uptime check failing"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Uptime check /health is failing"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" resource.type=\"uptime_url\" metric.labels.check_id=\"${google_monitoring_uptime_check_config.health.uptime_check_id}\""
      duration        = "180s"
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      trigger {
        count = 1
      }
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_FRACTION_TRUE"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.project_id", "resource.label.host"]
      }
    }
  }

  notification_channels = var.notification_channels

  alert_strategy {
    auto_close = "86400s"
  }

  documentation {
    content   = "Nexus-Hive uptime check is failing. See docs/runbooks/incident-response.md."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "http_5xx_rate" {
  display_name = "${var.service_name} - 5xx rate > 5%"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "5xx logs frequency"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.http_5xx.name}\" resource.type=\"cloud_run_revision\""
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = var.notification_channels

  documentation {
    content   = "Nexus-Hive is returning >5 5xx per minute. Runbook: docs/runbooks/incident-response.md"
    mime_type = "text/markdown"
  }
}
