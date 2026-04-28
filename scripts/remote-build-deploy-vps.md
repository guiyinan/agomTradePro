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
  -Host your-vps-ip `
  -User root `
  -PasswordFile "$HOME\.agomtradepro\vps.pass" `
  -Action upgrade `
  -Domain your-domain.com
```

Default wrapper behavior:

- Download built image tar back to local machine
- Prompt again before remote deployment

Built image tar is saved under:

- `dist/remote-built-images/`

First-time deploy with local SQLite and full Docker cleanup:

```powershell
pwsh ./scripts/remote-build-deploy-vps.ps1 `
  -Host your-vps-ip `
  -User root `
  -PasswordFile "$HOME\.agomtradepro\vps.pass" `
  -Action fresh `
  -IncludeSqlite `
  -WipeDocker `
  -Domain your-domain.com
```

Build and download only, do not deploy:

```powershell
pwsh ./scripts/remote-build-deploy-vps.ps1 `
  -Host your-vps-ip `
  -User root `
  -PasswordFile "$HOME\.agomtradepro\vps.pass" `
  -SkipDeployAfterBuild
```

## Common Parameters

- `-Host`: VPS IP or domain
- `-Port`: SSH port, default `22`
- `-User`: SSH username
- `-PasswordFile`: text file containing SSH password
- `-Action`: `fresh` or `upgrade`
- `-HttpPort`: optional public HTTP port override. Leave unset to preserve the existing remote port, use `80` for a normal domain deployment, or fall back to `8000` for temporary IP-only access.
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
- Remote deploy now preserves the existing VPS `DOMAIN`, `ALLOWED_HOSTS`, and Caddy port mapping unless you explicitly override them.
