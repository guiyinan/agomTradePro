# remote-build-deploy-vps.ps1

PowerShell wrapper for `remote_build_deploy_vps.py`.

Purpose:

- Upload current source tree to a Linux VPS
- Build Docker image on the VPS
- Download the built image tar back to local machine
- Ask for confirmation before deploying to the VPS
- Optionally include local `db.sqlite3`

## Quick Start

Show help:

```powershell
pwsh ./scripts/remote-build-deploy-vps.ps1 -Help
```

Typical usage:

```powershell
pwsh ./scripts/remote-build-deploy-vps.ps1 `
  -Host 141.11.211.21 `
  -User root `
  -PasswordFile "$HOME\.agomsaaf\vps.pass" `
  -Action upgrade `
  -HttpPort 8000
```

Default wrapper behavior:

- Download built image tar back to local machine
- Prompt again before remote deployment

Built image tar is saved under:

- `dist/remote-built-images/`

First-time deploy with local SQLite and full Docker cleanup:

```powershell
pwsh ./scripts/remote-build-deploy-vps.ps1 `
  -Host 141.11.211.21 `
  -User root `
  -PasswordFile "$HOME\.agomsaaf\vps.pass" `
  -Action fresh `
  -IncludeSqlite `
  -WipeDocker `
  -HttpPort 8000
```

Build and download only, do not deploy:

```powershell
pwsh ./scripts/remote-build-deploy-vps.ps1 `
  -Host 141.11.211.21 `
  -User root `
  -PasswordFile "$HOME\.agomsaaf\vps.pass" `
  -SkipDeployAfterBuild
```

## Common Parameters

- `-Host`: VPS IP or domain
- `-Port`: SSH port, default `22`
- `-User`: SSH username
- `-PasswordFile`: text file containing SSH password
- `-Action`: `fresh` or `upgrade`
- `-HttpPort`: public HTTP port on VPS, default `8000`
- `-IncludeSqlite`: include local `db.sqlite3` in upload bundle
- `-WipeDocker`: remove existing Docker containers/images/volumes before deploy
- `-Domain`: optional domain for Caddy
- `-AllowedHosts`: optional Django `ALLOWED_HOSTS`
- `-EnableCelery`: enable celery services on VPS
- `-DisableRsshub`: disable built-in RSSHub service
- `-BuiltImageDir`: local directory for downloaded image tar
- `-SkipDeployAfterBuild`: build and download only, skip VPS deployment
- `-NoDownloadBuiltImage`: do not download built image tar
- `-NoPromptBeforeDeploy`: skip second confirmation and deploy directly

## Notes

- `-Host` is supported as an alias. Internally the PowerShell script avoids direct use of the built-in `$Host` variable.
- If you omit key arguments, the underlying Python script may prompt interactively.
- The actual remote build/deploy logic lives in `remote_build_deploy_vps.py`.
