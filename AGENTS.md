# Repository Guidelines

## Architecture
- Control Plane (`orchestrator/`): FastAPI app exposing routers for `projects`, `work-items`, `scheduler`, and `observability`; SQLAlchemy + Postgres; middleware for request ID, CORS, and rate limiting; optional background tick (`ORCH_SCHEDULER_BACKGROUND_INTERVAL`).
- Agents (`agents/runner/` + `scripts/agent.py`): Polls the queue, plans steps from work item titles or ToolRecipe, requests missing inputs (Info Requests), executes commands, streams logs, and completes runs. Available locally (`make agent`) or containerized (`make up-agent`).
- Data Model: `Project`, `Vision`, `RequirementsDraft`, `WorkItem`, `Run`, `ApprovalRequest`, `ScheduledTask`, `ToolRecipe` (optional), `InfoRequest`.
- End-to-End Flow: project/vision → requirements propose/approve → work items + (optional) tool recipes → approvals → enqueue with deps → scheduler tick → agent executes → logs/metrics/traces → done.
- Security & Guardrails: approval policy (`ORCH_REQUIRE_APPROVAL`), sliding-window rate limiting, CORS, optional encryption-at-rest for Info Request responses (`ORCH_SECRET_KEY`).

```text
 User / CLI / UI
   |
   | HTTP (REST / WebSocket)
   v
 +-------------------------+        +-----------------------+
 | Orchestrator (FastAPI)  | <----> | Postgres (Persistence)|
 | - routers + middleware  |        | core tables & logs    |
 | - scheduler tick        |        +-----------------------+
 +------------+------------+
              |
              | queue/runs (API)
              v
      +--------------------+
      | Agent (Runner)     |
      | - plan/execute     |
      | - info requests    |
      | - stream/complete  |
      +--------------------+
```

## Project Structure & Module Organization
- Current: `Codex_Orchestrator_Requirements.md` is the authoritative scope/architecture.
- Planned layout (subject to scaffolding): `orchestrator/` (control plane), `agents/` (worker roles), `ui/` (web), `infra/` (IaC/helm), `tests/` (unit/integration), `scripts/` (dev/CI), `docs/` (ADRs, guides).
- Keep modules small and role‑focused. Co-locate tests with code when practical (e.g., `agents/dev/` + `agents/dev/__tests__/`).
- Implemented: FastAPI orchestrator backend at `orchestrator/` with routers for projects and work items.
- Added: approvals, scheduler, and observability routers.
 - Added: tool recipe validation (YAML) and endpoints; CORS and rate limiting middleware.

## Build, Test, and Development Commands
- Local stack (Docker):
  - `docker compose up --build` or `make dev`: start Postgres and the FastAPI service at `http://localhost:18080`.
  - `docker compose down -v`: stop and remove volumes.
- Tests: `pip install -r orchestrator/requirements.txt && make test` (spins Docker stack, runs e2e test via HTTP).
- Build images: `make build`.
- Formatting/Linting: `make fmt` (Black), `make lint` (Ruff).
- Convenience: `make up` / `make down` to manage stack; `make seed` to create sample data.
 - Config: `.env` with `ORCH_DATABASE_URL`, `ORCH_REQUIRE_APPROVAL`, `ORCH_CORS_ORIGINS`, `ORCH_RATE_LIMIT_PER_MIN`.

## Agent: Optional LLM Planning via Codex CLI
The agent can optionally use an LLM to plan/augment step execution. To avoid direct provider coupling,
the agent prefers invoking the Codex CLI (or any CLI) you configure, passing the prompt via stdin and
capturing the response from stdout.

- Enable feature: set `AGENT_ENABLE_LLM_PLANNING=true` in the agent environment.
- Configure CLI command with `CODEX_PLAN_CMD` or rely on the default:
  - Default: `codex exec --ask-for-approval never --sandbox read-only`
  - Or specify: `CODEX_PLAN_CMD="codex exec -m gpt-4o-mini --ask-for-approval never --sandbox read-only"`
  - The command must read the prompt from stdin and print the raw model output to stdout.
- Output contract: the model must return a JSON array of steps, where each element is either a string command or an object:
  - `{ "run": "echo build", "env": {"KEY":"VAL"}, "timeout": 30, "cwd": "./dir" }`

Fallbacks
- If `CODEX_PLAN_CMD` is not set or the CLI invocation fails, the agent uses its deterministic inference.
- You can optionally allow a direct OpenAI fallback by setting `AGENT_ALLOW_OPENAI_FALLBACK=true` and `OPENAI_API_KEY`.
  - Optional: `ORCH_OPENAI_MODEL` (default `gpt-4o-mini`), `ORCH_OPENAI_BASE_URL`.

Notes
- The agent updates the run with structured step events and logs as usual.
- LLM planning is a refinement step; if the model output is invalid JSON or empty, the agent falls back automatically.

## Agent: Full-Autonomy Executor via Codex
In addition to using Codex for planning, you can delegate the entire execution of a work item to Codex CLI.

- Enable by setting `AGENT_EXECUTOR=codex`. The agent will:
  - Claim a run and start a heartbeat.
  - Launch `codex exec --ask-for-approval never --sandbox workspace-write` and feed it a prompt with the Work Item title/description and optional ToolRecipe.
  - Stream Codex output to run logs and mark the run succeeded/failed based on the process exit code.

- Containerized defaults:
  - The agent image includes Codex CLI and a default `~/.codex/config.toml` enabling network in workspace-write:
    -
    ```toml
    [sandbox_workspace_write]
    network_access = true
    ```
  - If you prefer usage-based billing, set `OPENAI_API_KEY` in the container env. Otherwise run `codex login` interactively and copy `~/.codex/auth.json` as described in Codex README for headless setups.

- Compose overlay (`docker-compose.agent.yml`) sets `AGENT_EXECUTOR=codex` by default so Codex runs in full autonomy inside the container.

## Coding Style & Naming Conventions
- Formatting: enforce tool defaults (no bikeshedding). Use Prettier (TS/JS/MD), Black (Python), `gofmt` (Go).
- Linting: ESLint + TypeScript strict, Ruff for Python, `staticcheck`/`golangci-lint` for Go.
- Indentation: 2 spaces (TS/JS), 4 spaces (Python), tabs (Go).
- Names: kebab-case for files (`task-router.ts`), PascalCase for types/classes, snake_case for Python modules, lower_snake for Make targets.

## Testing Guidelines
- Framework: Pytest for backend; e2e test hits Dockerized API (see `tests/test_api.py`).
- Coverage target (MVP): ≥70% for service packages; raise over time.
- Naming: `test_*.py` for Python tests.
- Keep tests deterministic; external calls are stubbed/mocked.
- Additional e2e: `tests/test_work_items.py` covers work item run lifecycle.
- Approvals/scheduler: `tests/test_approvals.py`, `tests/test_scheduler.py` validate guardrails and queue.
- Observability/logs: `tests/test_logs_and_health.py` validates health and run logs.
 - Tool recipes: `tests/test_tool_recipes.py` validates YAML schema and errors.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`, `ci:`.
  - Examples: `feat(orchestrator): add task scheduler`, `fix(agents/dev): handle missing tool recipe`.
- PRs: clear description, linked issue, checklist (tests, docs, screenshots/logs), and rollout notes if applicable.
- Small, reviewable changes; keep PRs under ~400 lines when possible.

## Security & Configuration Tips
- Never commit secrets. Use `.env.local` (gitignored) and secret managers in CI.
- Prefer least-privilege credentials; stub cloud resources in local runs.
- Reference architecture and guardrails: see `Codex_Orchestrator_Requirements.md`.
 - Config env prefix: `ORCH_...` (e.g., `ORCH_DATABASE_URL`, `ORCH_REQUIRE_APPROVAL`, `ORCH_SECRET_KEY`, `ORCH_SCHEDULER_BACKGROUND_INTERVAL`).

## Development Context & Progress
- Progress tracker: see `PROGRESS.md` for completed tasks and next steps.
- Current focus: MVP API flow and work item/run lifecycle with Postgres.
- Current scope includes approvals/policy flag, observability metrics, and a simple scheduler with dependencies.
- Next milestones: richer logs/metrics, API docs polish, and seed scripts.

## Scaling & Reliability
- Horizontal agents: run multiple agent replicas to increase throughput. Specialize agents per domain (e.g., macOS for iOS builds).
- Claims/heartbeats: single-writer ownership per run via `claim` + `heartbeat`. Lease expiration allows safe takeover.
- Queue priorities: higher priority runs earlier. Use in `POST /scheduler/enqueue`.
- Retries/backoff: automatic re-queue on failure up to `ORCH_MAX_RETRIES`, with exponential backoff from `ORCH_BACKOFF_BASE_SECONDS`, plus jitter to reduce bursts. Per-work-item overrides via `POST /work-items/{id}/policy`.
- Requeue endpoints: explicit requeue for work items and runs with optional `delay_seconds` and `backoff`.
- Deploy: Kubernetes manifests and Helm chart under `infra/` for orchestrator and agent fleets.
