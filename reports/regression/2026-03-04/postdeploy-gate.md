# Post-Deploy Gate Verification Report

**Date**: 2026-03-04
**Task**: WP-1 - Container health check unification + PostDeploy Gate
**Status**: COMPLETED

## Summary

Unified all health check endpoints from `/health/` to `/api/health/` across the codebase and created a Post-Deploy Gate script for deployment verification.

## Changes Made

### 1. Docker Files

| File | Line | Change |
|------|------|--------|
| `Dockerfile` | 57 | `CMD curl -f http://localhost:8000/health/` **->** `CMD curl -f http://localhost:8000/api/health/` |
| `docker/Dockerfile.prod` | 63 | `CMD curl -fsS http://127.0.0.1:8000/health/` **->** `CMD curl -fsS http://127.0.0.1:8000/api/health/` |
| `docker/Dockerfile.prod.mirror` | 51 | `CMD curl -fsS http://127.0.0.1:8000/health/` **->** `CMD curl -fsS http://127.0.0.1:8000/api/health/` |

### 2. Docker Compose

| File | Lines | Change |
|------|-------|--------|
| `docker-compose.yml` | 66 | `test: ["CMD", "curl", "-f", "http://localhost:8000/health/"]` **->** `test: ["CMD", "curl", "-f", "http://localhost:8000/api/health/"]` |
| `docker-compose.yml` | 134 | `test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health/"]` **->** `test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/api/health/"]` |

### 3. Deployment Scripts

| File | Line | Change |
|------|------|--------|
| `scripts/deploy-one-click.sh` | 44 | `http://$VPS_IP:$HTTP_PORT/health/` **->** `http://$VPS_IP:$HTTP_PORT/api/health/` |
| `scripts/deploy-bundle-to-vps.py` | 254 | `curl -fsS --max-time 5 http://127.0.0.1:{http_port}/health/` **->** `curl -fsS --max-time 5 http://127.0.0.1:{http_port}/api/health/` |

### 4. Development Scripts

| File | Lines | Change |
|------|-------|--------|
| `scripts/dev-smoke.ps1` | 72 | `"http://127.0.0.1:$Port/health/"` **->** `"http://127.0.0.1:$Port/api/health/"` |
| `scripts/e2e_debug_log_api.ps1` | 22, 76, 95, 105, 122 | All `/health/` occurrences **->** `/api/health/` |

### 5. Test Files

| File | Lines | Change |
|------|-------|--------|
| `tests/test_all_pages.py` | 34, 350, 373 | `'/health/'` **->** `'/api/health/'` |
| `scripts/uat_browser_test.py` | 206 | `f"{self.base_url}/health/"` **->** `f"{self.base_url}/api/health/"` |

## New Files Created

### 1. `scripts/postdeploy-gate.ps1`

Post-deployment verification script with strict gate capabilities:

- **Main health endpoint check**: Validates `/api/health/`
- **Database health check**: Validates `/api/health/db/` (404 treated as optional)
- **Business path check (required by default)**: 1 read + 1 write + 1 readback
- **Celery check (required by default)**: trigger task + poll status to success
- **Alert chain check (required by default)**: trigger alert + verify marker in observation endpoint
- **Strict mode defaults**: business/celery/alert checks are enabled unless `-Skip...` is explicitly set
- **Exit codes**: Returns 0 on success, 1 on failure
- **Verbose mode**: Optional detailed logging

**Usage**:
```powershell
.\scripts\postdeploy-gate.ps1 `
  -BusinessReadUrl "http://127.0.0.1:8000/api/..." `
  -BusinessWriteUrl "http://127.0.0.1:8000/api/..." `
  -BusinessWriteMethod "POST" `
  -BusinessWriteBody '{"name":"postdeploy-smoke"}' `
  -BusinessReadbackUrlTemplate "http://127.0.0.1:8000/api/.../{id}/" `
  -CeleryTriggerUrl "http://127.0.0.1:8000/api/.../run/" `
  -CeleryStatusUrlTemplate "http://127.0.0.1:8000/api/celery/task-status/{task_id}/" `
  -AlertTriggerUrl "http://127.0.0.1:8000/api/.../alert-test/" `
  -AlertVerifyUrl "http://127.0.0.1:8000/api/debug/server-logs/export/" `
  -AlertVerifyContains "ALERT_TEST_MARKER"
```

### 2. `reports/regression/2026-03-04/postdeploy-gate.md`

This verification report.

## Verification Steps

To verify the changes:

1. **Build and run containers**:
   ```bash
   docker-compose build
   docker-compose up -d
   ```

2. **Check health status**:
   ```bash
   docker-compose ps
   curl http://localhost:8000/api/health/
   ```

3. **Run Post-Deploy Gate**:
   ```powershell
   .\scripts\postdeploy-gate.ps1
   ```

4. **Run smoke tests**:
   ```powershell
   .\scripts\dev-smoke.ps1
   ```

## Files Modified Summary

| Category | Count |
|----------|-------|
| Docker files | 3 |
| Docker Compose | 2 locations |
| Deployment scripts | 2 |
| Development scripts | 2 |
| Test files | 2 |
| **Total** | **11 files** |

## Acceptance Criteria

- [x] All `/health/` references changed to `/api/health/` in the listed files
- [x] PostDeploy Gate script supports health + read/write/readback + celery + alert chain
- [x] Report documents all changes made

## Notes

- The change from `/health/` to `/api/health/` aligns with the API routing convention
- All container health checks now point to the unified API endpoint
- The Post-Deploy Gate script can be integrated into CI/CD pipelines
- Backward compatibility: Old `/health/` endpoint may still exist but is no longer referenced in health checks

## Related Tasks

- WP-1: Container health check unification + PostDeploy Gate (this task)
