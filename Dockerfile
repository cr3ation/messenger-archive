# ---------- stage 1: build the SPA ----------
FROM node:22-alpine AS web

WORKDIR /app
COPY apps/frontend/package.json apps/frontend/package-lock.json* ./
RUN npm install
COPY apps/frontend/ ./
RUN npm run build

# ---------- stage 2: python runtime serving API + SPA ----------
FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY apps/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY apps/backend/app /srv/app
COPY --from=web /app/dist /srv/static

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv \
    ARCHIVE_DB=/data/archive.db \
    DATA_DIR=/data \
    HOST_DIR=/host \
    STATIC_DIR=/srv/static

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
