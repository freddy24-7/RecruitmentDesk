#!/bin/sh
# Start command of the container: migrations first, then the app.
set -eu

alembic upgrade head

# --no-access-log: uvicorn's access log holds visitors' IP addresses. The app
# logs its own events with ids and counts only (CLAUDE.md rule 12).
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --no-access-log \
    --no-server-header
