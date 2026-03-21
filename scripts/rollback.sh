#!/bin/bash
# AgomSaaS One-Click Rollback Script
# Usage: ./scripts/rollback.sh [previous_version]
#
# Description:
#   Performs a quick rollback to a previous version:
#   1. Identifies the previous version (auto-detected if not specified)
#   2. Checks out the previous version
#   3. Installs dependencies
#   4. Optionally rolls back migrations
#   5. Verifies service health
#
# Environment Variables:
#   DEPLOY_TARGET_DIR - Target deployment directory (default: /opt/agomtradepro)
#   VENV_PATH         - Virtual environment path (default: .venv)
#   HEALTH_CHECK_URL  - Health check endpoint (default: http://localhost:8000/api/health/)
#   READY_CHECK_URL   - Readiness check endpoint (default: http://localhost:8000/api/ready/)
#   ROLLBACK_MIGRATIONS - Whether to rollback migrations (default: false)

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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $*"
}

die() {
    log_error "$*"
    exit 1
}

# Configuration
PREVIOUS_VERSION="${1:-}"
DEPLOY_TARGET_DIR="${DEPLOY_TARGET_DIR:-/opt/agomtradepro}"
VENV_PATH="${VENV_PATH:-.venv}"
HEALTH_CHECK_URL="${HEALTH_CHECK_URL:-http://localhost:8000/api/health/}"
READY_CHECK_URL="${READY_CHECK_URL:-http://localhost:8000/api/ready/}"
ROLLBACK_MIGRATIONS="${ROLLBACK_MIGRATIONS:-false}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Banner
echo "==================================="
echo "Starting Rollback"
echo "==================================="

# Change to project root
cd "$PROJECT_ROOT" || die "Cannot change to project root: $PROJECT_ROOT"

# Determine previous version
if [ -z "$PREVIOUS_VERSION" ]; then
    # Try to get the previous tag
    if git describe --tags --abbrev=0 HEAD~1 >/dev/null 2>&1; then
        PREVIOUS_VERSION=$(git describe --tags --abbrev=0 HEAD~1)
    elif [ -L "$DEPLOY_TARGET_DIR/current" ]; then
        # Try to get version from current deployment
        CURRENT_DIR="$(readlink "$DEPLOY_TARGET_DIR/current")"
        if [ -f "$CURRENT_DIR/.release-info" ]; then
            # Get the version from the second-to-last release
            PREVIOUS_VERSION=$(find "$DEPLOY_TARGET_DIR/releases" -name ".release-info" -type f \
                -exec stat -c "%Y %n" {} \; 2>/dev/null | sort -rn | sed -n '2p' | cut -d' ' -f2- | xargs grep -m1 '^version=' | cut -d'=' -f2 || true)
        fi
    fi

    if [ -z "$PREVIOUS_VERSION" ]; then
        # Fallback to previous commit
        PREVIOUS_VERSION="HEAD~1"
    fi
    log_info "Auto-detected previous version: $PREVIOUS_VERSION"
fi

log_info "Rolling back to: $PREVIOUS_VERSION"
echo "==================================="

# Step 1: Verify the target version exists
log_step "[1/5] Verifying target version..."
if ! git rev-parse "$PREVIOUS_VERSION" >/dev/null 2>&1; then
    die "Target version $PREVIOUS_VERSION not found in repository"
fi

# Get current version for reference
CURRENT_VERSION=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
log_info "Current version: $CURRENT_VERSION"
log_info "Target version: $PREVIOUS_VERSION"

# Step 2: Create backup of current deployment
log_step "[2/5] Creating backup of current deployment..."
BACKUP_DIR="$DEPLOY_TARGET_DIR/backups/rollback-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "data/db.sqlite3" ]; then
    cp "data/db.sqlite3" "$BACKUP_DIR/db.sqlite3"
    log_info "Backed up database"
fi

if [ -d "logs" ]; then
    cp -r "logs" "$BACKUP_DIR/"
    log_info "Backed up logs"
fi

# Step 3: Checkout the previous version
log_step "[3/5] Checking out $PREVIOUS_VERSION..."

# Get the commit hash for rollback info
ROLLBACK_COMMIT=$(git rev-parse "$PREVIOUS_VERSION")

# Create release directory for rollback
ROLLBACK_NAME="rollback-$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short "$PREVIOUS_VERSION")"
ROLLBACK_DIR="$DEPLOY_TARGET_DIR/releases/$ROLLBACK_NAME"
mkdir -p "$ROLLBACK_DIR"

# Export the version to a clean directory
git archive "$PREVIOUS_VERSION" | tar -x -C "$ROLLBACK_DIR"
log_info "Extracted $PREVIOUS_VERSION to $ROLLBACK_DIR"

# Restore database to rollback directory
if [ -f "data/db.sqlite3" ]; then
    mkdir -p "$ROLLBACK_DIR/data"
    cp "data/db.sqlite3" "$ROLLBACK_DIR/data/db.sqlite3"
    log_info "Preserved database"
fi

# Copy current configuration
if [ -f "deploy/.env" ]; then
    mkdir -p "$ROLLBACK_DIR/deploy"
    cp "deploy/.env" "$ROLLBACK_DIR/deploy/.env"
    log_info "Copied configuration"
fi

# Step 4: Install dependencies
log_step "[4/5] Installing dependencies..."
cd "$ROLLBACK_DIR"

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

# Step 5: Database migration rollback (optional)
if [ "$ROLLBACK_MIGRATIONS" = "true" ]; then
    log_step "[5/6] Checking for migration rollback..."

    if [ -f "manage.py" ]; then
        # Show migrations that would be rolled back
        log_info "Migrations applied since $PREVIOUS_VERSION:"
        git log --oneline "$PREVIOUS_VERSION..HEAD" -- "*/migrations/*.py" 2>/dev/null || true

        # Attempt to rollback migrations
        log_warn "Automatic migration rollback is risky. Please review and run manually:"
        echo "  python manage.py showmigrations"
        echo "  python manage.py migrate <app> <previous_migration>"
    fi
else
    log_info "[5/6] Skipping migration rollback (set ROLLBACK_MIGRATIONS=true to enable)"
fi

# Step 6: Verify service health
log_step "[6/6] Verifying service health..."

# Give the service a moment to start
sleep 5

# Health check
MAX_RETRIES=5
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f -s "$HEALTH_CHECK_URL" >/dev/null 2>&1; then
        log_info "Health check passed"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        log_warn "Health check failed, retrying ($RETRY_COUNT/$MAX_RETRIES)..."
        sleep 3
    fi
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    log_error "Health check failed after $MAX_RETRIES attempts"
    log_error "Rollback incomplete - service is not healthy!"
    echo ""
    echo "Backup location: $BACKUP_DIR"
    echo "Rollback location: $ROLLBACK_DIR"
    die "Rollback verification failed"
fi

# Readiness check
if ! curl -f -s "$READY_CHECK_URL" >/dev/null 2>&1; then
    log_error "Readiness check failed"
    log_warn "Rollback completed but service may not be fully ready"
fi

# Run smoke tests if script exists and SKIP_SMOKE_TESTS is not set
if [ "${SKIP_SMOKE_TESTS:-false}" != "true" ] && [ -f "$PROJECT_ROOT/scripts/smoke_test.sh" ]; then
    log_info "Running post-rollback smoke tests..."
    if bash "$PROJECT_ROOT/scripts/smoke_test.sh" "$(echo "$HEALTH_CHECK_URL" | sed 's|/api/health/||')"; then
        log_info "Smoke tests passed"
    else
        log_warn "Smoke tests had warnings - review output above"
    fi
else
    log_warn "Smoke tests skipped (script not found or SKIP_SMOKE_TESTS=true)"
fi

# Update current symlink
log_info "Updating current deployment symlink..."
rm -f "$DEPLOY_TARGET_DIR/current"
ln -s "$ROLLBACK_DIR" "$DEPLOY_TARGET_DIR/current"

# Save rollback metadata
cat > "$ROLLBACK_DIR/.release-info" <<EOF
release_name=$ROLLBACK_NAME
version=$PREVIOUS_VERSION
commit=$ROLLBACK_COMMIT
rollback_from=$CURRENT_VERSION
rollback_at=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
rollback_by=$(whoami)
status=rolled_back
backup_dir=$BACKUP_DIR
EOF

# Success message
echo ""
echo "==================================="
echo "Rollback complete!"
echo "==================================="
echo ""
echo "Previous version: $PREVIOUS_VERSION"
echo "Rollback location: $ROLLBACK_DIR"
echo "Backup location: $BACKUP_DIR"
echo ""
echo "Next steps:"
echo "  1. Monitor application logs for any issues"
echo "  2. Verify all features are working correctly"
echo "  3. Check database integrity if migrations were skipped"
echo "  4. Review the failed deployment logs to prevent recurrence"
echo ""
echo "To re-apply migrations (if needed):"
echo "  cd $ROLLBACK_DIR"
echo "  python manage.py migrate"
echo ""
echo "==================================="

# Exit successfully
exit 0
