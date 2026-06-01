# Negotiation Engine — Phase 3 microservice.
#
# Build context: this directory (services/negotiation_engine/).
# Matches the orchestrator's service-local context pattern.
#
# Build:
#     docker build -t negotiation-engine services/negotiation_engine
# Run (standalone):
#     docker run --rm -p 8004:8004 negotiation-engine
# Compose:
#     docker compose -f services/negotiation_engine/docker-compose.yml up

FROM python:3.12-slim

WORKDIR /app

# Pin tini for clean PID-1 signal handling (graceful SIGTERM → drain
# in-flight LangGraph threads via the lifespan hook in main.py).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so the layer caches well.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Service source.
COPY src/ ./src/

# pydantic-settings looks for .env at the service root — provide an
# empty file so it doesn't error when the user has no .env.
RUN touch .env

# Sensible runtime defaults — these can be overridden by docker-compose
# or the orchestrator. Anything containing secrets (OPENAI_API_KEY,
# LANGCHAIN_API_KEY, KAFKA_BOOTSTRAP_SERVERS auth) MUST come from the
# deployment environment, never baked into the image.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    NEGOTIATION_LOG_LEVEL=INFO \
    NEGOTIATION_API_HOST=0.0.0.0 \
    NEGOTIATION_API_PORT=8004

EXPOSE 8004

# Liveness probe — readyz validates the LangGraph compiled.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8004/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# `--proxy-headers` lets us trust X-Forwarded-* when fronted by an
# ingress; safe inside the cluster network.
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8004", \
     "--proxy-headers", \
     "--no-server-header"]
