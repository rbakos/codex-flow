# Codex Orchestrator

FastAPI-based control plane for coordinating projects, work items, approvals, a minimal scheduler with dependencies, and observability (health, metrics, logs, traces stub).

## Architecture
- Control Plane (`orchestrator/`): FastAPI app with routers for `projects`, `work-items`, `scheduler`, `observability`; SQLAlchemy + Postgres persistence; middleware for request ID, CORS, and rate limiting; optional background scheduler tick (`ORCH_SCHEDULER_BACKGROUND_INTERVAL`).
- Agents (`agents/runner/` + `scripts/agent.py`): Worker process that polls the queue, plans required steps (tool-agnostic by default), requests missing inputs via Info Requests, executes commands, streams logs, and completes runs. Packaged for local use or as a container (`docker-compose.agent.yml`).
- Data Model: `Project`, `Vision`, `RequirementsDraft`, `WorkItem`, `Run`, `ApprovalRequest`, `ScheduledTask`, `ToolRecipe` (optional), `InfoRequest` (ask-user channel).
- Flow: Create project/vision → propose/approve requirements → create work items → request/approve where needed → enqueue (with dependencies) → scheduler starts runs → agent executes steps (with optional ToolRecipe) → logs/traces → complete.
- Extensibility: Optional Tool Recipes (validated YAML), provider-aware planning (AWS/GCP/Azure/K8s), encrypted Info Requests, streaming logs, and OpenAPI docs.

```text
 User / CLI / UI
   |
   | HTTP (REST / WebSocket)
   v
 +-------------------------+        +-----------------------+
 | Orchestrator (FastAPI)  | <----> | Postgres (Persistence)|
 | - projects/work-items   |        | projects, work_items, |
 | - scheduler/observability|       | runs, approvals, ...  |
 | - rate limit, CORS      |        +-----------------------+
 | - background tick (opt) |
 +------------+------------+
              |
              | queue/runs (API)
              v
      +--------------------+
      | Agent (Runner)     |
      | - plan steps       |
      | - info requests    |
      | - exec + stream    |
      | - complete runs    |
      +---------+----------+
                ^
                |
       Info Requests (create/list/respond)
                |
             User/Tool
```

Planned Layout
- `orchestrator/` (control plane)
- `agents/` (worker roles; e.g., `agents/runner/`)
- `ui/` (web UI)
- `infra/` (IaC/helm)
- `tests/` (unit/integration/e2e)
- `scripts/` (dev/CI utilities)
- `docs/` (ADRs, guides)

## How It Works (MVP)
The orchestrator models the control plane for autonomous build, test, and deploy workflows.

- Project: top-level scope for a delivery effort.
- Vision: high-level intent; used to derive requirements (stubbed deterministic draft).
- RequirementsDraft: proposed/approved requirements for the current vision.
- WorkItem: unit of work to build/test/deploy something; holds runs and a tool recipe.
- Run: execution instance of a work item; produces logs and a `trace_id`.
- ApprovalRequest: guardrail to gate risky actions (e.g., production deploy).
- ScheduledTask: queue entry with optional dependency on another work item.
- ToolRecipe: YAML describing tools needed by an agent (e.g., `awscli`, `opentofu`).

Flow overview:
1) You define a project and optionally submit a vision and approve requirements.
2) You create work items, attach tool recipes, and request/approve where needed.
3) You enqueue work items with dependencies; the scheduler starts eligible runs on `tick`.
4) Agents (future) execute runs using the tool recipe; MVP simulates via endpoints.
5) You fetch logs/traces and mark runs complete to unlock dependent tasks.

OpenAPI docs: `http://localhost:18080/docs` (after `docker compose up`).

## Tool Recipe (YAML)
Validated schema (MVP):

```yaml
tools:
  - name: awscli
    version: 2.15.0
    checksum: sha256:deadbeef
    env: { AWS_DEFAULT_REGION: us-east-1 }
    network: true
  - name: opentofu
    version: 1.7.0
    network: false
steps:
  - echo "build"
  - echo "test"
  - run: echo "deploy"
    env: { STAGE: prod }
    timeout: 60
    cwd: ./deploy
```

Agents provision tools and execute `steps` accordingly. Tool recipes are optional: if absent, the Agent infers a sensible set of steps from the work item title (e.g., build/test/deploy). The orchestrator validates and stores recipes when provided; see `POST /work-items/{id}/tool-recipe`.

## End-to-End Scenarios
Below are concrete examples using `curl`. Set `BASE=http://localhost:18080`.

### Scenario A: Microservices Build → Test → Deploy (with approvals)
Objective: Build two services (api, web), test them, run integration tests, deploy to staging, then gated deploy to production.

```bash
BASE=${BASE:-http://localhost:18080}

# 1) Project
proj=$(curl -sX POST $BASE/projects/ -H 'content-type: application/json' \
  -d '{"name":"shop-platform","description":"orchestrated demo"}')
pid=$(echo "$proj" | jq -r .id)

# 2) Work items
mkwi() { curl -sX POST $BASE/work-items/ -H 'content-type: application/json' -d "$1"; }
api_build=$(mkwi '{"project_id":'$pid',"title":"api:build","description":"docker build"}')
api_test=$(mkwi  '{"project_id":'$pid',"title":"api:test","description":"unit tests"}')
web_build=$(mkwi '{"project_id":'$pid',"title":"web:build","description":"vite build"}')
web_test=$(mkwi  '{"project_id":'$pid',"title":"web:test","description":"jest"}')
integ=$(mkwi      '{"project_id":'$pid',"title":"integration:test","description":"e2e"}')
deploy_stg=$(mkwi '{"project_id":'$pid',"title":"deploy:staging","description":"rollout"}')
deploy_prd=$(mkwi '{"project_id":'$pid',"title":"deploy:prod","description":"gated"}')

# extract IDs
jid() { echo "$1" | jq -r .id; }
api_b=$(jid "$api_build"); api_t=$(jid "$api_test"); web_b=$(jid "$web_build"); web_t=$(jid "$web_test")
it=$(jid "$integ"); stg=$(jid "$deploy_stg"); prd=$(jid "$deploy_prd")

# 3) Approvals for risky steps (staging+prod)
ar_stg=$(curl -sX POST $BASE/work-items/$stg/approvals)
curl -sX POST $BASE/work-items/approvals/$(echo "$ar_stg"|jq -r .id)/approve >/dev/null
ar_prd=$(curl -sX POST $BASE/work-items/$prd/approvals)
curl -sX POST $BASE/work-items/approvals/$(echo "$ar_prd"|jq -r .id)/approve >/dev/null

# 4) Enqueue with dependencies
q() { curl -sS -X POST $BASE/scheduler/enqueue -H 'content-type: application/json' -d "$1"; }
q '{"work_item_id":'$api_b'}'
q '{"work_item_id":'$web_b'}'
q '{"work_item_id":'$api_t',"depends_on_work_item_id":'$api_b'}'
q '{"work_item_id":'$web_t',"depends_on_work_item_id":'$web_b'}'
q '{"work_item_id":'$it',"depends_on_work_item_id":'$api_t'}'
q '{"work_item_id":'$it',"depends_on_work_item_id":'$web_t'}'  # parallel dep modeled as two queued items pointing to same WI
q '{"work_item_id":'$stg',"depends_on_work_item_id":'$it'}'
q '{"work_item_id":'$prd',"depends_on_work_item_id":'$stg'}'

# 5) Drive the scheduler; complete runs to unlock dependents
tick() { curl -sX POST $BASE/scheduler/tick; }
list_runs() { curl -s $BASE/work-items/$1/runs | jq -r '.[0].id'; }
complete() { curl -sX POST "$BASE/work-items/runs/$1/complete?success=true" >/dev/null; }

tick; rid=$(list_runs $api_b); complete $rid
tick; rid=$(list_runs $web_b); complete $rid
tick; rid=$(list_runs $api_t); complete $rid
tick; rid=$(list_runs $web_t); complete $rid
tick; rid=$(list_runs $it);   complete $rid
tick; rid=$(list_runs $stg);  complete $rid
tick; rid=$(list_runs $prd);  complete $rid

# 6) Inspect logs and traces
curl -s $BASE/work-items/runs/$rid/logs
curl -s $BASE/observability/traces | jq '.[0]'
```

Notes:
- The MVP agent is a stub; runs start via scheduler and are manually completed in the example. In production, agents would pick up runs and update status/logs.
- Parallel dependencies can be modeled by enqueuing multiple tasks that depend on the same predecessor(s) or by chaining separate WIs.

### Scenario B: Infrastructure Provision (Tofu + AWS) with Approval
Objective: Plan then apply infra with a manual approval gate.

```bash
BASE=${BASE:-http://localhost:18080}
p=$(curl -sX POST $BASE/projects/ -H 'content-type: application/json' -d '{"name":"infra","description":"tofu"}')
pid=$(echo "$p"|jq -r .id)

plan=$(curl -sX POST $BASE/work-items/ -H 'content-type: application/json' -d '{"project_id":'$pid',"title":"tofu:plan"}')
apply=$(curl -sX POST $BASE/work-items/ -H 'content-type: application/json' -d '{"project_id":'$pid',"title":"tofu:apply"}')
plan_id=$(echo "$plan"|jq -r .id); apply_id=$(echo "$apply"|jq -r .id)

# Attach tool recipe to both (awscli+opentofu)
read -r -d '' yaml <<'YAML'
tools:
  - name: awscli
    version: 2.15.0
    env: { AWS_DEFAULT_REGION: us-east-1 }
    network: true
  - name: opentofu
    version: 1.7.0
    network: false
YAML
curl -sX POST $BASE/work-items/$plan_id/tool-recipe -H 'content-type: application/json' -d "$(jq -Rn --arg yaml "$yaml" '{yaml:$yaml}')" >/dev/null
curl -sX POST $BASE/work-items/$apply_id/tool-recipe -H 'content-type: application/json' -d "$(jq -Rn --arg yaml "$yaml" '{yaml:$yaml}')" >/dev/null

# Approval for apply
ar=$(curl -sX POST $BASE/work-items/$apply_id/approvals)
curl -sX POST $BASE/work-items/approvals/$(echo "$ar"|jq -r .id)/approve >/dev/null

# Enqueue and drive
curl -sX POST $BASE/scheduler/enqueue -H 'content-type: application/json' -d '{"work_item_id":'$plan_id'}' >/dev/null
curl -sX POST $BASE/scheduler/enqueue -H 'content-type: application/json' -d '{"work_item_id":'$apply_id',"depends_on_work_item_id":'$plan_id'}' >/dev/null
curl -sX POST $BASE/scheduler/tick; rid=$(curl -s $BASE/work-items/$plan_id/runs|jq -r '.[0].id'); curl -sX POST "$BASE/work-items/runs/$rid/complete?success=true" >/dev/null
curl -sX POST $BASE/scheduler/tick; rid=$(curl -s $BASE/work-items/$apply_id/runs|jq -r '.[0].id'); curl -sX POST "$BASE/work-items/runs/$rid/complete?success=true" >/dev/null
```

### Scenario C: Logs and Filtering
```bash
run_id=$(curl -s $BASE/work-items/1/runs | jq -r '.[0].id')
curl -s "$BASE/work-items/runs/$run_id/logs?format=json&q=Starting&limit=10"
```

## Observability & Guardrails
- Health and Metrics: `/observability/health`, `/observability/metrics`
- Logs: `GET /work-items/runs/{run_id}/logs` returns text or JSON (`format=json`) with `q`, `limit`, `offset`. Live streaming via WebSocket: `GET /work-items/runs/{run_id}/logs/ws`.
- Traces (stub): `GET /observability/traces` lists recent runs with `trace_id`.
- Rate Limiting: sliding window; default high. 429s include remaining in `X-RateLimit-Remaining` header.
- Approvals: enforced when `ORCH_REQUIRE_APPROVAL=true` (default). Scheduler and manual run start both honor approvals.
- Info Requests: the agent can request missing inputs (e.g., cloud credentials). Use:
  - Create/list handled by agent and `GET /work-items/runs/{run_id}/info-requests`.
  - Respond with `POST /work-items/runs/info-requests/{req_id}/respond` body `{ "values": {"KEY":"VALUE"}}`.
  - Example:
    - List: `curl -s $BASE/work-items/runs/$RUN_ID/info-requests | jq`.
    - Respond: `curl -sX POST $BASE/work-items/runs/info-requests/REQ_ID/respond -H 'content-type: application/json' -d '{"values":{"AWS_ACCESS_KEY_ID":"...","AWS_SECRET_ACCESS_KEY":"...","AWS_DEFAULT_REGION":"us-east-1"}}'`.
  - Secret handling: if `ORCH_SECRET_KEY` is set, responses are encrypted at rest and redacted in API. The agent passes `AGENT_SECRET_KEY` and requests plaintext via query flags to retrieve them.

## Running Locally
- Start stack: `docker compose up --build` or `make dev`
- Stop stack: `docker compose down -v` or `make down`
- Seed sample data: `make up && make seed`
- Agent (local): `make agent` to run a local worker that:
  - Calls scheduler tick, finds running tasks, reads ToolRecipe YAML, executes `steps` locally in a shell
  - Streams stdout to run logs and completes runs with success/failure based on exit codes
  - Uses `ORCH_URL` (default `http://localhost:18080`). Optionally set `AGENT_STEPS` (newline-separated) to override steps for demo.
  - If no ToolRecipe is set, the agent works autonomously by inferring steps from the work item title (e.g., containing "build", "test", "deploy", "plan", "apply").
  - If a work item suggests a cloud provider (e.g., contains "aws", "gcp", "azure", "k8s"), the agent checks tool availability and requests required inputs (credentials, project/subscription, kubeconfig) via info requests before executing. Supported hints and requirements:
    - AWS: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` (CLI: `aws`)
    - GCP: `GOOGLE_APPLICATION_CREDENTIALS_JSON`, `GOOGLE_CLOUD_PROJECT` (CLI: `gcloud`)
    - Azure: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID` (CLI: `az`)
    - Kubernetes: `KUBECONFIG_CONTENT` (writes a temp kubeconfig; CLIs: `kubectl`, `helm`)
-- Agent (Docker): `make up-agent` to run orchestrator + agent container. Use `make down-agent` to stop both. Dockerfile at `agents/runner/Dockerfile`.
  - Background ticker: agent runs a scheduler tick in the background (`AGENT_TICK_INTERVAL`, default 1s) so dependent tasks continue progressing even during long steps.

## Configuration
- Orchestrator env (prefix `ORCH_`):
  - `ORCH_DATABASE_URL`: SQLAlchemy URL to Postgres
  - `ORCH_REQUIRE_APPROVAL`: gate runs behind approvals (default true)
  - `ORCH_CORS_ORIGINS`: CSV list or `*`
  - `ORCH_RATE_LIMIT_PER_MIN`: sliding window per-client (default 1000)
  - `ORCH_SECRET_KEY`: optional Fernet key to encrypt info request responses
  - `ORCH_SCHEDULER_BACKGROUND_INTERVAL`: seconds for background tick (0 disables)
- Agent env:
  - `ORCH_URL`: Orchestrator base URL (default http://localhost:18080)
  - `AGENT_INTERVAL`: main polling interval (default 2s)
  - `AGENT_TICK_INTERVAL`: background tick interval (default 1s)
  - `AGENT_SHELL`: command shell (default /bin/sh)
  - `AGENT_STEPS`: override steps (newline-separated)
  - `AGENT_SECRET_KEY`: shared secret to retrieve decrypted info-request responses
  - `AGENT_ID`: explicit agent identity (defaults to a random id)
  - `AGENT_HEARTBEAT_INTERVAL`: heartbeat cadence (default 10s)
  - `AGENT_CLAIM_TTL`: claim lease TTL seconds (default 300)

### AWS Demo
- Run the stack: `make up` and in another terminal run the agent (`make agent`) or containerized agent (`make up-agent`).
- Create a demo AWS work item and print any info requests: `make demo-aws`.
- If prompted, respond to the info request with required values (credentials/region) using the printed curl command.
- Tail logs with: `curl -s $BASE/work-items/runs/$RUN_ID/logs` or stream with WebSocket.

## Testing
- CI: runs end-to-end tests against the Docker stack.
- Local: `make venv-test` to create `.venv`, install deps, and run tests.

## Web UI (experimental)
- Visit `http://localhost:18080/ui/` for a lightweight UI to:
  - Create projects and work items
  - Request/approve approvals
  - Start/complete runs and view logs (including WebSocket streaming)
  - Enqueue tasks, tick the scheduler, and inspect the queue
  - List and respond to Info Requests
- The UI is mounted only when the `ui/` folder exists and is not included in the Docker image by default. For Dockerized UI, add a COPY step to the orchestrator Dockerfile or serve via a separate static host.

## Scaling & Reliability
- Parallel agents: run multiple agents to increase throughput; each agent independently executes runs.
- Claims & heartbeats: agents call `POST /work-items/runs/{id}/claim` then periodically `.../heartbeat` to ensure exclusive ownership. If a lease expires (no heartbeat before TTL), runs can be re-claimed.
- Priorities: queue entries accept `priority` so urgent tasks run first.
- Retries with backoff: failed runs are re-queued up to `ORCH_MAX_RETRIES` with exponential backoff from `ORCH_BACKOFF_BASE_SECONDS`. Per-item overrides are supported via `POST /work-items/{id}/policy` with `max_retries`, `backoff_base_seconds`, `backoff_jitter_seconds`.
- Jitter: randomizes backoff to avoid bursts on large fleets.
- Requeue APIs: `POST /scheduler/requeue/work-item` and `POST /scheduler/requeue/run/{run_id}` support explicit requeue with `delay_seconds`/`priority` or automatic `backoff`.
- Kubernetes: manifests in `infra/k8s/` and a Helm chart in `infra/helm/codex-orch/` to deploy orchestrator and scale agents (replicas).

## Codex CLI Integration
- Stable Make targets suitable for Codex CLI pipelines:
  - `make codex-up` — start Postgres + orchestrator
  - `make codex-agent` — start local agent (uses `.venv`)
  - `make codex-demo-aws` / `make codex-demo-gcp` / `make codex-demo-azure` — create demo work items and print Info Request instructions
  - `make codex-test` — create venv and run tests
- Use Codex CLI to run these targets in sequence (e.g., `codex run make codex-up && make codex-agent`). The `/ui` endpoint can be used for quick inspection.
 - A `codex.yaml` is included with a simple pipeline and individual tasks. Example:
   - `codex run pipeline up agent demo` (bring up orchestrator, start agent, run demo)
   - `codex run task codex-test` (run tests)

### Codex CLI Runtime Behavior
- Error/backoff:
  - Agent handles HTTP 429 and transient errors with a small backoff (`CODEX_ERROR_BACKOFF`, default 2s) and continues.
  - Scheduler tick is resilient to transient failures.
- Remaining context:
  - If Codex CLI exports `CODEX_CONTEXT_REMAINING`, the agent can reduce chatter when the value is low (advisory logging).
- Usage limits:
  - Per-project daily run quotas are supported and enforced at scheduler start time.
  - Configure with `POST /projects/{id}/quota` and inspect via `GET /observability/usage`.
  - When a quota is hit, tasks remain queued until the window resets or quotas are raised.

## Extending Toward Full Autonomy
- Agents: containerized agent available; adjust Dockerfile to add more tools and mount workspaces. Consider sandboxing and credentials.
- Tracing: propagate `trace_id` to agents and downstream systems; add spans per step.
- Policies: additional approval types, role-based controls, and change/audit logs.
- Scheduling: richer DAG semantics and automatic tick via background scheduler.
