# Build context: repo root (docker-compose sets context: .)
FROM python:3.12-slim
WORKDIR /app

COPY services/beckn-bap-client/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY services/beckn-bap-client/src/ ./src/

# Copy shared models (needed by beckn/models.py)
COPY shared/ ./shared/

# pydantic-settings looks for .env at /app/.env — provide empty file
RUN touch .env

ENV PYTHONPATH=/app

EXPOSE 8002
CMD ["python", "-m", "src.handler"]
