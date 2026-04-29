FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
# ComparativeEngine/ is mounted as a volume at runtime (see docker-compose.yml)
ENV PYTHONPATH=/app
EXPOSE 8003
CMD ["python", "src/handler.py"]
