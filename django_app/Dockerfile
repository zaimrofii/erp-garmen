# syntax=docker/dockerfile:1
#
# Multi-stage build untuk Django app `garmen`.
#   stage `builder` : compile dependency (butuh build-essential + libpq-dev)
#   stage `runtime` : hanya runtime + virtualenv, tanpa compiler
#
# Build:
#   docker build -t garmen_django ./django_app

# ---------------------------------------------------------------------------
# Stage 1 — builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# virtualenv di /opt/venv supaya gampang dicopy utuh ke stage runtime
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /app/requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DJANGO_SETTINGS_MODULE=config.settings \
    PATH="/opt/venv/bin:$PATH"

# libpq5 = runtime library untuk psycopg3, curl = healthcheck container
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. UID/GID 1000 = user developer di host supaya bind mount
# `./django_app:/app` tetap bisa ditulis (mis. worker & beat).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" appuser \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
               --create-home --shell /bin/bash appuser

COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . /app

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Default untuk production. Di development docker-compose menimpanya dengan
# `python manage.py runserver 0.0.0.0:8000`.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
