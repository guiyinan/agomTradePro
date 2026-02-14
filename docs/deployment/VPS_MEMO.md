# VPS Deployment Memo

This is the "do the right thing fast" memo for AgomSAAF VPS deployments.

## Defaults (What Runs Where)

- External traffic goes to `caddy` (reverse proxy).
- Host port mapping is configured via `deploy/.env`:
  - `CADDY_HTTP_PORT` (default `8000`)
  - `CADDY_HTTPS_PORT` (default `443`)
- Django app runs inside `web` container on internal port `8000` (not exposed to host directly).
- Redis runs as a container (`redis`), only on Docker internal network (no host port).
- Database is SQLite by default:
  - Container path: `/app/data/db.sqlite3`
  - Stored in Docker named volume: `sqlite_data`

## What Data Is In Redis?

Redis is used as runtime infrastructure (cache/broker), not as the system-of-record:

- Django cache (if enabled)
- Celery broker/result backend (if enabled)
- RSSHub cache (service-internal)

Recommendation:
- Treat Redis data as **ephemeral**.
- Do not bundle/restore Redis by default unless you have a specific need.

## The Two "Upgrade" Modes

1. Code upgrade (recommended):
- Do not ship local `db.sqlite3`
- Reuse VPS volumes (`sqlite_data`, `redis_data`, static/media volumes)
- Run migrations automatically

2. Seed/overwrite (dangerous):
- Bundle includes `backups/db.sqlite3`
- Deploy will restore it into the VPS volume (overwrites production database)

## Local Build (Windows)

Build bundle (interactive quick mode):

```powershell
pwsh ./scripts/package-for-vps.ps1
```

Verify bundle:

```powershell
pwsh ./scripts/verify-vps-bundle.ps1 -Bundle ./dist/agomsaaf-vps-bundle-<tag>.tar.gz -NoDockerLoad
```

Inject SQLite into an existing bundle (fast, does not rebuild images):

```powershell
pwsh ./scripts/inject-sqlite-into-bundle.ps1 `
  -SourceBundle ./dist/agomsaaf-vps-bundle-<tag>.tar.gz `
  -OutputTag <newTag> `
  -SqliteFile ./db.sqlite3
```

## VPS Deploy (Linux)

Deploy (interactive):

```bash
bash ./scripts/deploy-on-vps.sh --bundle /tmp/agomsaaf-vps-bundle-<tag>.tar.gz
```

Common actions:
- `fresh`: first deploy
- `upgrade`: keep volumes, update code/image, run migrations
- `restore-only`: restore DB/redis files from the bundle (if present)

After deploy, the canonical working directory is:
- `/opt/agomsaaf/current`

## Ports (When 80/443 Are Occupied)

Set host ports in:
- `/opt/agomsaaf/current/deploy/.env`

Example:

```env
CADDY_HTTP_PORT=8000
CADDY_HTTPS_PORT=8443
```

Restart Caddy:

```bash
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env restart caddy
```

## Access & Health Check

```bash
HTTP_PORT=$(grep '^CADDY_HTTP_PORT=' /opt/agomsaaf/current/deploy/.env | cut -d '=' -f2- | tail -n 1)
curl -fsS "http://<vps-ip>:${HTTP_PORT:-8000}/health/"
```

## Troubleshooting

### HTTP 400 Bad Request

Almost always `ALLOWED_HOSTS` mismatch.

- Edit `/opt/agomsaaf/current/deploy/.env` and set `ALLOWED_HOSTS` to include your IP/domain.
- Restart:
  ```bash
  docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env restart web
  ```

### Windows CRLF Breaks Linux /bin/sh

Symptoms:
- `/bin/sh: Syntax error: end of file unexpected (expecting "}")`

Fix on VPS:

```bash
sed -i 's/\r$//' /opt/agomsaaf/current/scripts/*.sh /opt/agomsaaf/current/docker/*.sh || true
```

### Docker Build Uses Proxy Unexpectedly

Packaging script clears proxy build-args/env, but if you keep seeing proxy-related build errors:
- Check `docker info` for `HTTP Proxy` / `HTTPS Proxy`
- Disable proxy in Docker Desktop settings (daemon-level proxy overrides env vars)

