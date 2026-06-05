FROM python:3.12-slim
WORKDIR /app
COPY services/data-normalizer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/data-normalizer/src/ ./src/
# DataNormalizer/ and shared/ are mounted as volumes at runtime
ENV PYTHONPATH=/app
EXPOSE 8006
CMD ["python", "src/handler.py"]
