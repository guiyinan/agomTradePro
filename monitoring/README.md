# Monitoring Configuration

AgomSAAF Prometheus monitoring and alerting configuration.

## Files

- `prometheus.yml` - Prometheus server configuration
- `alerts.yml` - Alert rules for AgomSAAF
- `README.md` - This file

## Alert Rules

### Critical Alerts

| Alert | Trigger | Description |
|-------|---------|-------------|
| `High5xxRate` | 5xx rate > 5% for 2min | High server error rate |
| `AuditWriteFailure` | Any audit write failures | Audit logging is broken |
| `DatabaseConnectionPoolExhausted` | Pool usage > 90% | Database connections exhausted |
| `RedisConnectionFailure` | Redis down for 1min | Redis not responding |

### Warning Alerts

| Alert | Trigger | Description |
|-------|---------|-------------|
| `CeleryTaskBacklog` | > 100 pending tasks | Celery tasks backing up |
| `HighAPILatency` | P95 latency > 1s | Slow API responses |
| `DataCollectionFailure` | Failure rate > 10% | Data collection issues |
| `QlibInferenceFailure` | Failure rate > 5% | Qlib inference problems |
| `DiskSpaceLow` | < 10% free disk | Running out of disk space |

## Quick Start

### 1. Install Prometheus

```bash
# Linux/macOS
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-2.45.0.linux-amd64.tar.gz
cd prometheus-2.45.0.linux-amd64
```

### 2. Start Prometheus

```bash
./prometheus --config.file=/path/to/agomSAAF/monitoring/prometheus.yml
```

### 3. Access UI

- Prometheus UI: http://localhost:9090
- AlertManager: http://localhost:9093

## Verify Configuration

```bash
python scripts/check_alerts.py -v
```

## Metrics Exporters

Django app exposes metrics at `/metrics` endpoint using `django-prometheus`.

Required exporters:
- `django-prometheus` - Django metrics
- `celery-exporter` (port 9540) - Celery metrics
- `postgres_exporter` (port 9187) - PostgreSQL metrics
- `redis_exporter` (port 9121) - Redis metrics
- `node_exporter` (port 9100) - System metrics
