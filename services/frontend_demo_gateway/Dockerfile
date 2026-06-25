# Frontend Demo Gateway — Phase 3 demo gateway (hosts the qwen3:8b Supplier Agent).
#
# Build context MUST be the repo root: the gateway imports the sibling `core`
# package (PyTorch Phase-2 scorer) from services/ComparativeAndScoreing via
# `_paths.py`, and runs under its package path `services.frontend_demo_gateway`.
#
# Build (from repo root):
#     docker build -f services/frontend_demo_gateway/Dockerfile -t demo-gateway .
# Compose:
#     build: { context: ., dockerfile: ./services/frontend_demo_gateway/Dockerfile }

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching. CPU-only torch wheel avoids the
# multi-GB CUDA download — a Dockerfile install choice; the pinned
# requirement (torch>=2.1) is unchanged.
COPY services/frontend_demo_gateway/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
      -r /tmp/requirements.txt

# Gateway package + the self-contained sibling `core` package its /score
# endpoint imports (core/ is 64K: numpy/torch/pydantic only, no ML registry).
COPY services/frontend_demo_gateway/ /app/services/frontend_demo_gateway/
COPY services/ComparativeAndScoreing/core/ /app/services/ComparativeAndScoreing/core/

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DEMO_GATEWAY_LOG_LEVEL=INFO

EXPOSE 8005

# readyz confirms the score model + supplier agent singletons are loaded.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://localhost:8005/readyz || exit 1

CMD ["uvicorn", "services.frontend_demo_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "8005"]
