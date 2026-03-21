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

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agomtradepro}"
export COMPOSE_PROJECT_NAME="$PROJECT_NAME"

BUNDLE=""
TARGET_DIR="/opt/agomtradepro"
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

IS_TTY=0
if [ -t 0 ]; then
  IS_TTY=1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose is required"
fi

compose_vps() {
  $COMPOSE -p "$PROJECT_NAME" -f docker/docker-compose.vps.yml --env-file deploy/.env "$@"
}

detect_conflicting_project() {
  for candidate in docker agomtradepro; do
    [ "$candidate" = "$PROJECT_NAME" ] && continue
    if docker ps -a --format '{{.Names}}' | grep -Eq "^${candidate}-(web|redis|caddy)-1$"; then
      die "Detected compose project '${candidate}' alongside '${PROJECT_NAME}'. Clean old stack first to avoid mixed deployments."
    fi
  done
}

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
  if [ "$IS_TTY" -ne 1 ]; then
    # Non-interactive mode (e.g. SSH exec). Always use default.
    printf '%s' "$default"
    return 0
  fi
  # Print prompt to stderr so command-substitution doesn't capture it.
  printf '%s [%s]: ' "$prompt" "$default" >&2
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

mkdir -p "$TARGET_DIR/releases"

if [ "$ACTION" = "status" ]; then
  cd "$TARGET_DIR/current" || die "Current deployment missing"
  compose_vps ps
  exit 0
fi

if [ "$ACTION" = "logs" ]; then
  cd "$TARGET_DIR/current" || die "Current deployment missing"
  compose_vps logs -f
  exit 0
fi

if [ -z "$BUNDLE" ]; then
  BUNDLE=$(ask "Bundle tar.gz path" "./agomtradepro-vps-bundle.tar.gz")
fi

[ -f "$BUNDLE" ] || die "Bundle not found: $BUNDLE"

release_name=$(basename "$BUNDLE" .tar.gz)
release_dir="$TARGET_DIR/releases/$release_name"

rm -rf "$release_dir"
mkdir -p "$release_dir"

tar -xzf "$BUNDLE" -C "$TARGET_DIR/releases"
if [ ! -d "$release_dir" ]; then
  extracted=$(find "$TARGET_DIR/releases" -maxdepth 1 -type d -name 'agomtradepro-vps-bundle-*' | tail -n 1)
  [ -n "$extracted" ] || die "Could not locate extracted bundle"
  release_dir="$extracted"
fi

log_info "Using release directory: $release_dir"

cd "$release_dir"

if [ -f deploy/manifest.json ] && command -v sha256sum >/dev/null 2>&1; then
  log_info "Verifying checksums"
  # Bundles produced on Windows may contain CRLF JSON; strip trailing CR from parsed fields.
  awk '/"path":|"sha256":/ {gsub(/[",]/, "", $2); if ($1 ~ /path/) p=$2; if ($1 ~ /sha256/) {print $2"  "p}}' deploy/manifest.json | while read -r line; do
    sha=$(printf '%s' "$line" | awk '{print $1}')
    file=$(printf '%s' "$line" | awk '{print $2}')
    sha=$(printf '%s' "$sha" | tr -d '\r')
    file=$(printf '%s' "$file" | tr -d '\r')
    file=$(printf '%s' "$file" | sed 's#\\#/#g')
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

# Heal a broken env file (common mistake: literal "\n" sequences appended).
if grep -q '\\\\n' deploy/.env 2>/dev/null; then
  log_warn "deploy/.env contains literal \\\\n sequences; recreating from template"
  old_secret=$(env_value SECRET_KEY deploy/.env)
  old_domain=$(env_value DOMAIN deploy/.env)
  old_allowed=$(env_value ALLOWED_HOSTS deploy/.env)
  cp deploy/.env.vps.example deploy/.env
  [ -n "$old_secret" ] && sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$old_secret|" deploy/.env
  [ -n "$old_domain" ] && sed -i "s|^DOMAIN=.*|DOMAIN=$old_domain|" deploy/.env
  if [ -n "$old_allowed" ]; then
    if grep -q '^ALLOWED_HOSTS=' deploy/.env; then
      sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$old_allowed|" deploy/.env
    else
      printf '\nALLOWED_HOSTS=%s\n' "$old_allowed" >> deploy/.env
    fi
  fi
fi

domain=$(grep '^DOMAIN=' deploy/.env | cut -d '=' -f2-)
if [ -z "$domain" ]; then
  domain=$(ask "Domain (empty for HTTP only)" "")
fi

secret_key=$(grep '^SECRET_KEY=' deploy/.env | cut -d '=' -f2-)
if [ "$secret_key" = "change-this-to-a-strong-secret" ] || [ -z "$secret_key" ]; then
  if [ "$IS_TTY" -eq 1 ]; then
    secret_key=$(ask "SECRET_KEY" "replace-me")
  else
    # Generate a random secret in non-interactive mode.
    if command -v python3 >/dev/null 2>&1; then
      secret_key=$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || true)
    elif command -v python >/dev/null 2>&1; then
      secret_key=$(python -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || true)
    elif command -v openssl >/dev/null 2>&1; then
      secret_key=$(openssl rand -hex 32 2>/dev/null || true)
    else
      secret_key=$(dd if=/dev/urandom bs=1 count=48 2>/dev/null | tr -dc 'a-zA-Z0-9' | head -c 48 || true)
    fi
    [ -n "$secret_key" ] || secret_key="replace-me"
  fi
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$secret_key|" deploy/.env
fi

if [ -n "$domain" ]; then
  sed -i "s|^DOMAIN=.*|DOMAIN=$domain|" deploy/.env
  site_addr="$domain"
else
  site_addr=":80"
fi

if [ -n "$domain" ]; then
  ssl_redirect="True"
  session_cookie_secure="True"
  csrf_cookie_secure="True"
  secure_hsts_seconds="31536000"
  secure_hsts_include_subdomains="True"
  secure_hsts_preload="True"
else
  ssl_redirect="False"
  session_cookie_secure="False"
  csrf_cookie_secure="False"
  secure_hsts_seconds="0"
  secure_hsts_include_subdomains="False"
  secure_hsts_preload="False"
fi

set_env_kv() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" deploy/.env; then
    sed -i "s|^${key}=.*|${key}=${value}|" deploy/.env
  else
    printf '\n%s=%s\n' "$key" "$value" >> deploy/.env
  fi
}

set_env_kv "SECURE_SSL_REDIRECT" "$ssl_redirect"
set_env_kv "SESSION_COOKIE_SECURE" "$session_cookie_secure"
set_env_kv "CSRF_COOKIE_SECURE" "$csrf_cookie_secure"
set_env_kv "SECURE_HSTS_SECONDS" "$secure_hsts_seconds"
set_env_kv "SECURE_HSTS_INCLUDE_SUBDOMAINS" "$secure_hsts_include_subdomains"
set_env_kv "SECURE_HSTS_PRELOAD" "$secure_hsts_preload"

sed "s|__SITE_ADDRESS__|$site_addr|g" docker/Caddyfile.template > docker/Caddyfile

# ALLOWED_HOSTS is required for IP access; default template only allows localhost.
allowed_hosts=$(grep '^ALLOWED_HOSTS=' deploy/.env | cut -d '=' -f2- || true)
if [ -z "$allowed_hosts" ] || [ "$allowed_hosts" = "127.0.0.1,localhost" ]; then
  default_hosts="127.0.0.1,localhost"
  if [ -n "$domain" ]; then
    default_hosts="$domain,$default_hosts"
  fi
  pub_ip=""
  if command -v curl >/dev/null 2>&1; then
    pub_ip=$(curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true)
  fi
  if [ -n "$pub_ip" ]; then
    default_hosts="$pub_ip,$default_hosts"
  fi
  allowed_hosts=$(ask "ALLOWED_HOSTS (comma-separated)" "$default_hosts")
  if grep -q '^ALLOWED_HOSTS=' deploy/.env; then
    sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$allowed_hosts|" deploy/.env
  else
    printf '\nALLOWED_HOSTS=%s\n' "$allowed_hosts" >> deploy/.env
  fi
fi

port_in_use() {
  p="$1"
  if command -v ss >/dev/null 2>&1; then
    # ss output may contain IPv4/IPv6 entries; match port at end.
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(:|\\])${p}$"
    return $?
  fi
  return 1
}

set_env_kv() {
  k="$1"
  v="$2"
  if grep -q "^${k}=" deploy/.env; then
    sed -i "s|^${k}=.*|${k}=${v}|" deploy/.env
  else
    printf '\n%s=%s\n' "$k" "$v" >> deploy/.env
  fi
}

# If common ports are already occupied on the VPS, auto-adjust Caddy host port mappings.
caddy_http_port=$(env_value CADDY_HTTP_PORT deploy/.env)
[ -n "$caddy_http_port" ] || caddy_http_port="80"
if port_in_use "$caddy_http_port"; then
  fallback_http="8000"
  if [ "$IS_TTY" -eq 1 ]; then
    caddy_http_port=$(ask "CADDY_HTTP_PORT is busy, choose another" "$fallback_http")
  else
    caddy_http_port="$fallback_http"
  fi
  set_env_kv "CADDY_HTTP_PORT" "$caddy_http_port"
fi

caddy_https_port=$(env_value CADDY_HTTPS_PORT deploy/.env)
[ -n "$caddy_https_port" ] || caddy_https_port="443"
if port_in_use "$caddy_https_port"; then
  fallback_https="8443"
  if [ "$IS_TTY" -eq 1 ]; then
    caddy_https_port=$(ask "CADDY_HTTPS_PORT is busy, choose another" "$fallback_https")
  else
    caddy_https_port="$fallback_https"
  fi
  set_env_kv "CADDY_HTTPS_PORT" "$caddy_https_port"
fi

web_image=$(grep '^WEB_IMAGE=' deploy/.env | cut -d '=' -f2-)
if [ -z "$web_image" ] || [ "$web_image" = "agomtradepro-web:latest" ]; then
  manifest_web=""
  if [ -f deploy/manifest.json ]; then
    if command -v python3 >/dev/null 2>&1; then
      manifest_web=$(python3 -c "import json;print(json.load(open('deploy/manifest.json'))['images']['web'])" 2>/dev/null || true)
    elif command -v python >/dev/null 2>&1; then
      manifest_web=$(python -c "import json;print(json.load(open('deploy/manifest.json'))['images']['web'])" 2>/dev/null || true)
    else
      manifest_web=$(awk -F'"' '/"web"[[:space:]]*:/ {print $4; exit}' deploy/manifest.json 2>/dev/null || true)
    fi
  fi
  if [ -n "$manifest_web" ]; then
    sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=$manifest_web|" deploy/.env
  else
    detected=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^agomtradepro-web:' | head -n 1 || true)
    [ -n "$detected" ] && sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=$detected|" deploy/.env
  fi
fi

core_services="redis web caddy"
extra_services=""
if is_true "$(env_value ENABLE_RSSHUB deploy/.env)"; then
  extra_services="$extra_services rsshub"
fi
if is_true "$(env_value ENABLE_CELERY deploy/.env)"; then
  extra_services="$extra_services celery_worker celery_beat"
fi

if [ "$ACTION" = "fresh" ] || [ "$ACTION" = "upgrade" ] || [ "$ACTION" = "restore-only" ]; then
  detect_conflicting_project
fi

if [ "$ACTION" = "fresh" ] || [ "$ACTION" = "upgrade" ]; then
  log_info "Starting stack"
  compose_vps up -d $core_services $extra_services
fi

if [ "$ACTION" = "fresh" ] || [ "$ACTION" = "restore-only" ]; then
  if [ "$ACTION" = "restore-only" ]; then
    log_info "Starting data services for restore"
    compose_vps up -d redis web
  fi

  if [ -f backups/db.sqlite3 ]; then
    log_info "Restoring SQLite database"
    web_cid=$(compose_vps ps -q web)
    [ -n "$web_cid" ] || die "Web container not found"
    docker cp backups/db.sqlite3 "$web_cid:/app/data/db.sqlite3"
    compose_vps restart web
  fi

  if [ -f backups/dump.rdb ]; then
    log_info "Restoring Redis snapshot"
    redis_cid=$(compose_vps ps -q redis)
    [ -n "$redis_cid" ] || die "Redis container not found"
    compose_vps stop redis
    docker cp backups/dump.rdb "$redis_cid:/data/dump.rdb"
    compose_vps start redis
  fi
fi

if [ "$ACTION" = "fresh" ] || [ "$ACTION" = "upgrade" ] || [ "$ACTION" = "restore-only" ]; then
  log_info "Running database migrations"
  tries=0
  while :; do
    if compose_vps exec -T web python manage.py migrate --noinput; then
      break
    fi
    tries=$((tries + 1))
    if [ "$tries" -ge 10 ]; then
      die "Database migration failed after retries"
    fi
    log_warn "Migration failed (web might not be ready yet). Retrying in 5s..."
    sleep 5
  done

  log_info "Running cold-start bootstrap"
  compose_vps exec -T web python manage.py bootstrap_cold_start --with-alpha --alpha-universes "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_UNIVERSES:-csi300}" --alpha-top-n "${AGOMTRADEPRO_BOOTSTRAP_ALPHA_TOP_N:-30}"

  log_info "Ensuring macro periodic tasks"
  if ! compose_vps exec -T web python manage.py setup_macro_daily_sync --hour 8 --minute 5; then
    log_warn "Failed to configure macro periodic tasks automatically"
  fi
fi

mkdir -p "$TARGET_DIR"
rm -rf "$TARGET_DIR/current"
ln -s "$release_dir" "$TARGET_DIR/current"

cd "$TARGET_DIR/current"
compose_vps ps
log_info "Deployment done"
