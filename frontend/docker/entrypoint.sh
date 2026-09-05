#!/bin/sh
# Frontend entrypoint: wait for backend (and optionally the DB), then run CMD.

set -e

TRY_LOOP="${TRY_LOOP:-20}"
BACKEND_HOST="${BACKEND_HOST:-twitter-backend}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
DB_HOST="${DB_HOST:-twitter-db}"
DB_PORT="${DB_PORT:-5432}"
WAIT_FOR_DB="${WAIT_FOR_DB:-1}"

wait_for_port() {
  host="$1"
  port="$2"
  i=0
  until nc -z "$host" "$port" || [ "$i" -ge "$TRY_LOOP" ]; do
    i=$((i + 1))
    echo "waiting for $host:$port ($i/$TRY_LOOP)..."
    sleep 1
  done
  if ! nc -z "$host" "$port"; then
    echo "$host:$port not reachable after $TRY_LOOP tries" >&2
    exit 1
  fi
}

if [ "$WAIT_FOR_DB" = "1" ]; then
  wait_for_port "$DB_HOST" "$DB_PORT"
fi
wait_for_port "$BACKEND_HOST" "$BACKEND_PORT"

cd /app
echo "executing: $*"
exec "$@"
