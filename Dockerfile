
# ---------- build frontend ----------
# 前端产物与目标架构无关：固定用构建机原生架构跑 npm，避免多架构构建时走 QEMU 模拟
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build -- --outDir /out --emptyOutDir

# ---------- runtime ----------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    FN2TRAKT_DATA_DIR=/data \
    FN2TRAKT_FNTV_DB_PATH=/fntv/trimmedia.db \
    FN2TRAKT_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu curl tzdata passwd \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 fn2trakt \
    && useradd --uid 1000 --gid fn2trakt --create-home --shell /usr/sbin/nologin fn2trakt

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=web /out backend/static
RUN chmod -R a+rX /app/backend
COPY docker/entrypoint.sh /usr/local/bin/fn2trakt-entrypoint
RUN chmod +x /usr/local/bin/fn2trakt-entrypoint

WORKDIR /app/backend
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${FN2TRAKT_PORT:-8080}/api/health" || exit 1

ENTRYPOINT ["/usr/local/bin/fn2trakt-entrypoint"]
