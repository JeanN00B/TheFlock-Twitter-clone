#!/bin/sh
# Backend entrypoint: wait for Postgres, migrate if alembic is set up, run CMD.
set -e

HOST="${POSTGRES_HOST:-db}"
PORT="${POSTGRES_PORT:-5432}"

i=0
until nc -z "$HOST" "$PORT" || [ "$i" -ge 20 ]; do
  i=$((i + 1))
  echo "waiting for postgres $HOST:$PORT ($i/20)..."
  sleep 1
done
if ! nc -z "$HOST" "$PORT"; then
  echo "postgres $HOST:$PORT not reachable after 20 tries" >&2
  exit 1
fi

if [ -f alembic.ini ] && command -v alembic >/dev/null 2>&1; then
  alembic upgrade head
else
  echo "skipping migrations (no alembic.ini yet)"
fi

exec "$@"
