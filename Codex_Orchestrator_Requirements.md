
# Codex Orchestrator – Requirements & Architecture

## 1) Product vision & goals
**Vision:** A Docker-native, agent‑orchestration platform that turns human‑readable intents into production‑grade software systems, from repo init to multi‑cloud deployment, with auditable autonomy and human-in-the-loop controls.  It will be driven by the GPT-5 API initially.

**Primary goals**
- Let a user describe a "Vision" in plain language and get to a deployed, running system.
- Autonomously derive, propose, and iterate on requirements, design, implementation, tests, infra, and deployment plans.
- Seamlessly provision tools (e.g., OpenTofu/Terraform, AWS CLI, Helm, kubectl) inside ephemeral containers as needed.
- Coordinate multiple specialized agents (“autonomous dev team”) that plan, code, review, test, merge, and deploy.
- Provide a clear cockpit UI: current plan, task board, execution logs, approvals, costs, and status.

**Non-goals (for v1)**
- Training foundation models from scratch.
- Long-running stateful IDE replacement (we’ll integrate with existing IDEs instead).

## 2) Personas
- **Maker** (primary): Technical founder/engineer who wants to rapidly bootstrap complex apps.
- **Architect**: Reviews requirements/architecture plans before approval.
- **Operator**: Oversees deployments, approvals, guardrails, and cost controls.

## 3) Core concepts & data model
- **Project**: Top-level container for all artifacts.
- **Vision**: Natural-language problem statement + constraints + success criteria.
- **Requirements**: Agent‑derived list; must be user‑approved. Versioned.
- **Work Item**: Task/Story/Spike/Test or Infra Task. Kanban states: `Proposed → Approved → In Progress → Review → Done`.
- **Agent**: Specialized role with skills and tools (Planner, Architect, Dev, Infra, QA, Security, Release Manager).
- **Capability**: Discrete skill (e.g., “Generate Django service scaffold”).
- **Tool**: Installable binary or SDK (awscli, opentofu, gcloud, docker, kubectl, helm, poetry, pnpm, etc.).
- **Workspace**: Containerized, ephemeral execution sandbox with mounted volumes and network policy.
- **Run**: An execution attempt by an agent with inputs/outputs, logs, and artifacts.
- **Change**: VCS commit/PR with metadata, diffs, reviewers, checks.
- **Environment**: dev/staging/prod with credentials and policies.

## 4) System architecture (high level)
- **Frontend (Web UI)**: Project creation wizard, Vision→Requirements flow, Task board, Run logs, Approvals, Secrets, Deploy dashboard.
- **Orchestrator (Control Plane)**: 
  - Planner/Decomposer service
  - Task Router & Scheduler
  - Policy & Guardrails service
  - Tooling Resolver & Installer
  - VCS Integrator (GitHub/GitLab/Bitbucket)
  - Cloud Deploy Integrators (AWS/GCP/Azure)
  - Artifact Store & Registry (OCI-compatible)
  - State Store (Postgres) + Vector Store (for RAG)
  - Events bus (NATS/Kafka)
- **Agent Runtimes (Worker Plane)**: Dockerized per-role containers; ephemeral; connect via gRPC to Orchestrator.
- **Observability**: Centralized logs (Loki), traces (OTel/Tempo), metrics (Prometheus), dashboards (Grafana).

## 5) Functional requirements
### 5.1 Vision & requirement derivation
- FR-1: Accept a free-form Vision (NL + optional attachments/specs).
- FR-2: Extract goals, scope boundaries, constraints, NFRs, and success criteria using LLM planning.
- FR-3: Generate a **Proposed Requirements** document (functional + NFRs + architecture options + MVP plan).
- FR-4: Support inline edits and comments by user; track versions; require explicit **user approval** before build.

### 5.2 Planning & decomposition
- FR-5: Produce a **Work Breakdown Structure (WBS)**: epics → stories → tasks with acceptance criteria.
- FR-6: Identify needed tools/capabilities; map to agents and environments.
- FR-7: Create a dependency graph; compute a critical path and a parallelization plan.
- FR-8: Continuously re-plan on failures/feedback; keep an audit trail of plan changes.

### 5.3 Agent team & execution
- FR-9: Ship default agent roles: Planner, Architect, Application Dev, Infra/DevOps, QA, Security, Release Manager, Tech Writer.
- FR-10: Each agent runs in a **Docker workspace** with least-privilege policies.
- FR-11: Agents can request new tools; Orchestrator resolves versions and installs into the workspace (cache for reuse).
- FR-12: Agents can propose changes (commits/PRs), author tests, run linters, formatters, and static analysis.
- FR-13: Agents collaborate: Reviewer agents can comment, require changes, and approve merges based on policy.
- FR-14: Agents can execute **multi-step tool flows**: e.g., OpenTofu plan/apply, Helm install/upgrade, kubectl rollout.
- FR-15: Support **multi-repo** and **monorepo** topologies; cross-repo change orchestration with atomic gates.

### 5.4 Source control & code operations
- FR-16: Integrate with GitHub/GitLab/Bitbucket via OAuth App + PAT; support self-hosted.
- FR-17: Auto-create repos, branches, PRs, tags, releases; enforce branch protection as configured.
- FR-18: Intelligent merge/conflict resolution using structured diffs and LLM assist; require human approval if policy dictates.
- FR-19: Commit signing (GPG/Sigstore) and conventional commits.

### 5.5 Tooling resolution & installation
- FR-20: Tool Catalog with version pinning, checksums, SBOMs, and sandbox rules.
- FR-21: Per-task **Tool Recipe** (YAML) that declares binaries, env vars, credentials, and network permissions.
- FR-22: Cross-platform support (linux/amd64, linux/arm64); deterministic installation (hermetic where possible).
- FR-23: Cache layers to speed up future runs; clean-up for idempotent replays.

### 5.6 Cloud deployment & environments
- FR-24: Cloud adapters: AWS (IAM/OIDC, CloudFormation/OpenTofu, EKS/ECS/Lambda), GCP (GKE/Cloud Run), Azure (AKS/Functions).
- FR-25: Environment definitions with secrets, region, quotas, cost guardrails, and approval thresholds.
- FR-26: Prebuilt **Infra Blueprints** (Kubernetes app, serverless API, data pipeline, multi-service microservices).
- FR-27: Progressive delivery (staging → prod), blue/green/canary; automated rollbacks on SLO/SLA breach.

### 5.7 Testing, QA & quality gates
- FR-28: Generate test scaffolding (unit/integration/e2e/load) and run in CI within agent containers.
- FR-29: Quality gates: coverage thresholds, static analysis, SAST/DAST, SBOM, license checks.
- FR-30: Security agent reviews IaC drift, secrets exposure, dependency risk (e.g., OSV), and enforces policies.

### 5.8 Approvals, guardrails & policy
- FR-31: Policy engine (OPA/Rego or Cedar) for actions that require **Just-In-Time approvals** (e.g., prod deploy, spending >$X).
- FR-32: Four-eye principle optional for merges to protected branches and production changes.
- FR-33: Dry-run and simulation modes for dangerous operations (infra apply, destructive migrations).

### 5.9 Observability & audit
- FR-34: Unified **Run Log** (structured) with step outputs, stdout/stderr, artifacts, and links to PRs/builds/deploys.
- FR-35: Metrics: task throughput, success/failure rates, MTTR, cost per task, tool cache hit rate.
- FR-36: Full audit log of decisions, prompts, model calls, approvals, and environment mutations.

### 5.10 Knowledge & context
- FR-37: Project Knowledge Base: Vision, requirements, decisions (ADRs), diagrams, docs, READMEs.
- FR-38: RAG over project artifacts and external docs; per-agent memory with retention policy.
- FR-39: Import existing repos/specs; infer architecture and generate a modernization plan.

### 5.11 UX & interaction
- FR-40: **Vision Wizard** asks clarifying questions, proposes requirements, and shows diffs on edits.
- FR-41: **Task Board** shows status, owners (agents), dependencies, and ETA bands.
- FR-42: **Console** to chat with the team: address agents, request changes, approve/deny actions.
- FR-43: **Deploy Dashboard**: environments, versions, rollout health, error budgets.
- FR-44: **Secrets & Connections**: bring-your-own cloud creds, Git, container registry, SSO.

### 5.12 Extensibility
- FR-45: Plugin SDK for new Tools, Agents, Blueprints, and Cloud adapters; versioned contracts.
- FR-46: Marketplace (later) for community capabilities.

## 6) Non-functional requirements (NFRs)
- NFR-1: **Security**: Workspaces run with least-privilege, outbound egress controls, and signed tools. Secrets via vault (e.g., HashiCorp Vault or cloud KMS).
- NFR-2: **Compliance**: Audit trails; optional SOC2-ready logging; artifact retention policies.
- NFR-3: **Reliability**: Control Plane HA; horizontal scaling of workers; idempotent task execution; exactly-once semantics for deploy gates.
- NFR-4: **Performance**: Cold-start workspace < 10s (cached); plan generation < 60s for typical projects; parallel task throughput > 100 tasks/hour per node.
- NFR-5: **Cost**: Built-in model usage budgeting; per-project cost caps and alerts.
- NFR-6: **Portability**: Self-hosted and SaaS; requires only Docker + PostgreSQL + Redis + object storage.
- NFR-7: **Privacy**: Data residency options; PII redaction for logs; model call minimization.

## 7) Detailed component design
### 7.1 Orchestrator services
- **Planner Service**: Converts Vision → Requirements → WBS; uses system prompts + reusable planning chains; persists versions.
- **Scheduler**: Topologically sorts tasks; respects dependencies and approvals; assigns to agents with required capabilities.
- **Policy Engine**: Evaluates actions; blocks or requests approval; integrates with SSO and Slack/Email for prompts.
- **Tool Resolver**: From Tool Recipes, picks versions, validates checksums, assembles container layers, and warms cache.
- **VCS Service**: Creates repos/branches/PRs; manages checks; signs commits; coordinates cross-repo merges.
- **Deploy Service**: Translates Blueprints to concrete infra (OpenTofu/Terraform); runs plan/apply; monitors rollouts.
- **Knowledge Service**: Vectorizes docs/code; RAG; embeds logs for later retrieval; supports code-aware chunking.

### 7.2 Agent runtimes
- Base images: `orchestrator/agent-base:{version}` (Debian/Alpine). Non-root, drop capabilities, read-only root filesystem with writable work dir.
- Sidecars: **Toolbox** (installer), **Logger** (OTel), **Secrets** (short‑lived token fetcher).
- gRPC contract: `StartTask`, `ReportProgress`, `EmitArtifact`, `RequestTool`, `OpenPR`, `RunTests`, `Deploy`, `AwaitApproval`.
- Pluggable model clients (OpenAI/Anthropic/others) with retry/backoff and deterministic sampling for reproducibility.

### 7.3 Tool installation
- Tool Recipe (YAML):
```yaml
name: awscli
version: 2.17.x
source:
  url: https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
  checksum: sha256:...
steps:
  - run: unzip awscli-exe-linux-x86_64.zip && ./aws/install
permissions:
  network: ["s3.amazonaws.com"]
  filesystem: ["/workspace"]
  capabilities: []
```
- Recipes stored in a signed catalog; updates via PRs; scanned for supply-chain risk.

### 7.4 State & data
- Postgres schemas: `projects`, `visions`, `requirements`, `tasks`, `runs`, `artifacts`, `environments`, `approvals`, `secrets_refs`, `changes`, `deployments`.
- Object storage (S3/GCS/Azure Blob) for artifacts, SBOMs, build logs.
- Vector store (pgvector/Weaviate) for code/doc embeddings.

## 8) Workflow (end-to-end)
1. **Create Project** → paste Vision.
2. **Clarify**: Planner asks targeted questions (domain, stack preferences, constraints, budget, timeline, compliance needs).
3. **Proposed Requirements** generated → user **approves/edits**.
4. **Plan**: WBS with dependencies; Tool Recipes resolved; environments selected.
5. **Execution**: Agents create repos, scaffolds, tests, infra; PRs open; CI runs; reviews & merges follow policy.
6. **Deploy**: Infra plan/apply; rollout to dev → staging → prod; smoke tests & SLO checks.
7. **Handover**: Tech Writer generates docs, runbooks, ADRs; Release Manager cuts versioned release.
8. **Operate**: Dashboards, alerts, and cost monitoring; change requests become new work items.

## 9) UX specs (high level)
- **Vision Wizard**
  - Pages: Vision → Constraints → Success → Risks → Approvals.
  - Live preview of Proposed Requirements.
- **Project Cockpit**
  - Left: Task board; Right: Run Log; Top: status/health; Bottom: agent chat.
- **Approvals Drawer**: list of pending actions with risk summaries and diffs.
- **Deploy Dashboard**: env tiles, current version, rollout status, error budgets, rollback button.

## 10) Security model
- Workspaces run as non-root; seccomp/apparmor profiles; no Docker-in-Docker in prod; use BuildKit or remote runners.
- Egress allowlist per task; secrets injected at runtime via short‑lived tokens; no secrets stored in images.
- Signed artifacts (Sigstore); SBOMs for every image; vulnerability scanning gates.

## 11) Policies & guardrails (examples)
- Require approval for: prod applies, DB migrations, external DNS changes, monthly spend > threshold.
- Disallow plaintext secrets in repos; enforce commit signing; block known-vulnerable dependencies.
- Drift detection on infra; automatic ticket/work item for remediation.

## 12) Integration requirements
- GitHub, GitLab, Bitbucket
- AWS, GCP, Azure
- Container registries: ECR/GCR/ACR/Docker Hub
- CI providers: GitHub Actions, GitLab CI, Argo Workflows, Tekton (optional)
- SSO: Okta, Azure AD, Google Workspace

## 13) Performance targets & sizing
- Cold start of agent workspace (cached): ≤ 10s; cache miss: ≤ 60s.
- Planning round-trip (Vision → Proposed Requirements): ≤ 60s for 1–2 page inputs.
- Parallelism: 100+ concurrent tasks per node; queue fairness by project.
- Repo ops latency: PR creation ≤ 5s; merge after checks ≤ 10s.

## 14) Telemetry & analytics
- Model token usage per task and per project; budget controls and caps.
- Time-in-state analytics for tasks; bottleneck detection.
- Deployment health correlated with change sets.

## 15) Failure modes & recovery
- Interrupted runs are resumable via checkpoints and idempotent steps.
- Rollback plans for infra; versioned environment manifests.
- Escalation rules to human reviewers on repeated failures.

## 16) Compliance & audit
- Immutable append-only audit log; export to SIEM.
- Data retention policies configurable per project/env.
- PII/PHI tagging; optional redaction in logs and prompts.

## 17) Testing strategy
- Golden prompts & regression tests for planners.
- Sandbox integration tests for tool recipes.
- Chaos tests on scheduler and deploy service.
- E2E flows on sample blueprints (web API + DB + queue + frontend + IaC).

## 18) API design (selected)
- REST/gRPC:
  - `POST /projects` (create)
  - `POST /projects/{id}/vision` (submit)
  - `POST /projects/{id}/requirements/propose` → returns draft
  - `POST /projects/{id}/requirements/{rid}/approve`
  - `POST /projects/{id}/tasks/plan` (WBS)
  - `POST /tasks/{id}/run`
  - `POST /runs/{id}/approve`
  - `POST /environments` / `POST /deployments`
  - `GET /audit`, `GET /logs`, `GET /metrics`

## 19) Initial blueprints (starter kits)
- **SaaS Monolith**: FastAPI + Postgres + Redis + OpenTofu + EKS/GKE/AKS + CI.
- **Evented Microservices**: Node/Nest + Kafka + Postgres; API gateway; Kubernetes + Helm.
- **Serverless API**: Lambda/Cloud Run/Azure Functions + IaC.
- **Data/ETL Pipeline**: Airflow + dbt + warehouse (Snowflake/BigQuery/Redshift).

## 20) MVP scope (v0.1)
- Vision Wizard; Proposed Requirements with approval.
- Single-repo generation; GitHub integration; GitHub Actions CI.
- AWS deploy via OpenTofu to EKS (one blueprint) with blue/green.
- Agents: Planner, Dev, Infra, QA (basic tests), Release.
- Tool Recipes: awscli, opentofu, kubectl, helm, poetry/pip, node/pnpm.
- Task board, Run logs, Approvals drawer.

## 21) Post-MVP roadmap
- Advanced Security agent (SAST/DAST, IaC misconfig detection gates).
- Multi-repo orchestration and cross-repo atomic merges.
- GCP/Azure parity; serverless blueprints; data pipeline blueprint.
- Marketplace for plugins/blueprints.
- Cost-aware planning and model selection; offline/air-gapped mode.

## 22) Acceptance criteria
- From a single Vision, the system generates requirements, seeks approval, scaffolds code/infra, opens PRs, runs CI, deploys to AWS EKS, and exposes a working endpoint with docs.
- All critical operations are logged and auditable; at least one approval required for production.
- Tool installation is automatic and reproducible; caches are reused across tasks.
- User can observe progress, approve/deny actions, and roll back a deployment from the UI.

## 23) Open questions
- Preferred default model/provider(s) and pricing controls?
- Default security posture for outbound egress from workspaces?
- Required compliance profiles (SOC2, HIPAA) for early adopters?
