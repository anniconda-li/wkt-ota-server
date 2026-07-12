FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OTA_DATA_DIR=/app/data

WORKDIR /app

RUN addgroup --system --gid 10001 ota \
    && adduser --system --uid 10001 --ingroup ota --home /app ota

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install . && mkdir -p /app/data && chown -R ota:ota /app

USER ota
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["python", "-m", "app"]
