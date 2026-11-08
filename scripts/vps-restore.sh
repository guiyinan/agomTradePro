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
TARGET_DIR_EXPLICIT=0
BACKUP_DIR="/opt/agomtradepro/backups"
DATABASE_FILE=""
DATABASE_SHA256=""
REDIS_FILE=""
CONFIRM_TARGET=""
RESTORE_DATABASE=1
RESTORE_REDIS=1
DATABASE_KIND=""
DATABASE_STAGE=""
STAGED_FILE=""
DATABASE_VERIFIED_SHA256=""
TMP_SQLITE=""
TMP_REDIS=""
ROLLBACK_TEMP=""
ROLLBACK_SIDECAR_TEMP=""
ROLLBACK_FILE=""
ROLLBACK_SIDECAR=""
RESTORE_DESTRUCTIVE_STARTED=0
COMPOSE=""
POSTGRES_DB=""
VERIFIED_SHA256=""

cleanup() {
  exit_status=$?
  trap - 0
  [ -z "$DATABASE_STAGE" ] || rm -f "$DATABASE_STAGE" 2>/dev/null || true
  [ -z "$STAGED_FILE" ] || rm -f "$STAGED_FILE" 2>/dev/null || true
  [ -z "$TMP_SQLITE" ] || rm -f "$TMP_SQLITE" 2>/dev/null || true
  [ -z "$TMP_REDIS" ] || rm -f "$TMP_REDIS" 2>/dev/null || true
  [ -z "$ROLLBACK_TEMP" ] || rm -f "$ROLLBACK_TEMP" 2>/dev/null || true
  [ -z "$ROLLBACK_SIDECAR_TEMP" ] || rm -f "$ROLLBACK_SIDECAR_TEMP" 2>/dev/null || true
  if [ "$exit_status" -ne 0 ] && [ "$RESTORE_DESTRUCTIVE_STARTED" = "1" ]; then
    printf '[ERROR] Restore stopped after target database changes began. Preserve and use the verified rollback archive: %s\n' \
      "${ROLLBACK_FILE:-not available}" >&2
  fi
  exit "$exit_status"
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM

require_value() {
  [ "$#" -ge 2 ] && [ -n "$2" ] || die "Missing value for $1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-dir)
      require_value "$@"
      TARGET_DIR="$2"; TARGET_DIR_EXPLICIT=1; shift 2 ;;
    --backup-dir)
      require_value "$@"
      BACKUP_DIR="$2"; shift 2 ;;
    --database-file|--sqlite-file)
      require_value "$@"
      DATABASE_FILE="$2"; shift 2 ;;
    --database-sha256)
      require_value "$@"
      DATABASE_SHA256="$2"; shift 2 ;;
    --redis-file)
      require_value "$@"
      REDIS_FILE="$2"; shift 2 ;;
    --confirm-target)
      require_value "$@"
      CONFIRM_TARGET="$2"; shift 2 ;;
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
require_cmd sed
require_cmd tail
require_cmd tr
require_cmd ls
require_cmd head

if [ -d "$TARGET_DIR" ]; then
  cd "$TARGET_DIR" || die "Target dir not found: $TARGET_DIR"
else
  die "Target dir not found: $TARGET_DIR"
fi
[ -f docker/docker-compose.vps.yml ] || die "Missing docker/docker-compose.vps.yml under target dir: $TARGET_DIR"
[ -f deploy/.env ] || die "Missing deploy/.env under target dir: $TARGET_DIR"

DATABASE_URL=$(sed -n 's/^DATABASE_URL=//p' deploy/.env | tail -n 1 | tr -d '\r')
case "$DATABASE_URL" in
  postgres://*|postgresql://*) DATABASE_KIND="postgres" ;;
  *) DATABASE_KIND="sqlite" ;;
esac

validate_sha256() {
  sha256_value=$1
  case "$sha256_value" in
    ''|*[!0123456789abcdef]*) return 1 ;;
  esac
  [ "${#sha256_value}" -eq 64 ]
}

find_manifest_sha256() {
  wanted_file=$1
  wanted_name=${wanted_file##*/}
  found_digest=""
  found_count=0
  for manifest_file in "$BACKUP_DIR"/meta/manifest-*.txt; do
    [ -f "$manifest_file" ] || continue
    [ ! -L "$manifest_file" ] || die "Backup manifest must not be a symlink: $manifest_file"
    while IFS= read -r manifest_line || [ -n "$manifest_line" ]; do
      manifest_line=$(printf '%s' "$manifest_line" | tr -d '\r')
      manifest_digest=${manifest_line%% *}
      [ "$manifest_digest" != "$manifest_line" ] || continue
      case "$manifest_digest" in
        ''|*[!0123456789abcdef]*) continue ;;
      esac
      [ "${#manifest_digest}" -eq 64 ] || continue
      manifest_path=${manifest_line#"$manifest_digest"}
      manifest_path=${manifest_path# }
      manifest_path=${manifest_path# }
      manifest_path=${manifest_path#\*}
      case "$manifest_path" in
        "$wanted_name"|*/"$wanted_name")
          found_count=$((found_count + 1))
          found_digest=$manifest_digest
          ;;
      esac
    done < "$manifest_file"
  done
  [ "$found_count" -eq 1 ] || die "Expected one SHA-256 entry for $wanted_file in $BACKUP_DIR/meta/manifest-*.txt; found $found_count"
  VERIFIED_SHA256=$found_digest
}

verify_file_sha256() {
  verified_file=$1
  expected_digest=$2
  if ! validate_sha256 "$expected_digest"; then
    die "Malformed SHA-256 digest for $verified_file; expected 64 lowercase hexadecimal characters"
  fi
  actual_digest_line=$(sha256sum "$verified_file") || die "Unable to calculate SHA-256 for $verified_file"
  actual_digest=${actual_digest_line%% *}
  [ "$actual_digest" = "$expected_digest" ] || die "SHA-256 digest mismatch for $verified_file"
}

prepare_backup_file() {
  input_file=$1
  supplied_digest=$2
  label=$3
  if [ -z "$input_file" ]; then
    die "No $label backup file was selected"
  fi
  [ -f "$input_file" ] || die "$label backup file not found: $input_file"
  [ ! -L "$input_file" ] || die "$label backup file must not be a symlink: $input_file"
  if [ -n "$supplied_digest" ]; then
    if ! validate_sha256 "$supplied_digest"; then
      die "Malformed SHA-256 digest for $input_file; expected 64 lowercase hexadecimal characters"
    fi
    VERIFIED_SHA256=$supplied_digest
  else
    find_manifest_sha256 "$input_file"
  fi
  verify_file_sha256 "$input_file" "$VERIFIED_SHA256"
  mkdir -p "$BACKUP_DIR/database"
  STAGED_FILE=$(mktemp "$BACKUP_DIR/database/.restore-${label}.XXXXXX") || die "Unable to stage $input_file"
  if ! cp "$input_file" "$STAGED_FILE"; then
    rm -f "$STAGED_FILE"
    STAGED_FILE=""
    die "Unable to stage $input_file"
  fi
  if [ -L "$STAGED_FILE" ]; then
    rm -f "$STAGED_FILE"
    STAGED_FILE=""
    die "Staged $label archive unexpectedly became a symlink"
  fi
  verify_file_sha256 "$STAGED_FILE" "$VERIFIED_SHA256"
  chmod 400 "$STAGED_FILE" || die "Unable to make staged $label archive read-only"
}

verify_runtime_target() {
  runtime_database=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres printenv POSTGRES_DB) || die "Unable to read runtime PostgreSQL target identity"
  [ "$runtime_database" = "$CONFIRM_TARGET" ] || \
    die "Runtime PostgreSQL target mismatch: expected '$CONFIRM_TARGET', found '${runtime_database:-empty}'"
}

fail_rollback_preflight() {
  die "Rollback snapshot preflight failed; target database '$CONFIRM_TARGET' was not dropped. Application writers may remain stopped; inspect service status and restart only services that should be running. Review $BACKUP_DIR/database."
}

if [ "$RESTORE_DATABASE" = "1" ]; then
  if [ -z "$DATABASE_FILE" ]; then
    if [ "$DATABASE_KIND" = "postgres" ]; then
      DATABASE_FILE=$(ls -1t "$BACKUP_DIR"/database/postgres-*.dump 2>/dev/null | head -n 1 || true)
    else
      DATABASE_FILE=$(ls -1t "$BACKUP_DIR"/database/db_backup_*.sqlite3.gz "$BACKUP_DIR"/sqlite/db-*.sqlite3.gz 2>/dev/null | head -n 1 || true)
    fi
  fi
  [ -n "$DATABASE_FILE" ] || die "No $DATABASE_KIND backup file found"
  if [ "$DATABASE_KIND" = "postgres" ]; then
    [ "$TARGET_DIR_EXPLICIT" = "1" ] || die "PostgreSQL restore requires explicit --target-dir"
    [ -n "$CONFIRM_TARGET" ] || die "PostgreSQL restore requires --confirm-target with the exact configured database name"
    require_cmd sha256sum
    require_cmd cp
    require_cmd date
    require_cmd mktemp
    require_cmd mv
    require_cmd rm
    require_cmd chmod
    require_cmd mkdir
    POSTGRES_DB=$(sed -n 's/^POSTGRES_DB=//p' deploy/.env | tail -n 1 | tr -d '\r')
    [ -n "$POSTGRES_DB" ] || POSTGRES_DB="agomtradepro"
    url_authority=${DATABASE_URL#*://}
    url_authority=${url_authority%%/*}
    url_authority=${url_authority##*@}
    case "$url_authority" in
      postgres|postgres:5432) ;;
      *) die "Configured DATABASE_URL host must be the Compose PostgreSQL service 'postgres'" ;;
    esac
    case "$POSTGRES_DB" in
      *[!A-Za-z0-9_.-]*|'')
        die "Malformed configured POSTGRES_DB in deploy/.env" ;;
    esac
    case "$POSTGRES_DB" in
      -*) die "Malformed configured POSTGRES_DB in deploy/.env: leading '-' is not supported" ;;
    esac
    [ "${#POSTGRES_DB}" -le 63 ] || die "Malformed configured POSTGRES_DB in deploy/.env"
    url_database=${DATABASE_URL##*/}
    url_database=${url_database%%\?*}
    [ "$url_database" = "$POSTGRES_DB" ] || \
      die "Configured DATABASE_URL target does not match POSTGRES_DB '$POSTGRES_DB'"
    [ "$CONFIRM_TARGET" = "$POSTGRES_DB" ] || \
      die "Target confirmation mismatch: --confirm-target '$CONFIRM_TARGET' does not match configured POSTGRES_DB '$POSTGRES_DB'"
  else
    [ -f "$DATABASE_FILE" ] || die "SQLite backup file not found: $DATABASE_FILE"
  fi
  if [ "$DATABASE_KIND" = "postgres" ]; then
    prepare_backup_file "$DATABASE_FILE" "$DATABASE_SHA256" "database"
    DATABASE_STAGE=$STAGED_FILE
    STAGED_FILE=""
    DATABASE_VERIFIED_SHA256=$VERIFIED_SHA256
  fi
fi

if [ "$RESTORE_REDIS" = "1" ]; then
  if [ -z "$REDIS_FILE" ]; then
    REDIS_FILE=$(ls -1t "$BACKUP_DIR"/redis/dump-*.rdb.gz 2>/dev/null | head -n 1 || true)
  fi
  [ -n "$REDIS_FILE" ] || die "No Redis backup file found"
  [ -f "$REDIS_FILE" ] || die "Redis backup file not found: $REDIS_FILE"
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose is required"
fi
export COMPOSE_PROJECT_NAME=agomtradepro

if [ "$RESTORE_DATABASE" = "1" ] && [ "$DATABASE_KIND" = "postgres" ]; then
  verify_runtime_target
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres pg_restore --list < "$DATABASE_STAGE" >/dev/null; then
    die "PostgreSQL backup archive failed pg_restore --list; target database was not changed"
  fi

  verify_runtime_target
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    stop web celery_worker celery_qlib_worker celery_beat >/dev/null; then
    die "Unable to stop all PostgreSQL writers; target database was not dropped. The stop may be partial; inspect service status and restart only services that should be running."
  fi

  timestamp=$(date +%Y%m%d-%H%M%S)
  ROLLBACK_TEMP=$(mktemp "$BACKUP_DIR/database/.pre-restore-${timestamp}.XXXXXX") || fail_rollback_preflight
  verify_runtime_target
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres sh -eu -c \
    'test "$POSTGRES_DB" = "$1" || { echo "runtime database changed" >&2; exit 91; }; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
    sh "$CONFIRM_TARGET" > "$ROLLBACK_TEMP"; then
    fail_rollback_preflight
  fi
  if [ ! -s "$ROLLBACK_TEMP" ]; then
    fail_rollback_preflight
  fi
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres pg_restore --list < "$ROLLBACK_TEMP" >/dev/null; then
    fail_rollback_preflight
  fi
  rollback_digest_line=$(sha256sum "$ROLLBACK_TEMP") || fail_rollback_preflight
  rollback_digest=${rollback_digest_line%% *}
  validate_sha256 "$rollback_digest" || fail_rollback_preflight
  ROLLBACK_FILE="$BACKUP_DIR/database/pre-restore-${timestamp}-${CONFIRM_TARGET}.dump"
  ROLLBACK_SIDECAR="$ROLLBACK_FILE.sha256"
  [ ! -e "$ROLLBACK_FILE" ] && [ ! -L "$ROLLBACK_FILE" ] && \
    [ ! -e "$ROLLBACK_SIDECAR" ] && [ ! -L "$ROLLBACK_SIDECAR" ] || fail_rollback_preflight
  if ! chmod 600 "$ROLLBACK_TEMP" || ! mv "$ROLLBACK_TEMP" "$ROLLBACK_FILE"; then
    fail_rollback_preflight
  fi
  ROLLBACK_TEMP=""
  ROLLBACK_SIDECAR_TEMP=$(mktemp "$BACKUP_DIR/database/.pre-restore-sha256.XXXXXX") || fail_rollback_preflight
  if ! printf '%s  %s\n' "$rollback_digest" "$ROLLBACK_FILE" > "$ROLLBACK_SIDECAR_TEMP" || \
    ! chmod 600 "$ROLLBACK_SIDECAR_TEMP" || ! mv "$ROLLBACK_SIDECAR_TEMP" "$ROLLBACK_SIDECAR"; then
    fail_rollback_preflight
  fi
  ROLLBACK_SIDECAR_TEMP=""
  rollback_sidecar_line=$(sed -n '1p' "$ROLLBACK_SIDECAR") || fail_rollback_preflight
  rollback_sidecar_digest=${rollback_sidecar_line%% *}
  [ "$rollback_sidecar_digest" = "$rollback_digest" ] || fail_rollback_preflight
  rollback_verified_line=$(sha256sum "$ROLLBACK_FILE") || fail_rollback_preflight
  rollback_verified_digest=${rollback_verified_line%% *}
  [ "$rollback_verified_digest" = "$rollback_digest" ] || fail_rollback_preflight
  [ -s "$ROLLBACK_SIDECAR" ] || fail_rollback_preflight
  log_info "Verified rollback snapshot saved: $ROLLBACK_FILE"
  log_info "Rollback snapshot SHA-256: $rollback_digest"

  verify_file_sha256 "$DATABASE_STAGE" "$DATABASE_VERIFIED_SHA256"
  verify_runtime_target
  RESTORE_DESTRUCTIVE_STARTED=1
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres sh -eu -c \
    'test "$POSTGRES_DB" = "$1" || { echo "runtime database changed" >&2; exit 91; }; exec dropdb --force --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    sh "$CONFIRM_TARGET"; then
    die "Could not drop confirmed target database '$CONFIRM_TARGET'"
  fi
  verify_runtime_target
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres sh -eu -c \
    'test "$POSTGRES_DB" = "$1" || { echo "runtime database changed" >&2; exit 91; }; exec createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    sh "$CONFIRM_TARGET"; then
    die "Could not recreate confirmed target database '$CONFIRM_TARGET'"
  fi
  verify_runtime_target
  verify_file_sha256 "$DATABASE_STAGE" "$DATABASE_VERIFIED_SHA256"
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env \
    exec -T postgres sh -eu -c \
    'test "$POSTGRES_DB" = "$1" || { echo "runtime database changed" >&2; exit 91; }; exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error' \
    sh "$CONFIRM_TARGET" < "$DATABASE_STAGE"; then
    die "Restore failed for confirmed target '$CONFIRM_TARGET'; use rollback archive $ROLLBACK_FILE after review"
  fi
  RESTORE_DESTRUCTIVE_STARTED=0
elif [ "$RESTORE_DATABASE" = "1" ] && [ "$DATABASE_KIND" = "sqlite" ]; then
  log_info "Restoring legacy SQLite from $DATABASE_FILE"
  TMP_SQLITE=$(mktemp) || die "Unable to create temporary SQLite restore file"
  gzip -dc "$DATABASE_FILE" > "$TMP_SQLITE" || die "Unable to decompress SQLite backup: $DATABASE_FILE"
  [ -s "$TMP_SQLITE" ] || die "Decompressed SQLite backup is empty: $DATABASE_FILE"
  docker volume create agomtradepro_sqlite_data >/dev/null
  docker run --rm -i -v agomtradepro_sqlite_data:/dest alpine:3.20 \
    sh -c 'cat > /dest/db.sqlite3 && chown 1000:1000 /dest/db.sqlite3 && chmod 664 /dest/db.sqlite3' \
    < "$TMP_SQLITE"
elif [ "$RESTORE_DATABASE" = "1" ]; then
  die "Unsupported database target type in deploy/.env"
fi

if [ "$RESTORE_REDIS" = "1" ]; then
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d redis >/dev/null; then
    die "Unable to start Redis for restore"
  fi
  log_info "Restoring Redis from $REDIS_FILE"
  TMP_REDIS=$(mktemp) || die "Unable to create temporary Redis restore file"
  gzip -dc "$REDIS_FILE" > "$TMP_REDIS" || die "Unable to decompress Redis backup: $REDIS_FILE"
  redis_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q redis)
  [ -n "$redis_cid" ] || die "redis container not found"
  if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env stop redis >/dev/null; then
    die "Unable to stop Redis before restore"
  fi
  if ! docker cp "$TMP_REDIS" "$redis_cid:/data/dump.rdb"; then
    die "Unable to copy verified Redis backup; Redis remains stopped. Inspect the copy error and restart Redis after review."
  fi
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env start redis >/dev/null
fi

if ! $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d >/dev/null; then
  die "Restore data is in place, but application services did not start; rollback archive: ${ROLLBACK_FILE:-not available}"
fi
log_info "Restore completed"
