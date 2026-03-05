# AgomSAAF Operations Runbook

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
| 16:30 | `sync_high_frequency_bonds` | Bond market data sync |
| 16:35 | `sync_high_frequency_commodities` | Commodity data sync |
| 17:00 | `generate_daily_regime_signal` | Generate daily regime signal |
| 17:05 | `recalculate_regime_with_daily_signal` | Recalculate regime |
| 17:30 | `qlib_daily_inference` | Alpha AI inference |

### Manual Verification

```bash
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
```

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
pg_dump -h localhost -U agomsaaf agomsaaf > backup_$(date +%Y%m%d).sql
pg_dump -h localhost -U agomsaaf -Fc agomsaaf > backup_$(date +%Y%m%d).dump
```

### Recovery

```bash
# SQLite restore
cp /app/data/db.sqlite3.bak.YYYYMMDD /app/data/db.sqlite3

# PostgreSQL restore
# See scripts/vps-restore.sh for full procedure
pg_restore -h localhost -U agomsaaf -d agomsaaf -c backup_YYYYMMDD.dump

# Post-restore verification
python manage.py healthcheck
python manage.py warmup_cache
```

---

## 5. Rollback Procedure

### Application Rollback

```bash
# 1. Identify the target version
docker images | grep agomsaaf

# 2. Update docker-compose to use previous image
# Edit docker/docker-compose.vps.yml or set WEB_IMAGE env var
export WEB_IMAGE=agomsaaf:previous-tag

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
