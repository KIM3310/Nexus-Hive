# Nexus-Hive Terraform

Minimal Cloud Run deployment skeleton for `Nexus-Hive`.

## Apply

```bash
terraform init
terraform apply \
  -var="project_id=your-project" \
  -var="image=asia-northeast3-docker.pkg.dev/your-project/apps/nexus-hive:latest"
```

Use `env` to inject `NEXUS_HIVE_OPERATOR_TOKEN`, model routing, and runtime store configuration.
