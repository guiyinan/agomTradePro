# VPS Deployment Runbook (141.11.211.21)

Last updated: 2026-02-14

## Current State

- VPS: `141.11.211.21` (Ubuntu 24.04.2 LTS)
- Deploy root: `/opt/agomsaaf`
- Current release dir: `/opt/agomsaaf/current`
- Compose project name: `agomsaaf`

Services expected:

- `web` (Django + gunicorn, internal port `8000`)
- `redis` (internal port `6379`)
- `rsshub` (internal port `1200`, optional but enabled currently)
- `caddy` (reverse proxy)

## Access

Because system `nginx` is already binding `80`/`443`, Caddy is mapped to non-standard host ports.

- App entry (HTTP via Caddy): `http://141.11.211.21:8000`
- Health check: `http://141.11.211.21:8000/health/`

If you later free ports `80/443`, you can remap Caddy by editing `/opt/agomsaaf/current/deploy/.env`:

- `CADDY_HTTP_PORT=80`
- `CADDY_HTTPS_PORT=443`

then:

```sh
export COMPOSE_PROJECT_NAME=agomsaaf
cd /opt/agomsaaf/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env up -d caddy
```

## Port Conflicts

Observed listeners:

- `80/tcp` is occupied by system `nginx`
- `443/tcp` is also occupied (cannot map Caddy to 443)

To inspect:

```sh
ss -ltnp | grep -E ':80 |:443 |:8000 |:8443 ' || true
```

## Configuration Keys

In `/opt/agomsaaf/current/deploy/.env`:

- `WEB_IMAGE=...` (must point to the loaded web image tag)
- `SECRET_KEY=...`
- `ALLOWED_HOSTS=...`
- `DOMAIN=` (blank means HTTP-only)
- `CADDY_HTTP_PORT=8000`
- `CADDY_HTTPS_PORT=8443`
- `ENABLE_RSSHUB=true|false`
- `ENABLE_CELERY=true|false`

## Operations

Status:

```sh
export COMPOSE_PROJECT_NAME=agomsaaf
cd /opt/agomsaaf/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env ps
```

Logs:

```sh
export COMPOSE_PROJECT_NAME=agomsaaf
cd /opt/agomsaaf/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env logs -f --tail=200
```

Restart just web:

```sh
export COMPOSE_PROJECT_NAME=agomsaaf
cd /opt/agomsaaf/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env restart web
```

Backup (recommended before upgrade):

```sh
bash /opt/agomsaaf/current/scripts/vps-backup.sh --target-dir /opt/agomsaaf/current --backup-dir /opt/agomsaaf/backups --keep-days 14
```

## Upgrade Flow (Recommended)

On your local machine:

1. Build bundle (default: code upgrade bundle; no local SQLite/Redis data):

```powershell
pwsh ./scripts/package-for-vps.ps1
```

2. Verify bundle:

```powershell
pwsh ./scripts/verify-vps-bundle.ps1 -Bundle ./dist/agomsaaf-vps-bundle-<tag>.tar.gz -NoDockerLoad
```

On the VPS:

1. Upload bundle to `/tmp/`.
2. Run upgrade:

```sh
bash /opt/agomsaaf/current/scripts/deploy-on-vps.sh --bundle /tmp/agomsaaf-vps-bundle-<tag>.tar.gz --target-dir /opt/agomsaaf --action upgrade
```

## Known Fixes Applied During Initial Bring-up

1. Missing production dependencies caused `web` to crash:
- `django-filter`
- `gunicorn`

These were hotfixed on the VPS image tag at the time. The repo-side fix is to include them in `requirements-prod.txt`.

2. Bundle manifest verification portability:
- Windows path separators in `deploy/manifest.json` can break Linux verification if not normalized.

3. Caddy ports made configurable:
- Host ports for Caddy are now environment-driven (`CADDY_HTTP_PORT`, `CADDY_HTTPS_PORT`).

4. Caddyfile generation:
- Ensure `/opt/agomsaaf/current/docker/Caddyfile` starts with a valid site address (e.g. `:80 { ... }`), not an interactive prompt prefix.

## Troubleshooting

If `web` is unhealthy:

```sh
export COMPOSE_PROJECT_NAME=agomsaaf
cd /opt/agomsaaf/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env logs --tail=200 web
```

If `caddy` fails:

```sh
export COMPOSE_PROJECT_NAME=agomsaaf
cd /opt/agomsaaf/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env logs --tail=200 caddy
```

If ports are occupied:

```sh
ss -ltnp | grep -E ':80 |:443 |:8000 |:8443 ' || true
```

