#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LIB_DIR="$SCRIPT_DIR/../shared"

if [ -f "$SCRIPT_DIR/common.sh" ]; then
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/common.sh"
elif [ -f "$LIB_DIR/common.sh" ]; then
  # shellcheck source=/dev/null
  . "$LIB_DIR/common.sh"
else
  log_info() { printf '[INFO] %s\n' "$*"; }
  log_warn() { printf '[WARN] %s\n' "$*" >&2; }
  die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
  require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }
fi

export COMPOSE_PROJECT_NAME=agomsaaf

BUNDLE=""
TARGET_DIR="/opt/agomsaaf"
ACTION="menu"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle)
      BUNDLE="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --action)
      ACTION="$2"
      shift 2
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

require_cmd docker
require_cmd tar

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose is required"
fi

env_value() {
  key="$1"
  file="$2"
  grep "^${key}=" "$file" | tail -n 1 | cut -d '=' -f2- || true
}

is_true() {
  val=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  [ "$val" = "1" ] || [ "$val" = "true" ] || [ "$val" = "yes" ] || [ "$val" = "on" ]
}

ask() {
  prompt="$1"
  default="$2"
  printf '%s [%s]: ' "$prompt" "$default"
  read -r value
  if [ -z "$value" ]; then
    printf '%s' "$default"
  else
    printf '%s' "$value"
  fi
}

choose_action() {
  cat <<'EOF'
Select action:
1) fresh
2) upgrade
3) restore-only
4) status
5) logs
EOF
  printf 'Enter choice [1]: '
  read -r c
  case "$c" in
    2) ACTION="upgrade" ;;
    3) ACTION="restore-only" ;;
    4) ACTION="status" ;;
    5) ACTION="logs" ;;
    *) ACTION="fresh" ;;
  esac
}

if [ "$ACTION" = "menu" ]; then
  choose_action
fi

mkdir -p "$TARGET_DIR/releases" "$TARGET_DIR/current"

if [ "$ACTION" = "status" ]; then
  cd "$TARGET_DIR/current" || die "Current deployment missing"
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps
  exit 0
fi

if [ "$ACTION" = "logs" ]; then
  cd "$TARGET_DIR/current" || die "Current deployment missing"
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env logs -f
  exit 0
fi

if [ -z "$BUNDLE" ]; then
  BUNDLE=$(ask "Bundle tar.gz path" "./agomsaaf-vps-bundle.tar.gz")
fi

[ -f "$BUNDLE" ] || die "Bundle not found: $BUNDLE"

release_name=$(basename "$BUNDLE" .tar.gz)
release_dir="$TARGET_DIR/releases/$release_name"

rm -rf "$release_dir"
mkdir -p "$release_dir"

tar -xzf "$BUNDLE" -C "$TARGET_DIR/releases"
if [ ! -d "$release_dir" ]; then
  extracted=$(find "$TARGET_DIR/releases" -maxdepth 1 -type d -name 'agomsaaf-vps-bundle-*' | tail -n 1)
  [ -n "$extracted" ] || die "Could not locate extracted bundle"
  release_dir="$extracted"
fi

log_info "Using release directory: $release_dir"

cd "$release_dir"

if [ -f deploy/manifest.json ] && command -v sha256sum >/dev/null 2>&1; then
  log_info "Verifying checksums"
  awk '/"path":|"sha256":/ {gsub(/[",]/, "", $2); if ($1 ~ /path/) p=$2; if ($1 ~ /sha256/) {print $2"  "p}}' deploy/manifest.json | while read -r line; do
    sha=$(printf '%s' "$line" | awk '{print $1}')
    file=$(printf '%s' "$line" | awk '{print $2}')
    [ -f "$file" ] || die "Missing file from manifest: $file"
    real=$(sha256sum "$file" | awk '{print $1}')
    [ "$sha" = "$real" ] || die "Checksum mismatch: $file"
  done
fi

log_info "Loading Docker images"
for image_tar in images/*.tar; do
  docker load -i "$image_tar" >/dev/null
done

if [ ! -f deploy/.env ]; then
  cp deploy/.env.vps.example deploy/.env
fi

domain=$(grep '^DOMAIN=' deploy/.env | cut -d '=' -f2-)
if [ -z "$domain" ]; then
  domain=$(ask "Domain (empty for HTTP only)" "")
fi

secret_key=$(grep '^SECRET_KEY=' deploy/.env | cut -d '=' -f2-)
if [ "$secret_key" = "change-this-to-a-strong-secret" ] || [ -z "$secret_key" ]; then
  secret_key=$(ask "SECRET_KEY" "replace-me")
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$secret_key|" deploy/.env
fi

if [ -n "$domain" ]; then
  sed -i "s|^DOMAIN=.*|DOMAIN=$domain|" deploy/.env
  site_addr="$domain"
else
  site_addr=":80"
fi

sed "s|__SITE_ADDRESS__|$site_addr|g" docker/Caddyfile.template > docker/Caddyfile

web_image=$(grep '^WEB_IMAGE=' deploy/.env | cut -d '=' -f2-)
if [ -z "$web_image" ] || [ "$web_image" = "agomsaaf-web:latest" ]; then
  detected=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^agomsaaf-web:' | head -n 1 || true)
  [ -n "$detected" ] && sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=$detected|" deploy/.env
fi

core_services="redis web caddy"
extra_services=""
if is_true "$(env_value ENABLE_RSSHUB deploy/.env)"; then
  extra_services="$extra_services rsshub"
fi
if is_true "$(env_value ENABLE_CELERY deploy/.env)"; then
  extra_services="$extra_services celery_worker celery_beat"
fi

if [ "$ACTION" = "fresh" ] || [ "$ACTION" = "upgrade" ]; then
  log_info "Starting stack"
  $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d $core_services $extra_services
fi

if [ "$ACTION" = "fresh" ] || [ "$ACTION" = "restore-only" ]; then
  if [ "$ACTION" = "restore-only" ]; then
    log_info "Starting data services for restore"
    $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d redis web
  fi

  if [ -f backups/db.sqlite3 ]; then
    log_info "Restoring SQLite database"
    web_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q web)
    [ -n "$web_cid" ] || die "Web container not found"
    docker cp backups/db.sqlite3 "$web_cid:/app/data/db.sqlite3"
    $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env restart web
  fi

  if [ -f backups/dump.rdb ]; then
    log_info "Restoring Redis snapshot"
    redis_cid=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q redis)
    [ -n "$redis_cid" ] || die "Redis container not found"
    $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env stop redis
    docker cp backups/dump.rdb "$redis_cid:/data/dump.rdb"
    $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env start redis
  fi
fi

rm -rf "$TARGET_DIR/current"
mkdir -p "$TARGET_DIR"
cp -R "$release_dir" "$TARGET_DIR/current"

cd "$TARGET_DIR/current"
$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps
log_info "Deployment done"
