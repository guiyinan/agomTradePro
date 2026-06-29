---
name: vps-hot-update-agomtradepro
description: Hot update selected AgomTradePro files on the production VPS without a full Docker rebuild or database restore. Use when the user asks to "热更新", "单独更新这几个文件", "只同步模板/CSS/JS", "更新到 VPS 但不重建", or to patch running Django templates/static assets such as core/templates, static/css, static/js, or other code-only files.
---

# AgomTradePro VPS Hot Update

Use this skill for small, code-only VPS patches where a full `vps-deploy-agomtradepro` rebuild is unnecessary. The workflow uploads selected local files to `/opt/agomtradepro/current`, backs up the remote originals, copies changed files into the running `web` container, refreshes the collected static volume for `static/...` files, restarts only `web` by default, and verifies HTTPS health.

## Boundaries

- Do not use this for dependency changes, migrations, Dockerfile/compose changes, database restore, or broad deploys. Use `vps-deploy-agomtradepro` instead.
- Do not overwrite SQLite or Docker volumes except the staticfiles volume path for matching `static/...` assets.
- Do not store VPS passwords, keys, API tokens, or generated temporary auth files in the repository.
- Require `AGOM_VPS_HOST` and `AGOM_VPS_PASS`. Default `AGOM_VPS_USER=root`, `AGOM_VPS_PORT=22`, `AGOM_VPS_TARGET_DIR=/opt/agomtradepro`.
- Work from the repository root and run `git status --short` first. Do not revert unrelated local changes.

## Quick Start

Run the bundled script from the repo root:

```powershell
python .agents/skills/vps-hot-update-agomtradepro/scripts/hot_update_files.py `
  core/templates/terminal/tui_workbench.html `
  static/css/tui-workbench.css `
  --expect-substring 'core/templates/terminal/tui_workbench.html::href="/terminal/"' `
  --expect-substring 'static/css/tui-workbench.css::tui-status-link'
```

For templates or Python files, the script copies the file into `/app/<relative-path>` inside `agomtradepro-web-1`. For `static/...` files, it also updates `/var/lib/docker/volumes/agomtradepro_static_data/_data/<path-without-static-prefix>`.

## Workflow

1. Check local status:

   ```powershell
   git status --short -- <files>
   ```

2. Confirm environment variables without printing secrets:

   ```powershell
   $env:AGOM_VPS_HOST
   if ($env:AGOM_VPS_PASS) { "AGOM_VPS_PASS=SET" }
   ```

3. Run `scripts/hot_update_files.py` with explicit file paths and any expected substrings.

4. Verify the script output includes:
   - `backup_dir=...`
   - matching release/container/static checks
   - HTTPS health `200`
   - running container state

5. If the user still sees stale UI, update the template asset version query string or ask them to force refresh. For Django templates, restart `web`; the script does this unless `--no-restart-web` is passed.

## Useful Options

- `--no-restart-web`: upload and copy files without restarting `web`. Use only for assets that do not need Django/Gunicorn cache invalidation.
- `--domain demo.agomtrade.pro`: public domain for HTTPS verification.
- `--expect-substring path::text`: assert local, remote release, and container/static copies contain a marker.
- `--target-dir /opt/agomtradepro`: override remote app root.
- `--container agomtradepro-web-1`: override web container name.

## Reporting

Tell the user:

- deployed mode: `hot-update code-only`
- changed files
- remote backup directory
- whether `web` was restarted
- public HTTPS health result
- whether template/static markers were verified
- running container state
