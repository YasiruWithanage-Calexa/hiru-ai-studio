# hiru-api: FastAPI, run on one VM behind Caddy (infra/vm; scripts/deploy_api.ps1). Build from the repo root:
#   docker build -t hiru-api .
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY src/api ./src/api
COPY src/libs ./src/libs
RUN pip install . && useradd --create-home --uid 10001 app

USER app
ENV PORT=8080 ENVIRONMENT=prod
# One worker per container. --proxy-headers so the app sees the real scheme behind the proxy
# (Caddy on the VM; only it can reach this port).
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'
