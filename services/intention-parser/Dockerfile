FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# IntentParser/ and shared/ are mounted as volumes at runtime (see docker-compose.yml)
ENV PYTHONPATH=/app

EXPOSE 8001
CMD ["python", "src/handler.py"]
