FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir requests PyYAML
COPY scripts/agent.py /app/agent.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/agent.py"]

