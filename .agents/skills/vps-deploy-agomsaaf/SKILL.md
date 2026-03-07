---
name: vps-deploy-agomsaaf
description: "Use when deploying this Django Docker stack to VPS 141.11.211.21, including full Docker cleanup, fresh/upgrade rollout, and both deployment modes: with local SQLite database restore or code-only without local DB."
---

# Vps Deploy Agomsaaf

## Overview

Deploy the current workspace to the target VPS using repository scripts and bundle workflow.  
Support two release modes:
- `code-only`: deploy latest image/code without restoring local `db.sqlite3`.
- `with-local-sqlite`: deploy and restore local `db.sqlite3` into VPS container volume.

## Workflow

1. Confirm deployment target and mode (`code-only` or `with-local-sqlite`).
2. Choose local image packaging or remote source build on the VPS.
3. Optionally inject local SQLite into bundle.
4. Optionally wipe VPS Docker state before fresh rollout.
5. Upload bundle and run remote deploy action (`fresh` or `upgrade`).
6. Verify container health, external health endpoint, and DB presence.

## Inputs

- `host`: `141.11.211.21`
- `user`: `root`
- `password`: provided by user at runtime (do not hardcode into files)
- `action`: `fresh` (full replacement) or `upgrade` (rolling update)
- `bundle_mode`: `code-only` or `with-local-sqlite`

## Step 1: Build Latest Bundle

Prefer the aggressive wrapper. It auto-retries common failure modes:

```powershell
$tag = Get-Date -Format 'yyyyMMddHHmmss'
pwsh -File scripts/package-for-vps-aggressive.ps1 -Tag $tag
```

When Windows disk I/O is the bottleneck, prefer WSL first:

```powershell
pwsh -File scripts/package-for-vps-aggressive.ps1 -Tag $tag -PreferWslBuild
```

Expected output bundle:
- `dist/agomsaaf-vps-bundle-$tag.tar.gz`

Fallback entrypoint only when debugging a specific stage:
- `scripts/package-for-vps.ps1`

## Step 1B: Remote Source Build On VPS

Prefer this path when local Windows or WSL disk I/O is the bottleneck:

```powershell
python .\scripts\remote_build_deploy_vps.py
```

This script:

- prompts for VPS host, port, username, password
- asks whether to include local SQLite
- asks whether to wipe existing Docker resources first
- uploads source instead of image tar files
- builds and deploys on the VPS directly
- downloads a deployment report to `dist/remote-build-reports`
- deletes remote temporary upload/build files by default

## Step 2: Optional SQLite Injection (with-local-sqlite mode)

For `with-local-sqlite`, prefer the wrapper flag:

```powershell
pwsh -File scripts/package-for-vps-aggressive.ps1 -Tag $tag -WithLocalSqlite
```

Use resulting bundle:
- `dist/agomsaaf-vps-bundle-$tag-live.tar.gz`

Manual fallback remains:

```powershell
pwsh -File scripts/inject-sqlite-into-bundle.ps1 `
  -SourceBundle dist/agomsaaf-vps-bundle-$tag.tar.gz `
  -OutputTag "$tag-live"
```

## Step 3: Optional VPS Docker Full Cleanup

Use this before strict `fresh` rollout when old stacks conflict:

```bash
docker ps -aq | xargs -r docker rm -f || true
docker system prune -af --volumes || true
rm -rf /opt/agomsaaf/current /opt/agomsaaf/releases/* || true
mkdir -p /opt/agomsaaf/releases
```

## Step 4: Deploy Bundle to VPS

```powershell
$passFile = Join-Path $env:TEMP 'agomsaaf_vps_pass.txt'
Set-Content -Path $passFile -Value '<PASSWORD>' -NoNewline
python ./scripts/deploy-bundle-to-vps.py `
  --host 141.11.211.21 `
  --user root `
  --action fresh `
  --bundle ./dist/agomsaaf-vps-bundle-$tag.tar.gz `
  --password-file $passFile `
  --timeout 180
$code=$LASTEXITCODE
Remove-Item $passFile -Force -ErrorAction SilentlyContinue
exit $code
```

For `with-local-sqlite`, change `--bundle` to the `-live` bundle.

## Step 5: Post-Deploy Verification

Minimum checks:

```bash
docker compose -p agomsaaf -f docker/docker-compose.vps.yml --env-file deploy/.env ps
curl -fsS http://127.0.0.1:8000/api/health/
curl -fsS http://141.11.211.21:8000/api/health/
```

DB presence check (inside `web` container):

```bash
python - <<'PY'
import sqlite3
conn=sqlite3.connect('/app/data/db.sqlite3')
cur=conn.cursor()
cur.execute("select count(*) from auth_user")
print(cur.fetchone()[0])
conn.close()
PY
```

## Known Pitfall and Fix

If `web` stays `unhealthy` but app logs show `404 /health/`, healthcheck path is stale in old bundle compose file.  
Fix on VPS compose:

```bash
sed -i 's#http://127.0.0.1:8000/health/#http://127.0.0.1:8000/api/health/#g' docker/docker-compose.vps.yml
docker compose -p agomsaaf -f docker/docker-compose.vps.yml --env-file deploy/.env up -d web caddy
```
