#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$SCRIPT_DIR/shared/common.sh" ]; then
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/shared/common.sh"
elif [ -f "$SCRIPT_DIR/../shared/common.sh" ]; then
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/../shared/common.sh"
else
  log_info() { printf '[INFO] %s\n' "$*"; }
  die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
  require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }
fi

TARGET_DIR="/opt/agomtradepro/current"
BACKUP_DIR="/opt/agomtradepro/backups"
DATABASE_FILE=""
REDIS_FILE=""
RESTORE_DATABASE=1
RESTORE_REDIS=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-dir)
      TARGET_DIR="$2"; shift 2 ;;
    --backup-dir)
      BACKUP_DIR="$2"; shift 2 ;;
    --database-file|--sqlite-file)
      DATABASE_FILE="$2"; shift 2 ;;
    --redis-file)
      REDIS_FILE="$2"; shift 2 ;;
    --no-database|--no-sqlite)
      RESTORE_DATABASE=0; shift ;;
    --no-redis)
      RESTORE_REDIS=0; shift ;;
    *)
      die "Unknown argument: $1" ;;
  esac
done

require_cmd docker
require_cmd gzip

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose is required"
fi

export COMPOSE_PROJECT_NAME=agomtradepro

cd "$TARGET_DIR" || die "Target dir not found: $TARGET_DIR"

DATABASE_URL=$(sed -n 's/^DATABASE_URL=//p' deploy/.env | tail -n 1)
$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d redis >/dev/null

if [ "$RESTORE_DATABASE" = "1" ]; then
  case "$DATABASE_URL" in
    postgres://*|postgresql://*)
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d postgres >/dev/null
      if [ -z "$DATABASE_FILE" ]; then
        DATABASE_FILE=$(ls -1t "$BACKUP_DIR"/database/postgres-*.dump 2>/dev/null | head -n 1 || true)
      fi
      [ -n "$DATABASE_FILE" ] || die "No PostgreSQL backup file found"
      [ -f "$DATABASE_FILE" ] || die "PostgreSQL backup file not found: $DATABASE_FILE"
      log_info "Restoring PostgreSQL from $DATABASE_FILE"
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
        exec -T postgres pg_restore --list < "$DATABASE_FILE" >/dev/null
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
        stop web celery_worker celery_beat >/dev/null 2>&1 || true
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
        exec -T postgres sh -eu <<'SH'
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
  -v dbname="$POSTGRES_DB" \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'dbname' AND pid <> pg_backend_pid();" >/dev/null
dropdb --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"
createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
SH
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
        exec -T postgres sh -eu -c \
        'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' \
        < "$DATABASE_FILE"
      ;;
    *)
      if [ -z "$DATABASE_FILE" ]; then
        DATABASE_FILE=$(ls -1t "$BACKUP_DIR"/database/db_backup_*.sqlite3.gz "$BACKUP_DIR"/sqlite/db-*.sqlite3.gz 2>/dev/null | head -n 1 || true)
      fi
      [ -n "$DATABASE_FILE" ] || die "No SQLite backup file found"
      [ -f "$DATABASE_FILE" ] || die "SQLite backup file not found: $DATABASE_FILE"

      log_info "Restoring legacy SQLite from $DATABASE_FILE"
      tmp_sqlite=$(mktemp)
      gzip -dc "$DATABASE_FILE" > "$tmp_sqlite"
      docker volume create agomtradepro_sqlite_data >/dev/null
      docker run --rm -i -v agomtradepro_sqlite_data:/dest alpine:3.20 \
        sh -c 'cat > /dest/db.sqlite3 && chown 1000:1000 /dest/db.sqlite3 && chmod 664 /dest/db.sqlite3' \
        < "$tmp_sqlite"
      rm -f "$tmp_sqlite"
      ;;
  esac
fi

if [ "$RESTORE_REDIS" = "1" ]; then
  if [ -z "$REDIS_FILE" ]; then
    REDIS_FILE=$(ls -1t "$BACKUP_DIR"/redis/dump-*.rdb.gz 2>/dev/null | head -n 1 || true)
  fi
  [ -n "$REDIS_FILE" ] || die "No Redis backup file found"
  [ -f "$REDIS_FILE" ] || die "Redis backup file not found: $REDIS_FILE"

  log_info "Restoring Redis from $REDIS_FILE"
  tmp_redis=$(mktemp)
  gzip -dc "$REDIS_FILE" > "$tmp_redis"
  redis_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q redis)
  [ -n "$redis_cid" ] || die "redis container not found"
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env stop redis >/dev/null
  docker cp "$tmp_redis" "$redis_cid:/data/dump.rdb"
  rm -f "$tmp_redis"
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env start redis >/dev/null
fi

$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d >/dev/null
log_info "Restore completed"
