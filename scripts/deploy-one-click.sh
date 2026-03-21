#!/usr/bin/env sh
# AgomTradePro VPS one-click deploy wrapper.
# Usage: ./scripts/deploy-one-click.sh [bundle-file.tar.gz]
#
# This script intentionally delegates to `scripts/deploy-on-vps.sh` to avoid drift.

set -eu

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*" >&2; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

BUNDLE="${1:-$(ls -t agomtradepro-vps-bundle-*.tar.gz 2>/dev/null | head -n 1 || true)}"
if [ -z "$BUNDLE" ] || [ ! -f "$BUNDLE" ]; then
  log_error "Bundle tar.gz not found. Pass it as the first argument, or put agomtradepro-vps-bundle-*.tar.gz in current dir."
  exit 1
fi

log_info "Deploying bundle: $BUNDLE"

TARGET_DIR="/opt/agomtradepro"
sh "$SCRIPT_DIR/deploy-on-vps.sh" --bundle "$BUNDLE" --target-dir "$TARGET_DIR" --action fresh

ENV_FILE="$TARGET_DIR/current/deploy/.env"
HTTP_PORT="8000"
if [ -f "$ENV_FILE" ]; then
  p=$(grep '^CADDY_HTTP_PORT=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f2- || true)
  [ -n "$p" ] && HTTP_PORT="$p"
fi

VPS_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
[ -n "$VPS_IP" ] || VPS_IP="<your-vps-ip>"

echo ""
log_info "Deployment completed"
echo "Health:"
echo "  http://$VPS_IP:$HTTP_PORT/api/health/"
echo ""
echo "If you see HTTP 400 Bad Request, check `ALLOWED_HOSTS` in $ENV_FILE."
