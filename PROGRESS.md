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

- Fixes/Polish:
  - Fixed `crud.append_run_log` to remove invalid retry logic (pure log append).
  - Agent: corrected claim/heartbeat control flow; heartbeats before execution.
  - Scheduler API: normalized `scheduled_for` to ISO strings in responses.
  - Projects API: added `GET /projects/` and wired UI to list projects.
  - Runs: set `finished_at` on completion; `RunOut` now includes `started_at`, `finished_at`, and computed `duration_seconds`.
  - Metrics: added `runs_by_status`, `runs_avg_duration_seconds`, and a `runs_duration_histogram`.
  - Traces: include `duration_seconds` per run.
  - Structured steps: added `RunStep` model and endpoints to create/list/update steps.
  - Agent: posts structured step events (start/end) with precise timings and status.
  - Observability: `GET /observability/runs/{id}` returns run summary with steps.
  - UI: added Run Detail view with per-step timing bars and Metrics section with histogram.

Next
 - Tests: add coverage for new endpoints and fields
   - `POST/PATCH/GET` run steps, `GET /observability/runs/{id}`, histogram in metrics, `RunOut.duration_seconds`.
 - Migrations: introduce Alembic and create migrations for `run_steps` table and any type changes.
 - UI Enhancements:
   - Add run selector (by project/work item), and step timeline visualization.
   - Live step updates via WebSocket (new `steps/ws` stream) to complement log streaming.
   - Show histogram in UI on dashboard load and auto-refresh.
 - Agent/Demos:
   - Provide demo steps with non-trivial durations (e.g., sleep) to better visualize timings.
   - Optional: emit granular sub-steps for complex commands (probes for tool availability).
 - API Docs: document new endpoints/fields and add global 429/error schema examples.
 - Observability:
   - Add per-step spans via OpenTelemetry; include run/step duration percentiles.
   - Add optional traces correlation IDs on step events.
 - Performance/Schema:
   - Index hot columns (e.g., `runs.status`, `run_steps.run_id`).
   - Consider pagination for `GET /observability/traces` and large step lists.
 - Security:
   - Add auth for write operations and role-based access to observability.
