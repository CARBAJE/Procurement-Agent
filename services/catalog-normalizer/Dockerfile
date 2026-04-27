FROM python:3.12-slim
WORKDIR /app
COPY services/catalog-normalizer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/catalog-normalizer/src/ ./src/
COPY shared/ ./shared/
ENV PYTHONPATH=/app
EXPOSE 8005
CMD ["python", "src/handler.py"]
