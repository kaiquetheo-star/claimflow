#!/bin/sh
# Run Alembic migrations (when DATABASE_URL is set), then start the API.
set -eu

if [ -n "${DATABASE_URL:-}" ]; then
  echo "Running database migrations..."
  alembic upgrade head
else
  echo "DATABASE_URL unset — skipping migrations (in-memory claim store)."
fi

exec "$@"
