FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
COPY agents ./agents
COPY evals ./evals
COPY orchestrator ./orchestrator
COPY registry ./registry
COPY shared ./shared

RUN python -m pip install --no-cache-dir --index-url https://packagefeedproxy.microsoft.io/pypi/simple .

EXPOSE 8000

CMD ["sh", "-c", "serve-agent --agent ${AGENT_ID} --port ${PORT:-8000}"]
