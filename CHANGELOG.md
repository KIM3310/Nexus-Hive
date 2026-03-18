# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-27

### Added
- Live Snowflake adapter with connection pooling and query timeouts
- Live Databricks adapter using Statement Execution API with unified auth
- Snowflake and Databricks demo seeding scripts
- Operator session management with HMAC-signed cookies
- Role-based access control for sensitive column gating
- OpenAI integration with capped public live API and rate limiting
- Governance scorecard, session board, and approval board runtime surfaces
- Semantic governance pack and lakehouse readiness pack endpoints
- Reviewer query demo with gold eval scoring
- Structured JSON logging with request-scoped correlation IDs
- k6 load test script for governance endpoints

### Changed
- Warehouse adapter registry now auto-detects live adapters from credentials
- Policy engine expanded with sensitive column rules per role

## [0.1.0] - 2026-03-15

### Added
- Multi-agent NL-to-SQL pipeline (Translator, Executor, Visualizer) built on LangGraph
- Multi-warehouse support (SQLite, Snowflake, Databricks) via adapter pattern
- Policy engine with deny/review/allow decisions for SQL governance
- Audit trail with JSONL logging and query-audit API endpoints
- Query tag governance metadata compatible with Snowflake QUERY_TAG and Databricks tags
- Session governance surfaces (query session board, approval board)
- Gold eval suite for scoring heuristic and LLM-generated SQL
- Circuit breaker pattern for Ollama LLM resilience
- Heuristic SQL fallback when Ollama is unavailable
- Chart.js visualization generation (bar, line, doughnut) with heuristic fallback
- Prompt injection detection and input sanitization
- FastAPI REST API with SSE streaming, health check, and OpenAPI docs
- Docker and Docker Compose deployment (with optional Ollama sidecar)
- Kubernetes manifests (deployment, service, ingress, HPA, configmap, secrets)
- Terraform configuration for GCP Cloud Run deployment
- SQLite demo database with 10k enterprise sales records seeder
- Frontend with live agent trace streaming and Chart.js rendering
