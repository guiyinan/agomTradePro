#!/usr/bin/env sh
set -eu
umask 077

TARGET_DIR="${1:-/opt/agomtradepro}"
MARKER_FILE="$TARGET_DIR/.postgres-migration-complete"
FIXTURE_DIR="$TARGET_DIR/backups/database"
COMPOSE_FILE="docker/docker-compose.vps.yml"
ENV_FILE="deploy/.env"

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "[ERROR] docker compose is required" >&2
  exit 1
fi

compose() {
  $COMPOSE -p agomtradepro -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

mkdir -p "$FIXTURE_DIR"
chown 1000:1000 "$FIXTURE_DIR"
chmod 700 "$FIXTURE_DIR"

compose up -d runtime_ns redis postgres

POSTGRES_READY=0
for _attempt in $(seq 1 60); do
  if compose exec -T postgres sh -eu -c \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    POSTGRES_READY=1
    break
  fi
  sleep 2
done
if [ "$POSTGRES_READY" != "1" ]; then
  echo "[ERROR] PostgreSQL did not become ready within 120 seconds" >&2
  compose logs --tail 100 postgres >&2 || true
  exit 1
fi

if [ -f "$MARKER_FILE" ]; then
  echo "[INFO] PostgreSQL migration marker exists; applying schema migrations only"
  compose run --rm --no-deps web python manage.py migrate --noinput
  exit 0
fi

if ! docker run --rm -v agomtradepro_sqlite_data:/source:ro alpine:3.20 \
  test -s /source/db.sqlite3; then
  echo "[INFO] No legacy SQLite database found; initializing PostgreSQL"
  compose run --rm --no-deps web python manage.py migrate --noinput
  printf 'initialized_without_legacy_sqlite=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER_FILE"
  chmod 600 "$MARKER_FILE"
  exit 0
fi

echo "[INFO] Legacy SQLite database found; rebuilding the unmarked PostgreSQL target"
compose exec -T postgres sh -eu <<'SH'
  dropdb --force --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"
  createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
SH

compose run --rm --no-deps web python manage.py migrate --noinput

SOURCE_COUNTS="$FIXTURE_DIR/sqlite-source-counts.json"
FIXTURE="$FIXTURE_DIR/sqlite-to-postgres.json"
TARGET_COUNTS="$FIXTURE_DIR/postgres-target-counts.json"
CONTAINER_SOURCE_COUNTS="/app/backups/database/sqlite-source-counts.json"
CONTAINER_FIXTURE="/app/backups/database/sqlite-to-postgres.json"
CONTAINER_TARGET_COUNTS="/app/backups/database/postgres-target-counts.json"

compose run --rm --no-deps \
  -e DATABASE_URL=sqlite:////app/data/db.sqlite3 \
  -e AGOMTRADEPRO_ALLOW_PRODUCTION_SQLITE_MIGRATION=1 \
  web python - "$CONTAINER_SOURCE_COUNTS" <<'PY'
import json
import sqlite3
import sys

tables = (
    "auth_user",
    "django_celery_beat_periodictask",
    "task_monitor_taskexecutionmodel",
)
connection = sqlite3.connect("/app/data/db.sqlite3")
try:
    available = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    counts = {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in tables
        if table in available
    }
finally:
    connection.close()

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(counts, handle, sort_keys=True)
print(json.dumps(counts, sort_keys=True))
PY

echo "[INFO] Exporting legacy SQLite data"
compose run --rm --no-deps \
  -e DATABASE_URL=sqlite:////app/data/db.sqlite3 \
  -e AGOMTRADEPRO_ALLOW_PRODUCTION_SQLITE_MIGRATION=1 \
  web python manage.py dumpdata \
    --natural-foreign \
    --natural-primary \
    --exclude contenttypes \
    --exclude auth.permission \
    --exclude sessions.session \
    --output "$CONTAINER_FIXTURE"

echo "[INFO] Importing data into PostgreSQL"
compose run --rm --no-deps web python manage.py loaddata "$CONTAINER_FIXTURE"

compose run --rm --no-deps web python - "$CONTAINER_TARGET_COUNTS" <<'PY'
import json
import os
import sys

import django

django.setup()
from django.db import connection

tables = (
    "auth_user",
    "django_celery_beat_periodictask",
    "task_monitor_taskexecutionmodel",
)
available = set(connection.introspection.table_names())
counts = {}
with connection.cursor() as cursor:
    for table in tables:
        if table not in available:
            continue
        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        counts[table] = cursor.fetchone()[0]

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(counts, handle, sort_keys=True)
print(json.dumps(counts, sort_keys=True))
PY

python3 - "$SOURCE_COUNTS" "$TARGET_COUNTS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    source = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    target = json.load(handle)

if not source:
    raise SystemExit("SQLite source verification produced no critical table counts")
if source != target:
    raise SystemExit(
        f"Critical table count mismatch after PostgreSQL migration: "
        f"source={source}, target={target}"
    )
print(f"[INFO] PostgreSQL migration counts verified: {target}")
PY

compose run --rm --no-deps web python manage.py check_encryption_readiness --json
printf 'migrated_from_sqlite=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER_FILE"
chmod 600 "$MARKER_FILE"
rm -f "$FIXTURE" "$SOURCE_COUNTS" "$TARGET_COUNTS"
echo "[INFO] SQLite to PostgreSQL migration completed"
