FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app ./app

RUN mkdir -p /data /bills && chown -R appuser:appuser /app /data /bills

USER appuser

EXPOSE 8000

# Paths default to /data and /bills; override with COST_MGMT_DB_PATH / BILLS_DIR_PATH if needed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
