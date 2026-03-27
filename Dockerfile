FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY main.py seed_db.py security.py runtime_store.py config.py ./
COPY logging_config.py circuit_breaker.py exceptions.py warehouse_adapter.py ./
COPY snowflake_adapter.py databricks_adapter.py ./
COPY review_resource_pack.py ./
COPY graph ./graph
COPY policy ./policy
COPY routes ./routes
COPY frontend ./frontend
COPY nexus_enterprise.db ./nexus_enterprise.db

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
