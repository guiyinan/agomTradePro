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
SQLITE_FILE=""
REDIS_FILE=""
RESTORE_SQLITE=1
RESTORE_REDIS=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-dir)
      TARGET_DIR="$2"; shift 2 ;;
    --backup-dir)
      BACKUP_DIR="$2"; shift 2 ;;
    --sqlite-file)
      SQLITE_FILE="$2"; shift 2 ;;
    --redis-file)
      REDIS_FILE="$2"; shift 2 ;;
    --no-sqlite)
      RESTORE_SQLITE=0; shift ;;
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

$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d redis web >/dev/null

if [ "$RESTORE_SQLITE" = "1" ]; then
  if [ -z "$SQLITE_FILE" ]; then
    SQLITE_FILE=$(ls -1t "$BACKUP_DIR"/sqlite/db-*.sqlite3.gz 2>/dev/null | head -n 1 || true)
  fi
  [ -n "$SQLITE_FILE" ] || die "No SQLite backup file found"
  [ -f "$SQLITE_FILE" ] || die "SQLite backup file not found: $SQLITE_FILE"

  log_info "Restoring SQLite from $SQLITE_FILE"
  tmp_sqlite=$(mktemp)
  gzip -dc "$SQLITE_FILE" > "$tmp_sqlite"
  web_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q web)
  [ -n "$web_cid" ] || die "web container not found"
  docker cp "$tmp_sqlite" "$web_cid:/app/data/db.sqlite3"
  rm -f "$tmp_sqlite"
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env restart web >/dev/null
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

log_info "Restore completed"
