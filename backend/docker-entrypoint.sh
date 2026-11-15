#!/bin/sh
# Apply database migrations, then start the API.
# The API holds no run state (runs live in Postgres and execute in run workers), so
# API_WORKERS > 1 is safe.
set -eu

echo "Applying database migrations..."
alembic upgrade head

# Only trust X-Forwarded-* from the reverse proxy (client IPs feed the login rate limiter).
# FORWARDED_ALLOW_IPS takes IPs/CIDRs; the default trusts nobody but localhost.
echo "Starting API on 0.0.0.0:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${API_WORKERS:-1}" --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
