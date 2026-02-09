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

TARGET_DIR="/opt/agomsaaf/current"
BACKUP_DIR="/opt/agomsaaf/backups"
KEEP_DAYS=14
DO_SQLITE=1
DO_REDIS=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-dir)
      TARGET_DIR="$2"; shift 2 ;;
    --backup-dir)
      BACKUP_DIR="$2"; shift 2 ;;
    --keep-days)
      KEEP_DAYS="$2"; shift 2 ;;
    --no-sqlite)
      DO_SQLITE=0; shift ;;
    --no-redis)
      DO_REDIS=0; shift ;;
    *)
      die "Unknown argument: $1" ;;
  esac
done

require_cmd docker
require_cmd gzip
require_cmd sha256sum

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose is required"
fi

export COMPOSE_PROJECT_NAME=agomsaaf

cd "$TARGET_DIR" || die "Target dir not found: $TARGET_DIR"
[ -f docker/docker-compose.vps.yml ] || die "Missing docker/docker-compose.vps.yml"
[ -f deploy/.env ] || die "Missing deploy/.env"

mkdir -p "$BACKUP_DIR/sqlite" "$BACKUP_DIR/redis" "$BACKUP_DIR/meta"
TS=$(date +%Y%m%d-%H%M%S)

if [ "$DO_SQLITE" = "1" ]; then
  log_info "Backing up SQLite"
  web_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q web)
  [ -n "$web_cid" ] || die "web container not found"
  sqlite_file="$BACKUP_DIR/sqlite/db-$TS.sqlite3"
  docker cp "$web_cid:/app/data/db.sqlite3" "$sqlite_file"
  gzip -f "$sqlite_file"
fi

if [ "$DO_REDIS" = "1" ]; then
  log_info "Backing up Redis"
  redis_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q redis)
  [ -n "$redis_cid" ] || die "redis container not found"
  docker exec "$redis_cid" redis-cli BGSAVE >/dev/null 2>&1 || true
  sleep 3
  redis_file="$BACKUP_DIR/redis/dump-$TS.rdb"
  docker cp "$redis_cid:/data/dump.rdb" "$redis_file"
  gzip -f "$redis_file"
fi

log_info "Saving metadata"
cp deploy/.env "$BACKUP_DIR/meta/env-$TS"
cp docker/docker-compose.vps.yml "$BACKUP_DIR/meta/compose-$TS.yml"
if [ -f docker/Caddyfile ]; then
  cp docker/Caddyfile "$BACKUP_DIR/meta/Caddyfile-$TS"
fi

manifest="$BACKUP_DIR/meta/manifest-$TS.txt"
: > "$manifest"
find "$BACKUP_DIR" -type f \( -name "*-$TS*" -o -name "env-$TS" -o -name "compose-$TS.yml" -o -name "Caddyfile-$TS" \) | while read -r f; do
  sha256sum "$f" >> "$manifest"
done

if [ "$KEEP_DAYS" -gt 0 ] 2>/dev/null; then
  find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete
fi

log_info "Backup completed"
log_info "SQLite: $BACKUP_DIR/sqlite"
log_info "Redis: $BACKUP_DIR/redis"
log_info "Manifest: $manifest"
