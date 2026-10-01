#!/usr/bin/env sh
set -eu
umask 077

TARGET_DIR="${1:-/opt/agomtradepro}"
RELEASE_DIR="${2:-$TARGET_DIR/current}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agomtradepro}"
MARKER_FILE="$TARGET_DIR/.postgres-migration-complete"
FIXTURE_DIR="$TARGET_DIR/backups/database"
COMPOSE_FILE="$RELEASE_DIR/docker/docker-compose.vps.yml"
ENV_FILE="$RELEASE_DIR/deploy/.env"
STATEMENT_LOGGING_STATE="$TARGET_DIR/.postgres-statement-logging-state"

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "[ERROR] docker compose is required" >&2
  exit 1
fi

compose() {
  $COMPOSE -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

statement_logging_psql() {
  mode="$1"
  if [ "$mode" = "query" ]; then
    compose exec -T postgres sh -eu -c \
      'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    return
  fi
  [ "$mode" = "execute" ] || return 2
  compose exec -T postgres sh -eu -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

. "$RELEASE_DIR/scripts/postgres_statement_logging_window.sh"

python3 "$RELEASE_DIR/scripts/ensure_vps_postgres_role_env.py" \
  --env-file "$ENV_FILE" \
  --secrets-file "$TARGET_DIR/secrets.env"

for runtime_service in web celery_worker celery_qlib_worker celery_beat terminal_agent_worker; do
  runtime_container="$(compose ps -q "$runtime_service")"
  if [ -n "$runtime_container" ]; then
    echo "[ERROR] Runtime service $runtime_service is still running; stop all database writers before migration" >&2
    exit 1
  fi
done

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

trap cleanup_statement_logging_window EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
enter_statement_logging_window

if [ -f "$MARKER_FILE" ]; then
  echo "[INFO] PostgreSQL migration marker exists; applying schema migrations only"
  bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"
  compose run --rm --no-deps migrator python -m scripts.manage_vps_migrations migrate --noinput
  bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"
  restore_statement_logging
  trap - EXIT HUP INT TERM
  exit 0
fi

if ! docker run --rm -v "${COMPOSE_PROJECT_NAME}_sqlite_data:/source:ro" alpine:3.20 \
  test -s /source/db.sqlite3; then
  echo "[INFO] No legacy SQLite database found; initializing PostgreSQL"
  bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"
  compose run --rm --no-deps migrator python -m scripts.manage_vps_migrations migrate --noinput
  bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"
  restore_statement_logging
  trap - EXIT HUP INT TERM
  printf 'initialized_without_legacy_sqlite=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER_FILE"
  chmod 600 "$MARKER_FILE"
  exit 0
fi

echo "[INFO] Legacy SQLite database found; rebuilding the unmarked PostgreSQL target"
compose exec -T postgres sh -eu <<'SH'
  dropdb --force --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"
createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
SH

bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"
compose run --rm --no-deps migrator python -m scripts.manage_vps_migrations migrate --noinput
bash "$RELEASE_DIR/scripts/bootstrap_vps_postgres_roles.sh" "$TARGET_DIR" --apply "$RELEASE_DIR"

SOURCE_COUNTS="$FIXTURE_DIR/sqlite-source-counts.json"
FIXTURE="$FIXTURE_DIR/sqlite-to-postgres.jsonl"
TARGET_COUNTS="$FIXTURE_DIR/postgres-target-counts.json"
RECONCILIATION_REPORT="$FIXTURE_DIR/sqlite-snapshot-reconciliation.json"
CONTAINER_SOURCE_COUNTS="/app/backups/database/sqlite-source-counts.json"
CONTAINER_FIXTURE="/app/backups/database/sqlite-to-postgres.jsonl"
CONTAINER_TARGET_COUNTS="/app/backups/database/postgres-target-counts.json"

compose run --rm --no-deps \
  -e PYTHONUTF8=1 \
  -e DATABASE_URL=sqlite:////app/data/db.sqlite3 \
  -e AGOMTRADEPRO_DATABASE_ROLE= \
  -e AGOMTRADEPRO_ALLOW_PRODUCTION_SQLITE_MIGRATION=1 \
  web python -m scripts.sqlite_snapshot_contract capture \
    --output "$CONTAINER_SOURCE_COUNTS"

echo "[INFO] Exporting legacy SQLite data"
compose run --rm --no-deps \
  -e PYTHONUTF8=1 \
  -e DATABASE_URL=sqlite:////app/data/db.sqlite3 \
  -e AGOMTRADEPRO_DATABASE_ROLE= \
  -e AGOMTRADEPRO_ALLOW_PRODUCTION_SQLITE_MIGRATION=1 \
  web python manage.py dumpdata \
    --format jsonl \
    --natural-foreign \
    --natural-primary \
    --exclude contenttypes \
    --exclude auth.permission \
    --exclude sessions.session \
    --output "$CONTAINER_FIXTURE"

echo "[INFO] Clearing migration seed data before importing the SQLite snapshot"
compose run --rm --no-deps migrator python -m scripts.manage_vps_migrations flush --noinput

echo "[INFO] Importing data into PostgreSQL"
compose run --rm --no-deps \
  -e PYTHONUTF8=1 \
  -e AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS=1 \
  migrator python -m scripts.manage_vps_migrations loaddata "$CONTAINER_FIXTURE"

compose run --rm --no-deps web python -m scripts.sqlite_snapshot_contract capture \
  --output "$CONTAINER_TARGET_COUNTS"

python3 "$RELEASE_DIR/scripts/sqlite_snapshot_contract.py" verify \
  --source "$SOURCE_COUNTS" \
  --target "$TARGET_COUNTS" \
  --fixture "$FIXTURE" \
  --report "$RECONCILIATION_REPORT"

compose run --rm --no-deps web python manage.py check_encryption_readiness --json
restore_statement_logging
trap - EXIT HUP INT TERM
printf 'migrated_from_sqlite=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER_FILE"
chmod 600 "$MARKER_FILE"
rm -f "$FIXTURE" "$SOURCE_COUNTS" "$TARGET_COUNTS" "$RECONCILIATION_REPORT"
echo "[INFO] SQLite to PostgreSQL migration completed"
