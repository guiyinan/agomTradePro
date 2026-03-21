#!/bin/bash
# AgomSaaS Canary Deployment Script
# Usage: ./scripts/deploy_canary.sh <version> [percentage]
#
# Description:
#   Performs a canary deployment by:
#   1. Pulling the specified version tag
#   2. Installing dependencies
#   3. Running database migrations
#   4. Performing health checks
#   5. (Manual) Traffic shifting via load balancer configuration
#
# Environment Variables:
#   DEPLOY_TARGET_DIR - Target deployment directory (default: /opt/agomtradepro)
#   VENV_PATH         - Virtual environment path (default: .venv)
#   HEALTH_CHECK_URL  - Health check endpoint (default: http://localhost:8000/api/health/)
#   READY_CHECK_URL   - Readiness check endpoint (default: http://localhost:8000/api/ready/)

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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
VERSION="${1:-}"
PERCENTAGE="${2:-10}"
DEPLOY_TARGET_DIR="${DEPLOY_TARGET_DIR:-/opt/agomtradepro}"
VENV_PATH="${VENV_PATH:-.venv}"
HEALTH_CHECK_URL="${HEALTH_CHECK_URL:-http://localhost:8000/api/health/}"
READY_CHECK_URL="${READY_CHECK_URL:-http://localhost:8000/api/ready/}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Usage
if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version> [percentage]"
    echo ""
    echo "Arguments:"
    echo "  version     Git tag or commit hash to deploy"
    echo "  percentage  Traffic percentage for canary (default: 10)"
    echo ""
    echo "Examples:"
    echo "  $0 v3.4.0          # Deploy v3.4.0 with 10% traffic"
    echo "  $0 v3.4.0 25       # Deploy v3.4.0 with 25% traffic"
    exit 1
fi

# Validate percentage
if ! [[ "$PERCENTAGE" =~ ^[0-9]+$ ]] || [ "$PERCENTAGE" -lt 1 ] || [ "$PERCENTAGE" -gt 100 ]; then
    die "Percentage must be between 1 and 100"
fi

# Banner
echo "==================================="
echo "Starting Canary Deployment"
echo "==================================="
echo "Version: $VERSION"
echo "Traffic: ${PERCENTAGE}%"
echo "Target: $DEPLOY_TARGET_DIR"
echo "==================================="

# Change to project root
cd "$PROJECT_ROOT" || die "Cannot change to project root: $PROJECT_ROOT"

# Step 1: Pull new version
log_info "[1/6] Pulling version $VERSION..."
if ! git fetch --tags 2>/dev/null; then
    log_warn "git fetch --tags failed, continuing anyway"
fi

# Check if tag/commit exists
if ! git rev-parse "$VERSION" >/dev/null 2>&1; then
    die "Version $VERSION not found in repository"
fi

# Create release directory
RELEASE_NAME="canary-$(date +%Y%m%d-%H%M%S)-${VERSION}"
RELEASE_DIR="$DEPLOY_TARGET_DIR/releases/$RELEASE_NAME"
mkdir -p "$RELEASE_DIR"

# Export the version to a clean directory
git archive "$VERSION" | tar -x -C "$RELEASE_DIR"
log_info "Extracted $VERSION to $RELEASE_DIR"

# Step 2: Install dependencies
log_info "[2/6] Installing dependencies..."
cd "$RELEASE_DIR"

if [ -f "requirements.txt" ]; then
    if [ -n "$VENV_PATH" ]; then
        if [ ! -d "$VENV_PATH" ]; then
            python3 -m venv "$VENV_PATH"
        fi
        # shellcheck source=/dev/null
        source "$VENV_PATH/bin/activate"
    fi
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    log_info "Dependencies installed"
else
    log_warn "requirements.txt not found, skipping dependency installation"
fi

# Step 3: Configuration
log_info "[3/6] Configuring deployment..."

# Copy existing configuration if available
CURRENT_SYMLINK="$DEPLOY_TARGET_DIR/current"
if [ -L "$CURRENT_SYMLINK" ]; then
    CURRENT_DIR="$(readlink "$CURRENT_SYMLINK")"
    if [ -f "$CURRENT_DIR/deploy/.env" ]; then
        mkdir -p deploy
        cp "$CURRENT_DIR/deploy/.env" deploy/.env
        log_info "Copied configuration from current deployment"
    fi
fi

# Step 4: Database migrations
log_info "[4/6] Running database migrations..."

if [ -f "manage.py" ]; then
    # Check for Django project
    if python manage.py check --deploy 2>&1 | grep -q "SystemCheckError"; then
        log_error "Django check failed"
        python manage.py check --deploy
        die "Cannot proceed with deployment"
    fi

    # Run migrations
    if ! python manage.py migrate --noinput; then
        die "Database migration failed"
    fi
    log_info "Migrations completed"
else
    log_warn "manage.py not found, skipping migrations"
fi

# Step 5: Health and smoke tests
log_info "[5/6] Running health checks and smoke tests..."

# Wait for service to be ready (if running)
MAX_WAIT=30
WAIT_COUNT=0
while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if curl -f -s "$HEALTH_CHECK_URL" >/dev/null 2>&1; then
        break
    fi
    WAIT_COUNT=$((WAIT_COUNT + 1))
    sleep 1
done

# Health check
if ! curl -f -s "$HEALTH_CHECK_URL" >/dev/null 2>&1; then
    log_error "Health check failed: $HEALTH_CHECK_URL"
    die "Service is not healthy, aborting deployment"
fi

# Readiness check
if ! curl -f -s "$READY_CHECK_URL" >/dev/null 2>&1; then
    log_error "Readiness check failed: $READY_CHECK_URL"
    die "Service is not ready, aborting deployment"
fi

log_info "Health checks passed"

# Run smoke tests if script exists and SKIP_SMOKE_TESTS is not set
if [ "${SKIP_SMOKE_TESTS:-false}" != "true" ] && [ -f "$PROJECT_ROOT/scripts/smoke_test.sh" ]; then
    log_info "Running smoke tests..."
    if STRICT_WARNINGS=true bash "$PROJECT_ROOT/scripts/smoke_test.sh" "$(echo "$HEALTH_CHECK_URL" | sed 's|/api/health/||')"; then
        log_info "Smoke tests passed"
    else
        die "Smoke tests failed, aborting canary deployment"
    fi
else
    log_warn "Smoke tests skipped (script not found or SKIP_SMOKE_TESTS=true)"
fi

# Step 6: Traffic shift (manual)
log_info "[6/6] Traffic shift instructions..."
echo ""
echo "==================================="
echo "Canary deployment complete!"
echo "==================================="
echo ""
echo "Release directory: $RELEASE_DIR"
echo ""
echo "To shift ${PERCENTAGE}% traffic to the new version:"
echo ""
echo "1. Update your load balancer configuration:"
echo "   - For nginx: Edit upstream weights"
echo "   - For HAProxy: Adjust server weights"
echo "   - For Kubernetes: Update Deployment/Service"
echo ""
echo "2. Example nginx upstream configuration:"
echo ""
cat <<'NGINX_EX'
upstream agomtradepro_backend {
    server current-production:8000 weight=90;  # Old version
    server canary-$VERSION:8000 weight=10;     # New version
}
NGINX_EX
echo ""
echo "3. Monitor the following metrics:"
echo "   - Error rates: $HEALTH_CHECK_URL"
echo "   - Response times"
echo "   - Database query performance"
echo "   - Celery task processing"
echo ""
echo "4. To promote to full production:"
echo "   ./scripts/promote_canary.sh $RELEASE_NAME"
echo ""
echo "5. To rollback if issues are detected:"
echo "   ./scripts/rollback.sh current"
echo ""
echo "==================================="

# Save release metadata
cat > "$RELEASE_DIR/.release-info" <<EOF
release_name=$RELEASE_NAME
version=$VERSION
percentage=$PERCENTAGE
deployed_at=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
deployed_by=$(whoami)
status=canary
EOF

log_info "Release info saved to $RELEASE_DIR/.release-info"

# Exit successfully
exit 0
