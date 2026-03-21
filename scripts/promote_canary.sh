#!/bin/bash
# AgomSaaS Canary Promotion Script
# Usage: ./scripts/promote_canary.sh <release_name>
#
# Description:
#   Promotes a canary deployment to full production:
#   1. Validates the canary deployment
#   2. Updates the current symlink
#   3. Performs final health checks
#   4. Archives the previous release
#
# Environment Variables:
#   DEPLOY_TARGET_DIR - Target deployment directory (default: /opt/agomtradepro)

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

die() {
    log_error "$*"
    exit 1
}

# Configuration
RELEASE_NAME="${1:-}"
DEPLOY_TARGET_DIR="${DEPLOY_TARGET_DIR:-/opt/agomtradepro}"

# Usage
if [ -z "$RELEASE_NAME" ]; then
    echo "Usage: $0 <release_name>"
    echo ""
    echo "Arguments:"
    echo "  release_name  Name of the canary release to promote"
    echo ""
    echo "Examples:"
    echo "  $0 canary-20260304-103000-v3.4.0"
    exit 1
fi

# Banner
echo "==================================="
echo "Promoting Canary to Production"
echo "==================================="
echo "Release: $RELEASE_NAME"
echo "Target: $DEPLOY_TARGET_DIR"
echo "==================================="

# Step 1: Validate canary release exists
log_info "[1/5] Validating canary release..."
CANARY_DIR="$DEPLOY_TARGET_DIR/releases/$RELEASE_NAME"

if [ ! -d "$CANARY_DIR" ]; then
    die "Canary release not found: $CANARY_DIR"
fi

if [ ! -f "$CANARY_DIR/.release-info" ]; then
    die "Release info not found, may not be a valid release"
fi

# Load release info
source "$CANARY_DIR/.release-info"

if [ "$status" != "canary" ]; then
    log_warn "Release status is '$status', expected 'canary'"
fi

log_info "Release validated: version=$version, percentage=$percentage"

# Step 2: Archive current production
log_info "[2/5] Archiving current production..."
CURRENT_SYMLINK="$DEPLOY_TARGET_DIR/current"

if [ -L "$CURRENT_SYMLINK" ]; then
    CURRENT_DIR="$(readlink "$CURRENT_SYMLINK")"
    ARCHIVE_NAME="archived-$(date +%Y%m%d-%H%M%S)-$(basename "$CURRENT_DIR")"
    ARCHIVE_DIR="$DEPLOY_TARGET_DIR/archives/$ARCHIVE_NAME"

    mkdir -p "$DEPLOY_TARGET_DIR/archives"
    mv "$CURRENT_DIR" "$ARCHIVE_DIR"
    log_info "Archived current production to: $ARCHIVE_DIR"
else
    log_warn "No current symlink found, skipping archive"
fi

# Step 3: Update current symlink
log_info "[3/5] Updating current symlink..."
rm -f "$CURRENT_SYMLINK"
ln -s "$CANARY_DIR" "$CURRENT_SYMLINK"
log_info "Updated current symlink to: $CANARY_DIR"

# Step 4: Update release status
log_info "[4/5] Updating release status..."
sed -i 's/^status=canary/status=production/' "$CANARY_DIR/.release-info"
sed -i 's/^percentage=[0-9]*/percentage=100/' "$CANARY_DIR/.release-info"
echo "promoted_at=$(date -u +"%Y-%m-%d %H:%M:%S UTC")" >> "$CANARY_DIR/.release-info"
log_info "Release status updated to production"

# Step 5: Final health check
log_info "[5/5] Running final health checks..."

cd "$CANARY_DIR"

# Django check
if [ -f "manage.py" ]; then
    if ! python manage.py check --deploy >/dev/null 2>&1; then
        log_error "Django check failed"
        die "Cannot promote release with failed Django check"
    fi
fi

# Health check endpoints
HEALTH_URL="http://localhost:8000/api/health/"
READY_URL="http://localhost:8000/api/ready/"

if curl -f -s "$HEALTH_URL" >/dev/null 2>&1; then
    log_info "Health check passed"
else
    log_warn "Health check failed (service may be starting up)"
fi

if curl -f -s "$READY_URL" >/dev/null 2>&1; then
    log_info "Readiness check passed"
else
    log_warn "Readiness check failed (service may be starting up)"
fi

# Success
echo ""
echo "==================================="
echo "Canary promotion complete!"
echo "==================================="
echo ""
echo "Production release: $RELEASE_NAME"
echo "Version: $version"
echo ""
echo "Traffic status:"
echo "  - Canary: ${percentage}% -> 100%"
echo ""
echo "Next steps:"
echo "  1. Update load balancer to send 100% traffic to new version"
echo "  2. Monitor metrics and logs for the next 24 hours"
echo "  3. Remove old canary configuration from load balancer"
echo "  4. Clean up old archives after 7 days"
echo ""
echo "To rollback if needed:"
echo "  ./scripts/rollback.sh archived-<timestamp>-<previous-release>"
echo ""
echo "==================================="

exit 0
