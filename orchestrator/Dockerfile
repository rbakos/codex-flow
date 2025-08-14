FROM python:3.11-slim

WORKDIR /app
COPY orchestrator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY orchestrator /app/orchestrator
COPY ui /app/ui

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "orchestrator.orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
