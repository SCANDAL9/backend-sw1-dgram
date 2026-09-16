#!/bin/sh
set -e

# Run migrations if starting the web server or when no args are provided
if [ "$1" = "uvicorn" ] || [ "$#" -eq 0 ]; then
    echo "==> Running database migrations with Alembic..."
    alembic upgrade head
fi

if [ "$#" -eq 0 ]; then
    echo "==> Starting Uvicorn server with ${WEB_CONCURRENCY:-2} worker(s)..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}"
else
    exec "$@"
fi
