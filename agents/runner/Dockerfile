FROM python:3.11-slim

WORKDIR /app
# System deps for Codex CLI
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates git nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
RUN pip install --no-cache-dir requests PyYAML

# Install Codex CLI globally (optional but present for containerized usage)
RUN npm i -g @openai/codex \
    && codex --version || true

# Default Codex config enabling network in workspace-write sandbox
RUN mkdir -p /root/.codex \
    && echo '\n[sandbox_workspace_write]\nnetwork_access = true\n' > /root/.codex/config.toml
COPY scripts/agent.py /app/agent.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/agent.py"]
