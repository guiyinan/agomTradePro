# AgomSAAF VPS Bundle Deployment Guide

## 1. Scope

This guide covers the new bundle-based deployment flow:

1. Build Docker images locally.
2. Export Docker images as tar files.
3. Export local SQLite and Redis data.
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
4. Open ports:
   - `80` (HTTP)
   - `443` (HTTPS, optional if domain is configured)

---

## 3. Build Bundle on Local Machine

Run from project root:

```powershell
pwsh ./scripts/package-for-vps.ps1
```

Optional example (explicit container names):

```powershell
pwsh ./scripts/package-for-vps.ps1 `
  -Tag 20260208 `
  -RedisContainer agomsaaf_redis
```

What this script does:

1. Builds production image with `docker/Dockerfile.prod`.
2. Auto-selects faster PyPI index between Aliyun mirror and official PyPI.
3. Pulls dependency images (`redis`, `caddy`, `rsshub`).
4. Saves images to tar files.
5. Copies local `db.sqlite3` to `backups/db.sqlite3`.
6. Exports Redis snapshot `backups/dump.rdb`.
7. Copies deployment templates and scripts.
8. Creates a final bundle tar.gz in `dist/`.

Output example:

- `dist/agomsaaf-vps-bundle-20260208153000.tar.gz`

---

## 4. Upload Bundle to VPS

Use SCP (example):

```bash
scp dist/agomsaaf-vps-bundle-20260208153000.tar.gz user@your-vps:/tmp/
```

---

## 5. Deploy on Linux VPS (Recommended)

SSH to VPS:

```bash
ssh user@your-vps
```

Run deployment script directly from repo or extracted bundle scripts:

```bash
bash ./scripts/deploy-on-vps.sh --bundle /tmp/agomsaaf-vps-bundle-20260208153000.tar.gz
```

The script supports interactive actions:

1. `fresh` - first-time deployment.
2. `upgrade` - upgrade app with existing volumes.
3. `restore-only` - restore DB/cache without full restart flow.
4. `status` - show compose status.
5. `logs` - tail logs.

Default deployment root:

- `/opt/agomsaaf`

---

## 6. PowerShell Deployment on Linux (Optional)

If your VPS has PowerShell 7:

```powershell
pwsh ./scripts/deploy-on-vps.ps1 -Bundle /tmp/agomsaaf-vps-bundle-20260208153000.tar.gz
```

---

## 7. Domain and HTTPS

1. If `DOMAIN` is set in `deploy/.env`, Caddy uses domain mode and can issue HTTPS certs.
2. If `DOMAIN` is empty, Caddy uses HTTP on `:80`.

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

---

## 9. Verify Deployment

Check service status:

```bash
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env ps
```

Health check:

```bash
curl -f http://127.0.0.1/health/
```

If domain is configured:

```bash
curl -f https://your-domain/health/
```

---

## 10. Rollback Strategy

Each deployment bundle is unpacked into:

- `/opt/agomsaaf/releases/<bundle-name>`

Current release:

- `/opt/agomsaaf/current`

Rollback approach:

1. Stop current stack.
2. Switch `current` to a previous release directory.
3. Start compose again with previous release env and compose files.

---

## 11. Troubleshooting

### Bundle extraction fails

1. Verify upload integrity (`sha256sum`).
2. Confirm enough disk space.

### Containers fail to start

1. Check logs:
   ```bash
   docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env logs -f
   ```
2. Confirm `SECRET_KEY` is not default placeholder.

### SQLite restore fails

1. Ensure `backups/db.sqlite3` exists in bundle.
2. Ensure `sqlite_data` volume is writable.
3. Retry `restore-only` action.

### Redis restore fails

1. Ensure `backups/dump.rdb` exists in bundle.
2. Check Redis container state and volume permissions.

---

## 12. Security Checklist

1. Replace default `SECRET_KEY`.
2. Protect and back up `db.sqlite3` regularly.
3. Restrict firewall rules for SSH and public ports only.
4. Set `ALLOWED_HOSTS` to your domain/IP list.
5. Keep VPS system and Docker updated.
