FROM python:3.12-slim
WORKDIR /app

COPY services/erp-mock/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/erp-mock/src/ ./src/

EXPOSE 8008
CMD ["python", "src/main.py"]
