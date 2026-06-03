FROM python:3.12-slim
WORKDIR /app
COPY services/sim-bpp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/sim-bpp/src/ ./src/
# catalog.json ships as a default but is bind-mounted at runtime so it can be
# edited without rebuilding (see docker-compose.yml).
COPY services/sim-bpp/catalog.json ./catalog.json
ENV PYTHONPATH=/app
EXPOSE 3002
CMD ["python", "src/handler.py"]
