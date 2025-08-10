.PHONY: dev build test fmt lint venv venv-install venv-test agent up-agent down-agent demo-aws demo-gcp demo-azure codex-up codex-agent codex-demo-aws codex-demo-gcp codex-demo-azure codex-test

dev:
	docker compose up --build

build:
	docker compose build

test:
	pytest -q

fmt:
	python -m black orchestrator || true

lint:
	python -m ruff check orchestrator || true

up:
	docker compose up -d --build

down:
	docker compose down -v

seed:
	ORCH_URL=http://localhost:18080 python scripts/seed.py

# Local Python venv helpers for running tests outside CI
venv:
	python3 -m venv .venv

venv-install: venv
	./.venv/bin/python -m pip install -U pip
	./.venv/bin/pip install -r orchestrator/requirements.txt

venv-test: venv-install
	./.venv/bin/pytest -q

agent: venv-install
	ORCH_URL=http://localhost:18080 ./.venv/bin/python scripts/agent.py

up-agent:
	docker compose -f docker-compose.yml -f docker-compose.agent.yml up -d --build

down-agent:
	docker compose -f docker-compose.yml -f docker-compose.agent.yml down -v

demo-aws:
	ORCH_URL=http://localhost:18080 python scripts/demo_aws.py

demo-gcp:
	ORCH_URL=http://localhost:18080 python scripts/demo_gcp.py

demo-azure:
	ORCH_URL=http://localhost:18080 python scripts/demo_azure.py

# Codex CLI-friendly aliases (stable names)
codex-up: up
codex-agent: agent
codex-demo-aws: demo-aws
codex-demo-gcp: demo-gcp
codex-demo-azure: demo-azure
codex-test: venv-test
