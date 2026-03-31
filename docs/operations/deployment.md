# AgomSaaS Deployment Guide

> **Version**: 3.4
> **Last Updated**: 2026-03-04
> **Target**: Operations Team

This guide covers production deployment procedures for AgomSaaS, including canary deployments and rollback procedures.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Architecture](#deployment-architecture)
- [Smoke Testing](#smoke-testing)
- [Canary Deployment](#canary-deployment)
- [Rollback Procedure](#rollback-procedure)
- [Health Check Endpoints](#health-check-endpoints)
- [Troubleshooting](#troubleshooting)
- [Deployment Checklist](#deployment-checklist)

---

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu 20.04+ recommended) or Windows Server 2019+
- **Python**: 3.11+
- **Database**: SQLite (development) or PostgreSQL (production)
- **Redis**: For Celery task queue
- **Web Server**: Nginx, Caddy, or equivalent

### Required Tools

```bash
# Version control
git >= 2.30

# Python environment
python3 >= 3.11
pip >= 23.0
virtualenv or venv

# Web utilities
curl
jq (for JSON parsing in scripts)
```

### Environment Variables

Create a `.env` file in the deployment directory:

```bash
# Core settings
SECRET_KEY=<your-secret-key>
DEBUG=False
ALLOWED_HOSTS=your-domain.com,your-ip

# Database (if using PostgreSQL)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=agomtradepro
DB_USER=agomtradepro
DB_PASSWORD=<your-password>
DB_HOST=localhost
DB_PORT=5432

# Cache
REDIS_HOST=localhost
REDIS_PORT=6379

# Feature flags
ENABLE_CELERY=true
ENABLE_RSSHUB=false
```

---

## Deployment Architecture

### Directory Structure

```
/opt/agomtradepro/
├── releases/           # Versioned releases
│   ├── canary-20260304-103000-v3.4.0/
│   ├── rollback-20260304-120000-v3.3.9/
│   └── archived-20260304-140000-v3.3.8/
├── backups/            # Database backups
│   └── rollback-20260304-120000/
├── archives/           # Old releases
├── current -> releases/canary-20260304-103000-v3.4.0  # Symlink
└── shared/             # Shared resources
```

### Release Lifecycle

```
         ┌─────────────┐
         │  New Tag    │
         └──────┬──────┘
                │
                ▼
         ┌─────────────┐
         │   Canary    │  10% traffic
         └──────┬──────┘
                │
                ├─────────────────┐
                │                 │
                ▼                 ▼
         ┌─────────────┐   ┌─────────────┐
         │  Promote    │   │  Rollback   │
         └──────┬──────┘   └──────┬──────┘
                │                 │
                ▼                 ▼
         ┌─────────────┐   ┌─────────────┐
         │ Production  │   │  Previous   │
         │  100%       │   │  Version    │
         └─────────────┘   └─────────────┘
```

---

## Smoke Testing

### Overview

Smoke tests are critical validation checks performed after deployment to ensure the system is functioning correctly. The `smoke_test.sh` script validates:

1. **Core Health Checks** - Main health and readiness endpoints
2. **Module Health Checks** - All module-specific health endpoints
3. **Critical Page Endpoints** - Dashboard, login pages
4. **Critical API Endpoints** - Regime, Signal, Macro, Asset APIs
5. **Business Read Tests** - Read operations for key business data
6. **Static Resources** - CSS, JS files

### Running Smoke Tests

```bash
# Run smoke tests against default localhost
./scripts/smoke_test.sh

# Run against specific base URL
./scripts/smoke_test.sh http://production-server:8000

# Skip business read tests
SKIP_BUSINESS=true ./scripts/smoke_test.sh

# Verbose output
VERBOSE=true ./scripts/smoke_test.sh
```

### Smoke Test Exit Codes

- `0` - All tests passed
- `1` - Critical test failed
- `2` - Usage error

### Integration with Deployment

Smoke tests are automatically run during canary deployment and rollback:

```bash
# Skip smoke tests during deployment (not recommended)
SKIP_SMOKE_TESTS=true ./scripts/deploy_canary.sh v3.4.0

# Skip smoke tests during rollback (not recommended)
SKIP_SMOKE_TESTS=true ./scripts/rollback.sh
```

### Validation Points

| Check Type | Endpoints | Failure Action |
|------------|-----------|----------------|
| Core Health | `/api/health/`, `/api/ready/` | Abort deployment |
| Module Health | All module health endpoints | Warning only |
| Critical Pages | `/`, `/account/login/` | Warning only |
| Critical APIs | `/api/regime/`, `/api/signal/` | Warning only |
| Business Read | `/api/regime/current/` | Warning only |

---

## Canary Deployment

### Overview

Canary deployment allows you to release a new version to a small percentage of users first, monitoring for issues before full rollout.

### Step-by-Step Procedure

#### 1. Prepare for Deployment

```bash
# Verify the tag exists
git tag -l "v3.4.*"

# Check the tag details
git show v3.4.0 --stat
```

#### 2. Run Canary Deployment

```bash
# Deploy with default 10% traffic
./scripts/deploy_canary.sh v3.4.0

# Deploy with custom percentage
./scripts/deploy_canary.sh v3.4.0 25
```

#### 3. Deployment Output

The script will:

1. **[1/6]** Pull and extract the version
2. **[2/6]** Install Python dependencies
3. **[3/6]** Copy configuration from current deployment
4. **[4/6]** Run Django migrations
5. **[5/6]** Verify health and readiness endpoints
6. **[6/6]** Display traffic shift instructions

#### 4. Configure Load Balancer

**Example: Nginx Upstream Configuration**

```nginx
upstream agomtradepro_backend {
    # Current production (90% traffic)
    server 10.0.1.10:8000 weight=90 max_fails=3 fail_timeout=30s;

    # Canary version (10% traffic)
    server 10.0.1.11:8000 weight=10 max_fails=3 fail_timeout=30s;
}
```

**Example: HAProxy Configuration**

```haproxy
backend agomtradepro_backend
    balance roundrobin
    server production 10.0.1.10:8000 check weight 90
    server canary 10.0.1.11:8000 check weight 10
```

#### 5. Monitor Canary Release

**Key Metrics to Monitor:**

```bash
# Health check
curl http://localhost:8000/api/health/

# Error rate (check logs)
tail -f /var/log/agomtradepro/application.log | grep ERROR

# Response time
curl -w "@curl-format.txt" http://localhost:8000/api/health/
```

**Celery Tasks:**

```bash
# Check task processing
celery -A core inspect active
```

#### 6. Gradual Traffic Increase (Optional)

If the canary is stable, gradually increase traffic:

| Phase | Traffic | Duration |
|-------|---------|----------|
| 1     | 10%     | 1 hour   |
| 2     | 25%     | 2 hours  |
| 3     | 50%     | 4 hours  |
| 4     | 100%    | -        |

---

## Rollback Procedure

### When to Rollback

Rollback should be triggered when:

- Error rate increases by >5%
- Response time increases by >50%
- Health check failures occur
- Database migration errors
- Critical bugs reported by users

### Quick Rollback

```bash
# Rollback to auto-detected previous version
./scripts/rollback.sh

# Rollback to specific version
./scripts/rollback.sh v3.3.9
```

### Rollback Process

The rollback script will:

1. **[1/5]** Verify the target version exists
2. **[2/5]** Create backup of current deployment
3. **[3/5]** Extract the previous version
4. **[4/5]** Install dependencies
5. **[5/5]** Verify service health

### Rollback with Migration Revert

```bash
# Enable migration rollback
export ROLLBACK_MIGRATIONS=true

./scripts/rollback.sh v3.3.9
```

**Warning**: Automatic migration rollback is risky. Review migrations manually first:

```bash
python manage.py showmigrations
python manage.py migrate <app> <previous_migration>
```

### Post-Rollback Verification

```bash
# Check health status
curl http://localhost:8000/api/health/
curl http://localhost:8000/api/ready/

# Verify database
python manage.py check --deploy

# Check recent errors
tail -100 /var/log/agomtradepro/application.log | grep ERROR
```

---

## Health Check Endpoints

### Health Endpoint

**URL**: `/api/health/`

**Method**: `GET`

**Response** (200 OK):
```json
{
    "status": "healthy",
    "version": "3.4.0",
    "timestamp": "2026-03-04T10:30:00Z",
    "components": {
        "database": "healthy",
        "redis": "healthy",
        "celery": "healthy"
    }
}
```

### Readiness Endpoint

**URL**: `/api/ready/`

**Method**: `GET`

**Response** (200 OK):
```json
{
    "ready": true,
    "checks": {
        "database": "passed",
        "migrations": "passed",
        "cache": "passed"
    }
}
```

### Module-Specific Health Checks

| Module | Endpoint |
|--------|----------|
| Audit | `/api/audit/health/` |
| Alpha | `/api/alpha/health/` |
| Filter | `/api/filter/health/` |
| Realtime | `/api/realtime/health/` |
| Regime | `/api/regime/health/` |
| Signal | `/api/signal/health/` |
| Task Monitor | `/api/system/celery/health/` |

---

## Troubleshooting

### Deployment Fails

**Symptom**: Deployment script exits with error

**Solution**:
```bash
# Check script permissions
chmod +x scripts/deploy_canary.sh

# Verify version exists
git ls-remote --tags origin | grep v3.4.0

# Check disk space
df -h /opt/agomtradepro
```

### Health Check Fails

**Symptom**: `curl: (22) The requested URL returned error: 404`

**Solution**:
```bash
# Verify service is running
ps aux | grep python

# Check Django configuration
python manage.py check --deploy

# Verify URL configuration
python manage.py show_urls | grep health
```

### Migration Fails

**Symptom**: `django.db.migrations.exceptions.InconsistentMigrationHistory`

**Solution**:
```bash
# Show current migration state
python manage.py showmigrations

# Fake migration if needed
python manage.py migrate --fake-initial

# Or rollback to specific migration
python manage.py migrate app_name 0001_previous
```

### Database Lock Issues

**Symptom**: `database is locked` (SQLite)

**Solution**:
```bash
# Check for running processes
lsof data/db.sqlite3

# Stop all services
systemctl stop agomtradepro-web
systemctl stop agomtradepro-celery

# Run migration
python manage.py migrate

# Restart services
systemctl start agomtradepro-web
systemctl start agomtradepro-celery
```

### Celery Tasks Not Processing

**Symptom**: Tasks accumulate in queue

**Solution**:
```bash
# Check Celery worker status
celery -A core inspect active

# Restart Celery
systemctl restart agomtradepro-celery

# Check Redis connection
redis-cli ping
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Tag the release with semantic version (e.g., `v3.4.0`)
- [ ] Push tag to remote repository
- [ ] Review changelog for breaking changes
- [ ] Verify all tests pass locally
- [ ] Check database migration compatibility
- [ ] Create database backup
- [ ] Notify stakeholders of deployment window

### During Deployment

- [ ] Run canary deployment script
- [ ] Verify release directory created
- [ ] Check migrations applied successfully
- [ ] Confirm health check passes
- [ ] Run smoke tests (automatic via deploy script)
- [ ] Update load balancer configuration
- [ ] Monitor error rates for 15 minutes

### Post-Deployment

- [ ] Verify core functionality works
- [ ] Run manual smoke tests for validation
- [ ] Check Celery tasks processing
- [ ] Monitor response times
- [ ] Review application logs for errors
- [ ] Verify data integrity
- [ ] Update deployment documentation
- [ ] Create post-deployment report

### Rollback Readiness

- [ ] Previous version tag identified
- [ ] Rollback script tested
- [ ] Backup verified accessible
- [ ] Team notified of rollback procedure

---

## Appendix

### Script Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `deploy_canary.sh` | Deploy new version as canary | `./scripts/deploy_canary.sh <version> [percentage]` |
| `rollback.sh` | Rollback to previous version | `./scripts/rollback.sh [version]` |
| `promote_canary.sh` | Promote canary to production | `./scripts/promote_canary.sh <release_name>` |
| `smoke_test.sh` | Run deployment smoke tests | `./scripts/smoke_test.sh [base_url]` |
| `deploy-on-vps.sh` | Full VPS deployment | `./scripts/deploy-on-vps.sh --bundle <file>` |
| `postdeploy-gate.ps1` | Post-deployment validation (Windows) | `./scripts/postdeploy-gate.ps1 -Port 8000` |

### Configuration Files

| File | Purpose |
|------|---------|
| `deploy/.env` | Environment variables |
| `deploy/.env.vps.example` | Environment template |
| `deploy/manifest.json` | Bundle manifest with checksums |
| `docker/Caddyfile.template` | Caddy reverse proxy config |

### Release Metadata

Each release contains a `.release-info` file:

```bash
release_name=canary-20260304-103000-v3.4.0
version=v3.4.0
percentage=10
deployed_at=2026-03-04 10:30:00 UTC
deployed_by=deploy-user
status=canary
```

---

## Contact

For deployment issues:

- **Ops Team**: ops@agomtradepro.com
- **On-Call**: +86 xxx xxxx xxxx
- **Emergency Channel**: #ops-emergency

---

**Document Version**: 1.0
**Last Modified**: 2026-03-04

