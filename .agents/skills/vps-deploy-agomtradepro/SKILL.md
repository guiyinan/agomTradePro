---
name: vps-deploy-agomtradepro
description: "Use when packaging, Dockerizing, deleting old containers, deploying, or fixing AgomTradePro on a VPS. Reads the target from AGOM_VPS_HOST instead of hardcoding an IP. Covers remote Docker build, code-only vs SQLite restore, Qlib/pyqlib checks, and post-deploy verification. Chinese triggers: 打包上线, Docker部署, 删旧容器, 部署新的, 远端版本不对, QLIB不对."
---

# VPS Deploy AgomTradePro

## Purpose

Deploy the current AgomTradePro workspace to the production VPS using the repository deployment scripts. The target must be read from environment variables:

- host: `$env:AGOM_VPS_HOST` / `AGOM_VPS_HOST`
- ssh user: `$env:AGOM_VPS_USER` / `AGOM_VPS_USER`, default `root`
- ssh password: `$env:AGOM_VPS_PASS` / `AGOM_VPS_PASS`
- ssh port: `$env:AGOM_VPS_PORT` / `AGOM_VPS_PORT`, default `22`
- app port: `$env:AGOM_VPS_HTTP_PORT` / `AGOM_VPS_HTTP_PORT`, default `8000`
- compose project: `agomtradepro`
- remote app dir: `$env:AGOM_VPS_TARGET_DIR` / `AGOM_VPS_TARGET_DIR`, default `/opt/agomtradepro`

Never write the VPS password, API tokens, encryption keys, or temporary password files into the repository.

## Non-Negotiables

- Work from the project root before running scripts.
- Run `git status --short` first and do not revert unrelated user changes.
- Require `AGOM_VPS_HOST` to be set before deploying. If it is missing, ask for the target host or stop and instruct the user to set it.
- Require `AGOM_VPS_PASS` to be set for SSH authentication. If it is missing, ask for the password or stop.
- Use a temporary password file for SSH password input, then delete it. The one-click script `deploy-vps.ps1` handles this automatically.
- If the user says "delete old one" or "把旧的删掉", use `fresh` plus `--wipe-docker`; do not use `--wipe-volumes` unless the user explicitly says to delete the database/data.
- Default to code-only deployment. Use `--include-sqlite` only when the user explicitly wants the local `db.sqlite3` restored to the VPS.
- Qlib package rule: the Python distribution is `pyqlib`, the imported module is `qlib`. Do not add or install a package named `qlib`.
- After every deploy, verify HTTPS health (if DOMAIN is configured) or HTTP health, container state, database freshness, and Qlib package identity inside the running `web` container.
- The deploy script persists `SECRET_KEY`, `AGOMTRADEPRO_ENCRYPTION_KEY`, and `DOMAIN` to `$TARGET_DIR/secrets.env` on the VPS. This file survives `--wipe-docker` and failed deploys. Never regenerate the encryption key unless the user explicitly requests it.

## Preferred Path: One-Click Script (Recommended)

Use `scripts/deploy-vps.ps1` as the **default** method. It reads all config from environment variables (`AGOM_VPS_HOST`, `AGOM_VPS_PASS`, `AGOM_VPS_USER`, etc.), checks for uncommitted/unpushed changes, pushes if needed, and runs the deploy via git-clone.

**Prerequisite**: The latest code must be pushed to GitHub before deploying (the script prompts to push automatically).

```powershell
# Default: fresh deploy, git-clone current branch, preserve remote data, and start Celery
.\scripts\deploy-vps.ps1

# Disable Celery explicitly when you only want web/redis/caddy
.\scripts\deploy-vps.ps1 -DisableCelery

# Restore local SQLite to VPS (overwrites remote DB)
.\scripts\deploy-vps.ps1 -IncludeSqlite

# Upgrade mode (don't remove old containers)
.\scripts\deploy-vps.ps1 -Upgrade

# Specify branch explicitly
.\scripts\deploy-vps.ps1 -GitBranch main
```

## Alternative Path: Git Clone via Python Script

Use this when the one-click script is not available or when you need fine-grained control. The VPS clones from GitHub directly, skipping local source upload entirely.

**Prerequisite**: The latest code must be pushed to GitHub before deploying.

Code-only fresh deploy that removes old containers/images but preserves data volumes:

```powershell
$passFile = Join-Path $env:TEMP 'agomtradepro_vps_pass.txt'
Set-Content -Path $passFile -Value $env:AGOM_VPS_PASS -NoNewline
$vpsHost = $env:AGOM_VPS_HOST
if (-not $vpsHost) { throw 'AGOM_VPS_HOST is required' }
$vpsUser = if ($env:AGOM_VPS_USER) { $env:AGOM_VPS_USER } else { 'root' }
$vpsHttpPort = if ($env:AGOM_VPS_HTTP_PORT) { $env:AGOM_VPS_HTTP_PORT } else { '8000' }

python .\scripts\remote_build_deploy_vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --password-file $passFile `
  --action fresh `
  --wipe-docker `
  --git-clone `
  --http-port $vpsHttpPort `
  --allowed-hosts "$vpsHost,demo.agomtrade.pro,localhost,127.0.0.1" `
  --timeout 1800

$code = $LASTEXITCODE
Remove-Item $passFile -Force -ErrorAction SilentlyContinue
exit $code
```

With specific branch or repo override:

```powershell
python .\scripts\remote_build_deploy_vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --password-file $passFile `
  --action fresh `
  --wipe-docker `
  --git-clone `
  --git-branch dev/feat-xxx `
  --http-port $vpsHttpPort `
  --allowed-hosts "$vpsHost,demo.agomtrade.pro,localhost,127.0.0.1" `
  --timeout 1800
```

Celery is enabled by default. Disable it only when background jobs must stay off:

```powershell
python .\scripts\remote_build_deploy_vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --password-file $passFile `
  --action fresh `
  --wipe-docker `
  --git-clone `
  --disable-celery `
  --timeout 1800
```

## Alternative Path: Remote Source Upload Build

Use this when the VPS cannot reach GitHub (firewall, private repo without deploy key, etc).

Code-only fresh deploy that removes old containers/images but preserves data volumes:

```powershell
$passFile = Join-Path $env:TEMP 'agomtradepro_vps_pass.txt'
Set-Content -Path $passFile -Value $env:AGOM_VPS_PASS -NoNewline
$vpsHost = $env:AGOM_VPS_HOST
if (-not $vpsHost) { throw 'AGOM_VPS_HOST is required' }
$vpsUser = if ($env:AGOM_VPS_USER) { $env:AGOM_VPS_USER } else { 'root' }
$vpsHttpPort = if ($env:AGOM_VPS_HTTP_PORT) { $env:AGOM_VPS_HTTP_PORT } else { '8000' }

python .\scripts\remote_build_deploy_vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --password-file $passFile `
  --action fresh `
  --wipe-docker `
  --http-port $vpsHttpPort `
  --allowed-hosts "$vpsHost,demo.agomtrade.pro,localhost,127.0.0.1" `
  --timeout 1800

$code = $LASTEXITCODE
Remove-Item $passFile -Force -ErrorAction SilentlyContinue
exit $code
```

Deploy and restore local SQLite:

```powershell
python .\scripts\remote_build_deploy_vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --password-file $passFile `
  --action fresh `
  --wipe-docker `
  --include-sqlite `
  --http-port $vpsHttpPort `
  --allowed-hosts "$vpsHost,demo.agomtrade.pro,localhost,127.0.0.1" `
  --timeout 1800
```

Celery is enabled by default. Disable it only when background scheduled jobs must stay off:

```powershell
python .\scripts\remote_build_deploy_vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --password-file $passFile `
  --action fresh `
  --wipe-docker `
  --disable-celery `
  --timeout 1800
```

## Fallback Path: Local Bundle Then Upload

Use this when a local Docker build is required or when debugging packaging stages.

```powershell
$tag = Get-Date -Format 'yyyyMMddHHmmss'
pwsh -File scripts/package-for-vps-aggressive.ps1 -Tag $tag -PreferWslBuild
```

For local SQLite restore:

```powershell
pwsh -File scripts/package-for-vps-aggressive.ps1 -Tag $tag -PreferWslBuild -WithLocalSqlite
```

Deploy the bundle:

```powershell
$passFile = Join-Path $env:TEMP 'agomtradepro_vps_pass.txt'
Set-Content -Path $passFile -Value $env:AGOM_VPS_PASS -NoNewline
$vpsHost = $env:AGOM_VPS_HOST
if (-not $vpsHost) { throw 'AGOM_VPS_HOST is required' }
$vpsUser = if ($env:AGOM_VPS_USER) { $env:AGOM_VPS_USER } else { 'root' }

python .\scripts\deploy-bundle-to-vps.py `
  --host $vpsHost `
  --user $vpsUser `
  --action fresh `
  --bundle ".\dist\agomtradepro-vps-bundle-$tag.tar.gz" `
  --password-file $passFile `
  --timeout 180

$code = $LASTEXITCODE
Remove-Item $passFile -Force -ErrorAction SilentlyContinue
exit $code
```

If `-WithLocalSqlite` was used, deploy `.\dist\agomtradepro-vps-bundle-$tag-live.tar.gz` instead of the code-only bundle.

## Preflight Checks

Before packaging, confirm the Qlib dependency is correct:

```powershell
Select-String -Path requirements*.txt,pyproject.toml,Dockerfile*,docker\* -Pattern "pyqlib|^[^#]*qlib" -ErrorAction SilentlyContinue
```

Expected:

- `pyqlib` is present in the runtime requirements or Docker build dependencies.
- No active dependency line installs `qlib`.
- Docker image installs system runtime libraries required by `pyqlib`, especially `libgomp1` on Debian/Ubuntu images.

If inference results on the VPS look several days old, decide whether this is a code/image issue or a data issue before redeploying:

- code/image issue: remote container image was not rebuilt or compose is still running an old tag.
- data issue: VPS SQLite volume differs from local `db.sqlite3`; use `--include-sqlite` only if the VPS should be overwritten by local data.
- scheduler issue: if Celery was explicitly disabled, periodic inference jobs will not run until `celery_worker` and `celery_beat` are started again.

## Post-Deploy Verification

Run these on the VPS after deploy:

```bash
cd /opt/agomtradepro/current
docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env ps
curl -fsS http://127.0.0.1:8000/api/health/
```

If DOMAIN is configured (e.g. `demo.agomtrade.pro`), verify Caddy HTTPS:

```bash
curl -fsSk https://demo.agomtrade.pro/api/health/
# Check Caddy has TLS certificate
docker logs agomtradepro-caddy-1 --tail 10 2>&1 | grep -E "tls|certificate|auto_https"
# Verify Caddyfile has domain (not :80)
head -1 /opt/agomtradepro/current/docker/Caddyfile
```

If Caddy is listening on `:80` instead of the domain, the DOMAIN was lost. Check `secrets.env`:

```bash
cat /opt/agomtradepro/secrets.env
# Should contain: DOMAIN=demo.agomtrade.pro
```

Verify Python package identity inside the `web` container:

```bash
docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env exec -T web python - <<'PY'
from importlib.metadata import PackageNotFoundError, version
try:
    print("pyqlib", version("pyqlib"))
except PackageNotFoundError:
    raise SystemExit("pyqlib distribution is missing")
try:
    print("qlib distribution", version("qlib"))
    raise SystemExit("wrong qlib distribution is installed")
except PackageNotFoundError:
    print("qlib distribution absent: ok")
import qlib
print("qlib module", qlib.__file__)
PY
```

Verify database presence and latest timestamps:

```bash
docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env exec -T web python - <<'PY'
import os
import sqlite3
db = "/app/data/db.sqlite3"
print("db_exists", os.path.exists(db), "db_size", os.path.getsize(db) if os.path.exists(db) else 0)
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("select count(*) from sqlite_master where type='table'")
print("table_count", cur.fetchone()[0])
for table in ["alpha_stock_score", "alpha_qlib_prediction", "task_monitor_taskrun"]:
    cur.execute("select name from sqlite_master where type='table' and name=?", (table,))
    if cur.fetchone():
        cur.execute(f"select count(*) from {table}")
        print(table, "rows", cur.fetchone()[0])
conn.close()
PY
```

## Troubleshooting Playbook

- External access URL: `https://demo.agomtrade.pro` (if DOMAIN configured) or `http://$AGOM_VPS_HOST:$AGOM_VPS_HTTP_PORT/`.
- **PR_END_OF_FILE_ERROR on HTTPS**: Caddy is listening on `:80` (HTTP only) instead of the domain. The DOMAIN was lost from `secrets.env`. Fix: add `DOMAIN=demo.agomtrade.pro` to `/opt/agomtradepro/secrets.env`, update the Caddyfile, and restart Caddy. Then redeploy to make it permanent.
- **Encryption key regenerated unexpectedly**: The `AGOMTRADEPRO_ENCRYPTION_KEY` was lost from `secrets.env` (e.g. after a failed deploy wiped `current/` before keys were preserved). Check `/opt/agomtradepro/secrets.env` — it should always contain `SECRET_KEY`, `AGOMTRADEPRO_ENCRYPTION_KEY`, and `DOMAIN`.
- If `web` is healthy locally but not from the internet, check VPS firewall/security group and whether Caddy or the Django port is exposed.
- If the UI still shows old inference data, compare the local and remote SQLite files first. Code-only deploy preserves the VPS database volume.
- If Qlib is wrong, rebuild the image after fixing dependencies; do not repair by `pip install qlib` inside a running container.
- If `web` logs show stale Qlib paths from Windows or old cache directories, clear or migrate the persisted Qlib runtime configuration under `/app/data`, then restart `web`.
- If deployment succeeds but scheduled inference does not advance, check whether `celery_worker` and `celery_beat` are running. The deploy flow now defaults to `ENABLE_CELERY=true`, so a missing worker usually means failed startup or a manual disable.
- If a failed build left remote temp files, remove `/tmp/agomtradepro-source-upload` and prune Docker builder cache on the VPS.
- If a healthcheck references `/health/`, update it to `/api/health/` in the deployed compose file and recreate affected services.

## Expected Final Report

When reporting back to the user, include:

- deployed mode: `code-only` or `with-local-sqlite`
- cleanup mode: `--wipe-docker` and whether volumes were preserved
- public URL and health result (use HTTPS URL if DOMAIN is configured)
- Caddy HTTPS status: verify Caddyfile has domain (not `:80`) and TLS certificate is obtained
- running container state
- Qlib check result: `pyqlib` version, imported `qlib` module path, and absence of the wrong `qlib` distribution
- whether Celery was enabled
- deployment report path under `dist/remote-build-reports` when available
