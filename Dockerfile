FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY main.py seed_db.py security.py ./
COPY frontend ./frontend
COPY nexus_enterprise.db ./nexus_enterprise.db

RUN pip install --no-cache-dir .

ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").environ.get(\"PORT\",\"8000\")}/health', timeout=5).status == 200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
