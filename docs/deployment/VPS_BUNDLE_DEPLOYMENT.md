# AgomTradePro VPS Bundle Deployment Guide

## 1. Scope

This guide covers the new bundle-based deployment flow:

1. Build Docker images locally.
2. Export Docker images as tar files.
3. Optionally export local SQLite and Redis data.
4. Pack all deployment artifacts into one bundle.
5. Upload bundle to Linux VPS and deploy interactively.

Target scripts:

- `scripts/package-for-vps.ps1`
- `scripts/deploy-on-vps.sh`
- `scripts/deploy-on-vps.ps1`

---

## 2. Prerequisites

### Local machine (Windows + PowerShell)

1. Docker Desktop installed and running.
2. Project repo up to date.
3. Local `db.sqlite3` and optional Redis running in Docker containers.
4. PowerShell 7 recommended (`pwsh`).

### Linux VPS

1. Docker Engine installed.
2. Docker Compose plugin available (`docker compose`).
3. SSH access with permissions to manage Docker.
4. Open ports (host side):
   - `CADDY_HTTP_PORT` (default `80` for domain deployments, `8000` only for temporary IP access)
   - `CADDY_HTTPS_PORT` (default `443`, optional if you do not configure a domain)

---

## 3. Build Bundle on Local Machine

Platform: Windows PowerShell

Run from project root:

```powershell
pwsh ./scripts/package-for-vps.ps1
```

Optional example (explicit container names):

```powershell
pwsh ./scripts/package-for-vps.ps1 `
  -Tag 20260208 `
  -IncludeSqliteData `
  -RedisContainer agomtradepro_redis
```

Wheel cache options:

```powershell
# 强制刷新 Linux wheel 缓存
pwsh ./scripts/package-for-vps.ps1 -RefreshWheelCache
```

What this script does:

1. Builds production image with `docker/Dockerfile.prod`.
2. Installs production-only Python dependencies from `requirements-prod.txt`.
   - Microsoft Qlib is installed separately as the `pyqlib` PyPI distribution.
   - Do not install `qlib`; that is a different package and does not provide `qlib.data`.
   - The production Dockerfile verifies `metadata.distribution("pyqlib")` and `import qlib.data` during build.
   - Daily scoped Alpha inference refreshes Qlib data for the union of all active portfolio scopes before queueing per-portfolio predictions. Use `portfolio_limit=0` to cover every active portfolio.
   - The production Celery worker must consume `celery,qlib_infer,qlib_train`; Qlib prediction tasks are routed to `qlib_infer`.
3. Pulls dependency images (`redis`, `caddy`, `rsshub`).
4. Saves images to tar files.
5. Optionally copies local `db.sqlite3` to `backups/db.sqlite3` (default: No).
   - For upgrades on a VPS that already has data, you usually want **No** (keep the existing `sqlite_data` volume).
   - Only include SQLite when you explicitly want to overwrite/seed the VPS database.
6. Optionally exports Redis snapshot `backups/dump.rdb` (default: No; explicit container required).
7. Copies deployment templates and scripts.
8. Creates a final bundle tar.gz in `dist/`.

Output example:

- `dist/agomtradepro-vps-bundle-20260208153000.tar.gz`

Bundle verification:

```powershell
pwsh ./scripts/verify-vps-bundle.ps1 -Bundle ./dist/agomtradepro-vps-bundle-20260208153000.tar.gz -NoDockerLoad
```

---

## 4. Upload Bundle to VPS

Platform: cross-platform shell from local machine

Use SCP (example):

```bash
scp dist/agomtradepro-vps-bundle-20260208153000.tar.gz user@your-vps:/tmp/
```

---

## 5. Deploy on Linux VPS (Recommended)

Platform: Linux VPS shell

SSH to VPS:

```bash
ssh user@your-vps
```

Run deployment script directly from repo or extracted bundle scripts:

```bash
bash ./scripts/deploy-on-vps.sh --bundle /tmp/agomtradepro-vps-bundle-20260208153000.tar.gz
```

The script supports interactive actions:

1. `fresh` - first-time deployment.
2. `upgrade` - upgrade app with existing volumes.
3. `restore-only` - restore DB/cache without full restart flow.
4. `status` - show compose status.
5. `logs` - tail logs.

Default deployment root:

- `/opt/agomtradepro`

---

## 6. PowerShell Deployment on Linux (Optional)

If your VPS has PowerShell 7:

```powershell
pwsh ./scripts/deploy-on-vps.ps1 -Bundle /tmp/agomtradepro-vps-bundle-20260208153000.tar.gz
```

---

## 7. Domain and HTTPS

1. If `DOMAIN` is set in `deploy/.env`, Caddy uses domain mode and should be exposed on host `80/443` so it can issue HTTPS certs normally.
2. If `DOMAIN` is empty, Caddy uses HTTP on container `:80`, and the **host port** is controlled by `CADDY_HTTP_PORT` in `deploy/.env` (typically `8000` for temporary IP-only access).
3. `scripts/remote_build_deploy_vps.py` now preserves the existing remote `DOMAIN`, `ALLOWED_HOSTS`, and Caddy port mapping unless you explicitly override them on the next deploy.

Template source:

- `docker/Caddyfile.template`

Rendered file at deploy time:

- `docker/Caddyfile`

---

## 7.1 Self-hosted RSSHub (4G-friendly)

The VPS stack supports built-in RSSHub service (`rsshub` container).

Set in `deploy/.env`:

```env
ENABLE_RSSHUB=true
```

Then configure RSSHub global base URL in your app data to:

```text
http://rsshub:1200
```

Why this value:

1. It is container-internal networking.
2. It avoids public RSSHub rate limits.
3. It does not require exposing RSSHub to public internet.

---

## 7.2 4G VPS Memory Recommendations

Recommended `deploy/.env` values:

```env
ENABLE_CELERY=false
ENABLE_RSSHUB=true
GUNICORN_WORKERS=2
REDIS_MAXMEMORY=256mb
```

Operational advice:

1. Keep Celery disabled unless you actively need async tasks.
2. Enable Celery temporarily for scheduled jobs:
   - set `ENABLE_CELERY=true`
   - rerun deployment action `upgrade`
3. Add swap (for example 2G) to reduce OOM risk during spikes.

---

## 8. Runtime Configuration

Main env template:

- `deploy/.env.vps.example`

At deploy time, script will create/update:

- `deploy/.env`

Critical values to set:

1. `SECRET_KEY`
2. `DATABASE_URL` (default SQLite path is already provided)
3. `ALLOWED_HOSTS`
4. `DOMAIN` (optional but recommended for HTTPS)
5. API keys (`TUSHARE_TOKEN`, `OPENAI_API_KEY`, etc.) if needed
6. Service toggles:
   - `ENABLE_RSSHUB=true|false`
   - `ENABLE_CELERY=true|false`
7. For standard public domain access, keep:
   - `CADDY_HTTP_PORT=80`
   - `CADDY_HTTPS_PORT=443`

---

## 9. Verify Deployment

Platform: Linux VPS shell

Check service status:

```bash
docker compose -f /opt/agomtradepro/current/docker/docker-compose.vps.yml --env-file /opt/agomtradepro/current/deploy/.env ps
```

Health check:

```bash
HTTP_PORT=$(grep '^CADDY_HTTP_PORT=' /opt/agomtradepro/current/deploy/.env | cut -d '=' -f2- | tail -n 1)
curl -f "http://127.0.0.1:${HTTP_PORT:-8000}/api/health/"
```

判定口径：

1. 以 `curl` 退出码和最终 HTTP 状态码为准。
2. `2xx` 即视为健康，不能再把“响应体为空”误判成失败。
3. 只有在需要核对 JSON 契约时，才额外检查响应体内容。

If domain is configured:

```bash
curl -f https://your-domain/api/health/
```

---

## 10. Rollback Strategy

Each deployment bundle is unpacked into:

- `/opt/agomtradepro/releases/<bundle-name>`

Current release:

- `/opt/agomtradepro/current`

Rollback approach:

1. Stop current stack.
2. Switch `current` to a previous release directory.
3. Start compose again with previous release env and compose files.

---

## 11. Backup and Restore

### 11.1 Backup (Linux)

Run on VPS:

```bash
bash /opt/agomtradepro/current/scripts/vps-backup.sh \
  --target-dir /opt/agomtradepro/current \
  --backup-dir /opt/agomtradepro/backups \
  --keep-days 14
```

What it backs up:

1. SQLite database from `web` container (`/app/data/db.sqlite3`).
2. Redis snapshot (`dump.rdb`).
3. Deployment metadata (`deploy/.env`, compose file, optional Caddyfile).
4. SHA-256 manifest file for backup integrity.

### 11.2 Restore (Linux)

Restore latest backup:

```bash
bash /opt/agomtradepro/current/scripts/vps-restore.sh \
  --target-dir /opt/agomtradepro/current \
  --backup-dir /opt/agomtradepro/backups
```

Restore specific files:

```bash
bash /opt/agomtradepro/current/scripts/vps-restore.sh \
  --target-dir /opt/agomtradepro/current \
  --backup-dir /opt/agomtradepro/backups \
  --sqlite-file /opt/agomtradepro/backups/sqlite/db-20260208-130000.sqlite3.gz \
  --redis-file /opt/agomtradepro/backups/redis/dump-20260208-130000.rdb.gz
```

### 11.3 PowerShell on Linux (optional)

Backup:

```powershell
pwsh /opt/agomtradepro/current/scripts/vps-backup.ps1 -TargetDir /opt/agomtradepro/current -BackupDir /opt/agomtradepro/backups -KeepDays 14
```

Restore:

```powershell
pwsh /opt/agomtradepro/current/scripts/vps-restore.ps1 -TargetDir /opt/agomtradepro/current -BackupDir /opt/agomtradepro/backups
```

---

## 12. Troubleshooting

### Bundle extraction fails

1. Verify upload integrity (`sha256sum`).
2. Confirm enough disk space.

### Containers fail to start

1. Check logs:
   ```bash
   docker compose -f /opt/agomtradepro/current/docker/docker-compose.vps.yml --env-file /opt/agomtradepro/current/deploy/.env logs -f
   ```
2. Confirm `SECRET_KEY` is not default placeholder.

### HTTP 400 Bad Request

This is almost always `ALLOWED_HOSTS` mismatch.

1. Edit: `/opt/agomtradepro/current/deploy/.env`
2. Set `ALLOWED_HOSTS` to include your access IP and/or domain (comma-separated).
3. Restart web:
   ```bash
   docker compose -f /opt/agomtradepro/current/docker/docker-compose.vps.yml --env-file /opt/agomtradepro/current/deploy/.env restart web
   ```

### SQLite restore fails

1. Ensure `backups/db.sqlite3` exists in bundle.
2. Ensure `sqlite_data` volume is writable.
3. Retry `restore-only` action.

### Redis restore fails

1. Ensure `backups/dump.rdb` exists in bundle.
2. Check Redis container state and volume permissions.

---

## 13. Security Checklist

1. Replace default `SECRET_KEY`.
2. Protect and back up `db.sqlite3` regularly.
3. Restrict firewall rules for SSH and public ports only.
4. Set `ALLOWED_HOSTS` to your domain/IP list.
5. Keep VPS system and Docker updated.
