# AgomTradePro Operations Runbook

## 1. First Deployment Checklist

### Prerequisites
- PostgreSQL 15+ running and accessible
- Redis 7+ running and accessible
- `.env` file configured (copy from `.env.example`)
- Docker images built: `docker compose -f docker/docker-compose.vps.yml build`

### Deployment Steps

```bash
# 1. Apply database migrations
python manage.py migrate

# 2. Create superuser
python manage.py createsuperuser

# 3. Initialize all configuration data
python manage.py init_all

# 4. Verify health
python manage.py healthcheck --json

# 5. Warm up caches
python manage.py warmup_cache

# 6. Collect static files (production)
python manage.py collectstatic --noinput

# 7. Start services
docker compose -f docker/docker-compose.vps.yml up -d
```

The production web entrypoint runs lightweight cold-start configuration by default, but does not run Alpha/Qlib bootstrap unless `AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=1` is explicitly set. Keep the default disabled on memory-constrained VPS hosts; run Alpha bootstrap as a separate maintenance task when needed.

The VPS compose stack persists the application `var` directory in the `var_data` Docker volume. Keep readiness evidence under `var/readiness-evidence` so web, Celery worker, and Celery beat share the same evidence window across redeploys.

The production app containers share the `web` PID namespace so `show_personal_readiness_status --strict-monitor --require-local-scheduler-runtime` can verify both Celery worker and beat processes from the web container.

### Post-Deployment Verification

```bash
# Liveness check (lightweight)
curl http://localhost:8000/api/health/

# Readiness check (full: DB, Redis, Celery, critical data)
curl http://localhost:8000/api/ready/

# CLI health check
python manage.py healthcheck

# Verify Celery workers
celery -A core inspect active
celery -A core inspect ping
```

---

## 2. Daily Data Sync Verification

### Automated Tasks (Celery Beat)

| Time | Task | Description |
|------|------|-------------|
| 08:00 | `sync_and_calculate_regime` | Daily macro data sync + regime calculation |
| 15:35 | `decision-quote-pre-readiness-refresh` | Refresh decision-grade quotes before personal readiness evidence |
| 16:10 | `personal-readiness-daily-evidence` | Generate scheduler-sourced personal readiness evidence |
| 16:30 | `sync_high_frequency_bonds` | Bond market data sync |
| 16:35 | `sync_high_frequency_commodities` | Commodity data sync |
| 17:00 | `generate_daily_regime_signal` | Generate daily regime signal |
| 17:05 | `recalculate_regime_with_daily_signal` | Recalculate regime |
| 17:30 | `qlib_daily_inference` | Alpha AI inference |
| Fri 17:30 | `dashboard-auto-advisor-weekly-report` | Persist personal auto-advisor weekly reports |

### Manual Verification

Daily browser check:

- Use `/ops/task-monitor/readiness/` for the lightweight 20-trading-day readiness monitor. This page loads the monitor payload, readiness schedule controls, active-stock data coverage, and MCP/TUI/Terminal operation-surface coverage, so it is the preferred daily VPS entry on memory-constrained hosts.
- The production data coverage panel must be interpreted in two layers: `universe_quality` proves the active A-share master universe is broad enough, while `domains.price/valuation/financial` prove facts exist for that universe. A 300-stock universe is a narrow index pool, not production all-market coverage.
- Use `/data-center/universe/` to configure the production coverage universe and thresholds. The backing APIs are `GET/PUT /api/data-center/production-coverage/universe/` for the DB-backed universe config and `GET /api/data-center/production-coverage/summary/` for the current coverage summary.
- Use `/settings/config-center/qlib/` to configure Alpha/Qlib model universes for scoring, data builds, and training. The backing APIs and MCP tools are `list_alpha_universes`, `save_alpha_universe`, and `get_alpha_universe_members`; TUI exposes the same actions under `api-library.config-center`. Keep this separate from the Data Center production coverage universe: Data Center defines readiness coverage, Alpha universe defines the investable/model universe.
- Recommended naming: keep the production coverage ID as `active_a_share`, and use an explicit model-scope ID such as `model_all_a_share`, `model_star_market`, or `model_growth_boards` for Alpha/Qlib. If both should use the same filter, configure that filter twice intentionally instead of relying on implicit coupling.
- The "严格运行态" refresh performs the full local scheduler runtime probe and is cached for 60 seconds to avoid repeated heavy checks on the VPS.
- Use `/ops/task-monitor/` only when you need the full PeriodicTask catalog, Celery inspect output, and recent failure list.

```bash
# Refresh active A-share master data before judging production coverage
python manage.py sync_a_share_universe --deactivate-missing --json

# Personal readiness monitor, read-only; does not generate evidence
powershell -ExecutionPolicy Bypass -File scripts/check-personal-readiness-monitor.ps1 -SummaryOnly

# Final acceptance gate, still expected to fail until the 20-trading-day window is complete
powershell -ExecutionPolicy Bypass -File scripts/check-personal-readiness-monitor.ps1 -StrictAcceptance

# Read-only acceptance window details and evidence diagnosis
python manage.py validate_personal_readiness_window --json
python manage.py inspect_personal_readiness_evidence --target-date <latest_closed_trade_date> --json

# Check data freshness
python manage.py shell -c "
from apps.macro.infrastructure.models import MacroDataModel
from django.utils import timezone
from datetime import timedelta

cutoff = timezone.now() - timedelta(days=2)
stale = MacroDataModel.objects.filter(updated_at__lt=cutoff).values_list('indicator__code', flat=True).distinct()
print(f'Stale indicators: {list(stale)[:10]}')
"

# Check regime state
python manage.py shell -c "
from apps.regime.infrastructure.models import RegimeStateModel
latest = RegimeStateModel.objects.order_by('-calc_date').first()
print(f'Latest regime: {latest.regime} on {latest.calc_date}')
"

# Trigger a Pulse rebuild with upstream macro refresh
python manage.py shell -c "
from apps.pulse.application.use_cases import CalculatePulseUseCase
snapshot = CalculatePulseUseCase().execute()
print(snapshot.composite_score if snapshot else 'pulse refresh failed')
"
```

- During the scheduler-clean trial, let Celery beat create `personal-readiness-daily-evidence`; manual `run_personal_readiness_daily` is for diagnosis or explicit backfill and does not advance the scheduler-clean suffix.
- 如果当前 Regime 链路只能返回 `Unknown`，Pulse 重建会直接失败并保留最近有效快照，避免用未知象限覆盖现有战术上下文。

---

## 3. Celery Task Troubleshooting

### Common Issues

#### Workers Not Processing Tasks
```bash
# Check worker status
celery -A core inspect active
celery -A core inspect reserved

# Check queue depth
celery -A core inspect active_queues

# Restart workers
docker compose -f docker/docker-compose.vps.yml restart celery_worker

# Check logs
docker compose -f docker/docker-compose.vps.yml logs --tail=100 celery_worker
```

#### Tasks Stuck in Retry Loop
```bash
# Purge a specific queue
celery -A core purge -Q celery

# Revoke stuck tasks
celery -A core control revoke <task_id> --terminate

# Check failed tasks via Django admin
# Navigate to: /admin/ -> Periodic Tasks -> Task Results
```

#### Beat Scheduler Issues
```bash
# Check beat is running
docker compose -f docker/docker-compose.vps.yml logs celery_beat

# Reset beat schedule (if using DB scheduler)
python manage.py shell -c "
from django_celery_beat.models import PeriodicTask
tasks = PeriodicTask.objects.filter(enabled=True)
for t in tasks:
    print(f'{t.name}: last_run={t.last_run_at}')
"
```

---

## 4. Database Backup & Recovery

### Automated Backups
- Daily backup task runs at 03:00 via Celery Beat
- Retention: 7 days (configurable via `keep_days`)
- Location: see `scripts/vps-backup.sh`

### Manual Backup

```bash
# SQLite backup
cp /app/data/db.sqlite3 /app/data/db.sqlite3.bak.$(date +%Y%m%d)

# PostgreSQL backup
pg_dump -h localhost -U agomtradepro agomtradepro > backup_$(date +%Y%m%d).sql
pg_dump -h localhost -U agomtradepro -Fc agomtradepro > backup_$(date +%Y%m%d).dump
```

### Recovery

```bash
# SQLite restore
cp /app/data/db.sqlite3.bak.YYYYMMDD /app/data/db.sqlite3

# PostgreSQL restore
# See scripts/vps-restore.sh for full procedure
pg_restore -h localhost -U agomtradepro -d agomtradepro -c backup_YYYYMMDD.dump

# Post-restore verification
python manage.py healthcheck
python manage.py warmup_cache
```

---

## 5. Rollback Procedure

### Application Rollback

```bash
# 1. Identify the target version
docker images | grep agomtradepro

# 2. Update docker-compose to use previous image
# Edit docker/docker-compose.vps.yml or set WEB_IMAGE env var
export WEB_IMAGE=agomtradepro:previous-tag

# 3. Rollback
docker compose -f docker/docker-compose.vps.yml up -d

# 4. If migrations need reverting
python manage.py migrate <app_name> <migration_number>
```

### Data Rollback
See `scripts/rollback.sh` for the full rollback procedure.

---

## 6. Monitoring & Alerts

### Health Endpoints
- `GET /api/health/` - Liveness check (returns status + timestamp)
- `GET /api/ready/` - Full readiness check (DB, Redis, Celery, critical data)
- `GET /metrics` - Prometheus metrics endpoint

### Key Metrics to Monitor
- `django_http_requests_total` - Request rate
- `django_http_requests_latency_seconds` - Request latency
- `celery_task_runtime_seconds` - Task execution time
- `celery_task_failures_total` - Task failure count

### Sentry Integration
- Configure `SENTRY_DSN` environment variable
- Error alerts are automatic for unhandled exceptions
- Performance monitoring via `SENTRY_TRACES_RATE` (default: 10%)

---

## 7. Emergency Contacts & Escalation

| Issue | First Responder | Escalation |
|-------|----------------|------------|
| Data sync failure | Check Celery logs, verify data source APIs | Review failover logic |
| High error rate | Check Sentry dashboard | Review recent deployments |
| Database issues | Check connection pool, disk space | DBA team |
| Memory/CPU spike | Check Docker resource limits | Scale resources |
