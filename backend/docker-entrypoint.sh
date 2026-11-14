#!/bin/sh
# Apply database migrations, then start the API.
# Exactly one worker: active runs (cancel, one-run-per-conversation) live in process
# memory — see docs/ARCHITECTURE.md "Single-process limitation".
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API on 0.0.0.0:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips="*"
