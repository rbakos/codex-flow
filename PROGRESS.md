# Delivery Progress

This file tracks completed tasks across Codex sessions.

Completed
- Scaffolding: Python FastAPI orchestrator service with Postgres persistence.
- API: create project, submit vision, propose/approve requirements.
- Containers: Dockerfile for service, docker-compose with Postgres.
- Tests: end-to-end test exercising the minimal flow via local Docker.
- Tooling: Makefile with dev/build/test targets.
 - Config: pydantic-settings wired; `.env` support.
 - Work Items: model + API; Run logs + agent stub.
 - Tests: e2e for work item run lifecycle.
- CI: GitHub Actions workflow to run tests.
 - Approvals: policy flag enforced for run start; API to request/approve.
 - Observability: metrics endpoint with basic counters.
- Scheduler: minimal queue with dependency support and tick endpoint.
 - Observability extras: health/ping endpoints; Request ID middleware; logs retrieval endpoint.
 - Seed: script to populate sample data and queue with dependencies.
- Make targets: `up`, `down`, `seed` for convenience.
- Tool Recipes: YAML validation and storage per work item; endpoints to set/get; tests.
- CORS and rate limiting: configurable; high default to avoid test flakiness.
 - Logs: enriched retrieval endpoint with filtering and JSON format.
 - Traces: added stub endpoint and trace_id on runs.
 - OpenAPI: tags, summaries, and endpoint descriptions.
 - Agent: real executable agent that runs ToolRecipe steps and streams logs.
 - ToolRecipe: support structured steps with env/timeout/cwd; API returns YAML.
 - Streaming logs: WebSocket endpoint for live run logs.
 - Docker: containerized agent and compose overlay (`docker-compose.agent.yml`).

Next
 - Expand metrics and tracing details (durations, statuses, per-step spans).
 - Add error schema examples and global 429 documentation.
 - Add structured change/audit log and PR metadata stubs.
