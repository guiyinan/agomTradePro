#!/bin/bash
# AgomSaaS Smoke Test Script
# Usage: ./scripts/smoke_test.sh [base_url] [options]
#
# Description:
#   Performs comprehensive smoke tests after deployment:
#   1. Health endpoint validation
#   2. Readiness endpoint validation
#   3. Module-specific health checks
#   4. Business read operations
#   5. Critical API endpoint validation
#
# Exit Codes:
#   0 - All tests passed
#   1 - Critical test failed
#   2 - Usage error

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNED=0

# Configuration
BASE_URL="${1:-http://localhost:8000}"
TIMEOUT="${HTTP_TIMEOUT:-10}"
VERBOSE="${VERBOSE:-false}"
SKIP_BUSINESS="${SKIP_BUSINESS:-false}"
STRICT_WARNINGS="${STRICT_WARNINGS:-true}"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_ok() {
    echo -e "${GREEN}[OK]${NC} $*"
    ((TESTS_PASSED++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
    ((TESTS_WARNED++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $*"
    ((TESTS_FAILED++))
}

log_section() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $*${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
}

# HTTP request wrapper
http_request() {
    local url="$1"
    local expected_status="${2:-200}"
    local method="${3:-GET}"
    local data="${4:-}"

    local curl_opts=(
        -s
        -o /dev/null
        -w "%{http_code}"
        --connect-timeout "$TIMEOUT"
        --max-time "$TIMEOUT"
    )

    if [ "$method" != "GET" ] && [ -n "$data" ]; then
        curl_opts+=(-X "$method" -H "Content-Type: application/json" -d "$data")
    fi

    local status_code
    status_code=$(curl "${curl_opts[@]}" "$url")

    # Check if status code is in expected range (2xx, 3xx)
    if [[ "$status_code" =~ ^[23] ]] || [ "$status_code" = "$expected_status" ]; then
        return 0
    fi
    return 1
}

# HTTP request with JSON output
http_json() {
    local url="$1"

    local json_data
    json_data=$(curl -s --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" "$url")

    echo "$json_data"
}

# Health check test
test_health_endpoint() {
    local url="$1"
    local name="${2:-Health endpoint}"

    log_info "Testing $name: $url"

    if http_request "$url"; then
        local json
        json=$(http_json "$url")

        # Validate JSON structure
        if echo "$json" | jq -e '.status' >/dev/null 2>&1; then
            local status
            status=$(echo "$json" | jq -r '.status')

            if [ "$status" = "healthy" ] || [ "$status" = "ok" ]; then
                log_ok "$name: healthy [$url]"
                return 0
            else
                log_warn "$name: status=$status [$url]"
                return 1
            fi
        else
            log_ok "$name: HTTP OK [$url]"
            return 0
        fi
    else
        log_error "$name: FAILED [$url]"
        return 1
    fi
}

# Critical endpoint test
test_critical_endpoint() {
    local url="$1"
    local name="${2:-Endpoint}"
    local allowed_statuses="${3:-200,301,302,401,403,404}"

    log_info "Testing $name: $url"

    if http_request "$url"; then
        log_ok "$name: accessible [$url]"
        return 0
    else
        # Check if status is in allowed list
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout "$TIMEOUT" "$url")

        if [[ ",$allowed_statuses," == *",$status_code,"* ]]; then
            log_ok "$name: $status_code (allowed) [$url]"
            return 0
        fi

        log_error "$name: HTTP $status_code [$url]"
        return 1
    fi
}

# Business read test
test_business_read() {
    local url="$1"
    local name="${2:-Business read}"

    if [ "$SKIP_BUSINESS" = "true" ]; then
        log_info "Skipping $name (SKIP_BUSINESS=true)"
        return 0
    fi

    log_info "Testing $name: $url"

    local json
    json=$(http_json "$url")

    if [ -n "$json" ]; then
        # Check if it's valid JSON
        if echo "$json" | jq -e '.' >/dev/null 2>&1; then
            log_ok "$name: valid JSON response [$url]"
            if [ "$VERBOSE" = "true" ]; then
                echo "$json" | jq -r 'to_entries[:3] | .[] | "  \(.key): \(.value)"' 2>/dev/null || true
            fi
            return 0
        else
            log_warn "$name: invalid JSON response [$url]"
            return 1
        fi
    else
        log_error "$name: no response [$url]"
        return 1
    fi
}

# Banner
cat <<'EOF'
╔═══════════════════════════════════════════╗
║     AgomSaaS Deployment Smoke Test      ║
║  Health Checks + Business Validation    ║
╔═══════════════════════════════════════════╝
EOF

echo ""
echo "Configuration:"
echo "  Base URL: $BASE_URL"
echo "  Timeout: ${TIMEOUT}s"
echo "  Skip Business: $SKIP_BUSINESS"
echo ""

# Check dependencies
if ! command -v curl >/dev/null 2>&1; then
    log_error "curl is required but not installed"
    exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
    log_warn "jq is not installed, JSON validation will be limited"
fi

# ============================================================================
# Section 1: Core Health Checks
# ============================================================================
log_section "Core Health Checks"

# Main health endpoint
if ! test_health_endpoint "${BASE_URL}/api/health/" "Main health endpoint"; then
    log_error "Main health check failed - aborting smoke test"
    exit 1
fi

# Readiness endpoint
test_health_endpoint "${BASE_URL}/api/ready/" "Readiness endpoint"

# ============================================================================
# Section 2: Module Health Checks
# ============================================================================
log_section "Module Health Checks"

# Audit module
test_health_endpoint "${BASE_URL}/audit/api/health/" "Audit module"

# Alpha module
test_health_endpoint "${BASE_URL}/alpha/health/" "Alpha module"

# Filter module
test_health_endpoint "${BASE_URL}/filter/api/health/" "Filter module"

# Realtime module
test_health_endpoint "${BASE_URL}/realtime/health/" "Realtime module"

# Regime module
test_health_endpoint "${BASE_URL}/regime/health/" "Regime module"

# Signal module
test_health_endpoint "${BASE_URL}/signal/api/health/" "Signal module"

# Task monitor
test_health_endpoint "${BASE_URL}/api/system/celery/health/" "Celery health"

# Account module
test_health_endpoint "${BASE_URL}/account/api/health/" "Account module"

# ============================================================================
# Section 3: Critical Page Endpoints
# ============================================================================
log_section "Critical Page Endpoints"

# Dashboard
test_critical_endpoint "${BASE_URL}/" "Dashboard homepage" "200,302"

# Login page
test_critical_endpoint "${BASE_URL}/account/login/" "Login page" "200,302"

# ============================================================================
# Section 4: Critical API Endpoints
# ============================================================================
log_section "Critical API Endpoints"

# Regime API
test_critical_endpoint "${BASE_URL}/api/regime/" "Regime API list" "200,401"

# Signal API
test_critical_endpoint "${BASE_URL}/api/signal/" "Signal API list" "200,401"

# Macro data API
test_critical_endpoint "${BASE_URL}/api/macro/" "Macro API list" "200,401"

# Asset analysis API
test_critical_endpoint "${BASE_URL}/api/asset-analysis/" "Asset API list" "200,401"

# ============================================================================
# Section 5: Business Read Tests
# ============================================================================
log_section "Business Read Tests"

if [ "$SKIP_BUSINESS" = "false" ]; then
    # Test Regime data read
    test_business_read "${BASE_URL}/api/regime/current/" "Current Regime"

    # Test Signal list
    test_business_read "${BASE_URL}/api/signal/" "Signals list"

    # Test Macro indicators
    test_business_read "${BASE_URL}/api/macro/indicators/" "Macro indicators"

    # Test Asset list
    test_business_read "${BASE_URL}/api/asset-analysis/" "Assets list"
else
    log_info "Business read tests skipped (SKIP_BUSINESS=true)"
fi

# ============================================================================
# Section 6: Static Resources
# ============================================================================
log_section "Static Resources"

# Static files
test_critical_endpoint "${BASE_URL}/static/css/style.css" "Static CSS" "200,404"
test_critical_endpoint "${BASE_URL}/static/js/main.js" "Static JS" "200,404"

# ============================================================================
# Summary
# ============================================================================
log_section "Test Summary"

TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED + TESTS_WARNED))

echo "Total tests: $TOTAL_TESTS"
echo -e "  ${GREEN}Passed:${NC} $TESTS_PASSED"
echo -e "  ${YELLOW}Warnings:${NC} $TESTS_WARNED"
echo -e "  ${RED}Failed:${NC} $TESTS_FAILED"
echo ""

# Determine exit code
if [ "$TESTS_FAILED" -gt 0 ]; then
    log_error "Smoke test FAILED with $TESTS_FAILED error(s)"
    exit 1
elif [ "$TESTS_WARNED" -gt 0 ]; then
    if [ "$STRICT_WARNINGS" = "true" ]; then
        log_error "Smoke test FAILED due to $TESTS_WARNED warning(s) in strict mode"
        exit 1
    fi
    log_warn "Smoke test completed with $TESTS_WARNED warning(s)"
    exit 0
else
    log_ok "Smoke test PASSED - All $TESTS_PASSED tests successful"
    exit 0
fi
