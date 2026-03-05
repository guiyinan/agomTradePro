# VPS Deployment Runbook (141.11.211.21)

Last updated: 2026-02-15

## Standard Workflow

For standardized release process (test -> package -> release -> rollback), see:

- `docs/deployment/TEST_PACKAGE_RELEASE_WORKFLOW.md`

## Current State

- VPS: `141.11.211.21` (Ubuntu 24.04.2 LTS)
- Deploy root: `/opt/agomsaaf`
- Current release dir: `/opt/agomsaaf/current`
- Compose project name: `agomsaaf`
- Bundle tag currently synced into `/opt/agomsaaf/current`: `agomsaaf-vps-bundle-20260214141304`
- Caddy host ports: `8000` (HTTP) / `8443` (HTTPS port mapped, but domain is empty so you typically use HTTP)
- **Important**: This deployment uses HTTP (not HTTPS), so security settings are configured accordingly.
- Current `WEB_IMAGE` on VPS: `agomsaaf-web:20260215-corsfix-hotfix10`

Services expected:

- `web` (Django + gunicorn, internal port `8000`)
- `redis` (internal port `6379`)
- `rsshub` (internal port `1200`, optional but enabled currently)
- `caddy` (reverse proxy)

## Access

Because system `nginx` is already binding `80`/`443`, Caddy is mapped to non-standard host ports.

- App entry (HTTP via Caddy): `http://141.11.211.21:8000`
- Health check: `http://141.11.211.21:8000/api/health/`

Quick verification (from anywhere):

```sh
curl -fsS http://141.11.211.21:8000/api/health/
```

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
- `ALLOWED_HOSTS=...` (should include VPS IP: `141.11.211.21`)
- `DOMAIN=` (blank means HTTP-only)
- `CADDY_HTTP_PORT=8000`
- `CADDY_HTTPS_PORT=8443`
- `ENABLE_RSSHUB=true|false`
- `ENABLE_CELERY=true|false`

### HTTP Deployment Settings (Current Configuration)

Since this VPS uses HTTP (not HTTPS), the following security settings are **disabled**:

- `SECURE_SSL_REDIRECT=False`
- `SESSION_COOKIE_SECURE=False`
- `CSRF_COOKIE_SECURE=False`

These are set via environment variables in docker-compose.vps.yml. For HTTPS deployments, set these to `True`.

### CORS Configuration

The application is configured to allow cross-origin requests for browser access:

- Django `django-cors-headers` is enabled (preferred single source of truth)
- Caddy **does not** inject CORS headers (avoid conflicts like `Access-Control-Allow-Origin: *` + credentials)
- For production with specific domains, configure `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` in `deploy/.env`

Sanity check (preflight):

```sh
curl -i -X OPTIONS http://141.11.211.21:8000/api/schema/ \
  -H 'Origin: http://example.com' \
  -H 'Access-Control-Request-Method: GET' | grep -i access-control
```

### Common Issues and Fixes

#### 1. CORS Errors

If you see CORS errors in browser console:

```bash
# Check Caddy is running and adding CORS headers
curl -I http://141.11.211.21:8000/api/schema/

# Should see Access-Control-Allow-Origin header
```

#### 2. 404 Errors

If you see 404 errors for API endpoints:

- Check that the URL path matches the configured patterns in `core/urls.py`
- Example: `/macro/dashboard/` does NOT exist - use `/dashboard/` instead
- API endpoints are under `/api/` prefix (e.g., `/api/schema/`)

#### 3. Navigation Not Displaying

If navigation bar is missing:

- Check static files are being served: `http://141.11.211.21:8000/static/css/...`
- Restart Caddy: `docker compose restart caddy`
- Check Django logs: `docker compose logs web`

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

3. Upload + deploy from local (no interactive SSH prompts; uses a local password file):

```powershell
python ./scripts/deploy-bundle-to-vps.py `
  --host 141.11.211.21 `
  --user root `
  --action upgrade `
  --password-file "$HOME\\.agomsaaf\\vps.pass"
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
  Note: If you see `ports: - "80:80"` hardcoded in `docker/docker-compose.vps.yml`, update it to use env vars, otherwise Caddy will fail because `80/443` are occupied by system `nginx`.

4. Caddyfile generation:
- Ensure `/opt/agomsaaf/current/docker/Caddyfile` starts with a valid site address (e.g. `:80 { ... }`), not an interactive prompt prefix.

5. CRLF pitfalls (Windows -> Linux):
- If a `.sh` file in the bundle has CRLF, `/bin/sh` may error like `Syntax error: end of file unexpected (expecting "}")`.
- Fix by running: `sed -i 's/\r$//' /opt/agomsaaf/current/scripts/*.sh` (and similarly under `docker/*.sh`).

6. SQLite restore:
- The running stack uses `DATABASE_URL=sqlite:////app/data/db.sqlite3` with a named volume.

7. Hotfix note (2026-02-15):
- If the bundled `web` image lags behind repo settings (e.g., hardcoded `SECURE_SSL_REDIRECT=True`, missing CORS middleware),
  we can build a small derived image on the VPS that patches `/app/core/settings/*.py` and adds missing runtime deps.
- This is a stopgap; the real fix is: rebuild the `web` image from repo and re-bundle.
- To restore from a bundle’s backup:
  - `web_cid=$(docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q web)`
  - `docker cp backups/db.sqlite3 "$web_cid:/app/data/db.sqlite3"`
  - `docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env restart web`

## Frontend Static Asset Policy

- Do not rely on CDN JS/CSS in templates (some VPS networks block CDNs).
- Vendor third-party libs into `static/vendor/...` and reference them via `{% static %}`.

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
