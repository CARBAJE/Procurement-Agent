FROM python:3.12-slim
WORKDIR /app
COPY services/catalog-normalizer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/catalog-normalizer/src/ ./src/
# CatalogNormalizer/ and shared/ are mounted as volumes at runtime (see docker-compose.yml)
ENV PYTHONPATH=/app
EXPOSE 8005
CMD ["python", "src/handler.py"]
