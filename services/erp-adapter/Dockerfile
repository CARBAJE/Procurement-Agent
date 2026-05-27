FROM python:3.12-slim
WORKDIR /app

COPY services/erp-adapter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/erp-adapter/src/ ./src/

EXPOSE 8007
CMD ["python", "src/main.py"]
