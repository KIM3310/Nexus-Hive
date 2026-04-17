# Nexus-Hive Terraform

Enterprise Cloud Run deployment for `Nexus-Hive` with Secret Manager,
Workload Identity, uptime checks, and log-based alerting.

## Layout

```
infra/terraform/
  main.tf           # provider + enabled APIs
  cloud-run.tf      # Cloud Run service, VPC connector, IAM invoker
  secrets.tf        # Secret Manager secrets + accessors
  iam.tf            # Runtime SA, deployer SA, Workload Identity binding
  monitoring.tf     # Uptime checks, log-based metrics, alert policies
  variables.tf      # Inputs
  outputs.tf        # Outputs
  versions.tf       # Provider pinning
```

## Apply

```bash
terraform init

terraform apply \
  -var="project_id=your-project" \
  -var="image=asia-northeast3-docker.pkg.dev/your-project/apps/nexus-hive:0.2.0" \
  -var="environment=prod" \
  -var='authenticated_invokers=["group:analytics-internal@example.com"]' \
  -var='notification_channels=["projects/your-project/notificationChannels/123456789"]'
```

## Populating secrets

Each key in `local.secret_env_map` (in `secrets.tf`) is created as an empty
Secret. Populate them out-of-band:

```bash
echo -n "your-snowflake-password" | \
  gcloud secrets versions add nexus-hive-snowflake-password --data-file=-

echo -n "dapi..." | \
  gcloud secrets versions add nexus-hive-databricks-token --data-file=-
```

In a sandbox, pass `-var=create_stub_secret_versions=true` to pre-populate a
`REPLACE_ME` value so the first revision starts.

## Variables

| Name | Type | Default | Description |
|---|---|---|---|
| `project_id` | string | _required_ | GCP project ID |
| `region` | string | `asia-northeast3` | Cloud Run region |
| `service_name` | string | `nexus-hive` | Cloud Run service name |
| `image` | string | _required_ | Container image URL |
| `env` | map(string) | `{}` | Non-secret environment variables |
| `environment` | string | `prod` | Deployment environment label |
| `min_instances` | number | `1` | Cloud Run min instance count |
| `max_instances` | number | `10` | Cloud Run max instance count |
| `concurrency` | number | `40` | Max concurrent requests per instance |
| `request_timeout_seconds` | number | `120` | Cloud Run request timeout |
| `cpu_limit` | string | `"1"` | CPU limit per instance |
| `memory_limit` | string | `"1Gi"` | Memory limit per instance |
| `ingress` | string | `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` | Ingress setting |
| `allow_unauthenticated` | bool | `false` | Bind `allUsers` to `roles/run.invoker` |
| `authenticated_invokers` | list(string) | `[]` | IAM members granted `roles/run.invoker` |
| `deletion_protection` | bool | `true` | Prevents accidental `terraform destroy` |
| `create_vpc_connector` | bool | `false` | Create Serverless VPC Access connector |
| `vpc_network_name` | string | `default` | VPC network for the connector |
| `vpc_connector_cidr` | string | `10.8.0.0/28` | Connector CIDR |
| `vpc_egress` | string | `PRIVATE_RANGES_ONLY` | Egress policy via connector |
| `enable_workload_identity` | bool | `false` | Bind GKE KSA to runtime SA |
| `workload_identity_namespace` | string | `analytics` | KSA namespace |
| `workload_identity_ksa` | string | `nexus-hive` | KSA name |
| `create_deployer_sa` | bool | `false` | Provision a CI/CD deployer SA |
| `create_stub_secret_versions` | bool | `false` | Stub secrets with `REPLACE_ME` |
| `notification_channels` | list(string) | `[]` | Alert notification channel IDs |

## Outputs

| Name | Description |
|---|---|
| `service_uri` | Cloud Run URL |
| `service_name` | Cloud Run service name |
| `service_account_email` | Runtime service account email |
| `deployer_service_account_email` | CI/CD deployer SA email (null when disabled) |
| `secret_ids` | Map of env-var-name to Secret Manager secret ID |
| `uptime_check_id` | Uptime check ID |
| `vpc_connector_id` | VPC Access connector ID (null when disabled) |

## Enabled APIs

`main.tf` enables: `run`, `iam`, `secretmanager`, `monitoring`, `logging`,
`vpcaccess`, `cloudresourcemanager`. These are kept on destroy so other
workloads are not disrupted.

## Related

- `docs/runbooks/production-deploy.md` - 1-hour rollout on GCP
- `docs/runbooks/incident-response.md` - what to do when alerts fire
