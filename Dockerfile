# syntax=docker/dockerfile:1

# ---- 1. SPA build ---------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. runtime -----------------------------------------------------------
FROM denoland/deno:bin AS deno
FROM ghcr.io/astral-sh/uv:0.9.17 AS uv

FROM python:3.13-slim AS runtime

ARG APP_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="fetcharr" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/rkamran1/fetcharr"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg aria2 ca-certificates tini gosu \
 && rm -rf /var/lib/apt/lists/*

COPY --from=deno /deno /usr/local/bin/deno
COPY --from=uv /uv /usr/local/bin/uv

# yt-dlp in its own venv, so it can be upgraded without touching the app's dependencies.
RUN python -m venv /opt/yt-dlp \
 && /opt/yt-dlp/bin/pip install --no-cache-dir --upgrade pip yt-dlp

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/app ./app
COPY --from=web /web/dist /app/static

RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --no-create-home --home-dir /config --shell /usr/sbin/nologin app \
 && mkdir -p /config

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

ENV PATH="/app/.venv/bin:/opt/yt-dlp/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}

EXPOSE 8000
VOLUME ["/config"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
