#!/bin/sh
# Apply database migrations, then start the API.
# The API holds no run state (runs live in Postgres and execute in run workers), so
# API_WORKERS > 1 is safe.
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API on 0.0.0.0:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${API_WORKERS:-1}" --proxy-headers --forwarded-allow-ips="*"
