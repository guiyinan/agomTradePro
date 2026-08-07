#!/usr/bin/env sh
set -eu
umask 077

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
KEEP_DAYS=1
DO_DATABASE=1
DO_REDIS=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-dir)
      TARGET_DIR="$2"; shift 2 ;;
    --backup-dir)
      BACKUP_DIR="$2"; shift 2 ;;
    --keep-days)
      KEEP_DAYS="$2"; shift 2 ;;
    --no-database|--no-sqlite)
      DO_DATABASE=0; shift ;;
    --no-redis)
      DO_REDIS=0; shift ;;
    *)
      die "Unknown argument: $1" ;;
  esac
done

require_cmd docker
require_cmd gzip
require_cmd sha256sum
require_cmd python3

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose is required"
fi

export COMPOSE_PROJECT_NAME=agomtradepro

cd "$TARGET_DIR" || die "Target dir not found: $TARGET_DIR"
[ -f docker/docker-compose.vps.yml ] || die "Missing docker/docker-compose.vps.yml"
[ -f deploy/.env ] || die "Missing deploy/.env"

mkdir -p "$BACKUP_DIR/sqlite" "$BACKUP_DIR/redis" "$BACKUP_DIR/meta" "$BACKUP_DIR/database"
chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/sqlite" "$BACKUP_DIR/redis" "$BACKUP_DIR/meta" "$BACKUP_DIR/database"
TS=$(date +%Y%m%d-%H%M%S)

DATABASE_URL=$(sed -n 's/^DATABASE_URL=//p' deploy/.env | tail -n 1)

if [ "$DO_DATABASE" = "1" ]; then
  find "$BACKUP_DIR/database" -maxdepth 1 -type f -name ".*.tmp" -delete
  case "$DATABASE_URL" in
    postgres://*|postgresql://*)
      log_info "Backing up PostgreSQL"
      postgres_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q postgres)
      [ -n "$postgres_cid" ] || die "postgres container not found"
      postgres_temp="$BACKUP_DIR/database/.postgres-$TS.dump.tmp"
      postgres_file="$BACKUP_DIR/database/postgres-$TS.dump"
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
        exec -T postgres sh -eu -c \
        'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
        > "$postgres_temp"
      [ -s "$postgres_temp" ] || die "PostgreSQL backup is empty"
      $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
        exec -T postgres pg_restore --list < "$postgres_temp" >/dev/null
      mv "$postgres_temp" "$postgres_file"
      chmod 600 "$postgres_file"
      ;;
    *)
      log_info "Backing up legacy SQLite"
      web_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q web)
      [ -n "$web_cid" ] || die "web container not found"
      sqlite_file="$BACKUP_DIR/database/db_backup_$TS.sqlite3"
      sqlite_temp="$BACKUP_DIR/database/.db_backup_$TS.sqlite3.tmp"
      gzip_temp="$BACKUP_DIR/database/.db_backup_$TS.sqlite3.gz.tmp"
      container_tmp="/tmp/agomtradepro-predeploy-$TS.sqlite3"
      docker exec -i "$web_cid" python - "$container_tmp" <<'PY'
import sqlite3
import sys

source = sqlite3.connect("/app/data/db.sqlite3", timeout=60)
destination = sqlite3.connect(sys.argv[1])
try:
    source.backup(destination)
    result = destination.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise SystemExit(f"SQLite backup integrity check failed: {result}")
finally:
    destination.close()
    source.close()
PY
      docker cp "$web_cid:$container_tmp" "$sqlite_temp"
      docker exec "$web_cid" rm -f "$container_tmp"
      gzip -c "$sqlite_temp" > "$gzip_temp"
      gzip -t "$gzip_temp"
      mv "$gzip_temp" "$sqlite_file.gz"
      rm -f "$sqlite_temp"
      chmod 600 "$sqlite_file.gz"
      ;;
  esac

  # A verified replacement exists now; keep one completed local database copy.
  find "$BACKUP_DIR/database" -maxdepth 1 -type f ! -name ".*.tmp" \
    -printf '%T@ %p\n' \
    | sort -nr \
    | sed -n '2,$p' \
    | cut -d' ' -f2- \
    | while IFS= read -r superseded_database_backup; do
        [ -n "$superseded_database_backup" ] && rm -f "$superseded_database_backup"
      done
fi

if [ "$DO_REDIS" = "1" ]; then
  log_info "Backing up Redis"
  redis_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q redis)
  [ -n "$redis_cid" ] || die "redis container not found"
  before_save=$(docker exec "$redis_cid" redis-cli LASTSAVE)
  docker exec "$redis_cid" redis-cli BGSAVE >/dev/null
  redis_saved=0
  for _attempt in $(seq 1 30); do
    after_save=$(docker exec "$redis_cid" redis-cli LASTSAVE)
    if [ "$after_save" -gt "$before_save" ]; then
      redis_saved=1
      break
    fi
    sleep 1
  done
  [ "$redis_saved" = "1" ] || die "Redis BGSAVE did not complete within 30 seconds"
  redis_file="$BACKUP_DIR/redis/dump-$TS.rdb"
  docker cp "$redis_cid:/data/dump.rdb" "$redis_file"
  gzip -f "$redis_file"
  gzip -t "$redis_file.gz"
  chmod 600 "$redis_file.gz"
fi

log_info "Saving metadata"
cp deploy/.env "$BACKUP_DIR/meta/env-$TS"
cp docker/docker-compose.vps.yml "$BACKUP_DIR/meta/compose-$TS.yml"
if [ -f docker/Caddyfile ]; then
  cp docker/Caddyfile "$BACKUP_DIR/meta/Caddyfile-$TS"
fi
secrets_file="$(dirname "$BACKUP_DIR")/secrets.env"
if [ -f "$secrets_file" ]; then
  cp "$secrets_file" "$BACKUP_DIR/meta/secrets-$TS.env"
fi
chmod 600 "$BACKUP_DIR/meta"/* 2>/dev/null || true

manifest="$BACKUP_DIR/meta/manifest-$TS.txt"
: > "$manifest"
find "$BACKUP_DIR" -type f -name "*$TS*" ! -path "$manifest" | while read -r f; do
  sha256sum "$f" >> "$manifest"
done
chmod 600 "$manifest"

if [ "$KEEP_DAYS" -gt 0 ] 2>/dev/null; then
  find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete
fi

log_info "Backup completed"
log_info "Database: $BACKUP_DIR/database"
log_info "Redis: $BACKUP_DIR/redis"
log_info "Manifest: $manifest"
