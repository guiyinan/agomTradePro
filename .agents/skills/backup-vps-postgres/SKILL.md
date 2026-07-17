---
name: backup-vps-postgres
description: "Create a verified custom-format PostgreSQL backup on the AgomTradePro VPS and download it to the local workspace over SFTP with SHA-256 verification. Use when the user asks to back up the VPS database, download a production database backup, fetch the latest PostgreSQL dump, verify a remote backup, or prune old PostgreSQL dump files. Chinese triggers: 备份VPS数据库, 下载数据库备份, PostgreSQL备份, 拉取最新备份, 清理旧数据库备份."
---

# Back Up VPS PostgreSQL

Use the repository entry point `scripts/backup-vps-postgres.ps1`. It reads the VPS target and password from environment variables, creates a PostgreSQL custom-format archive inside the running production container, validates it remotely, downloads it atomically, and verifies its SHA-256 locally.

## Workflow

1. Work from the repository root and run `git status --short`. Preserve unrelated changes.
2. Require `AGOM_VPS_HOST` and `AGOM_VPS_PASS`. Read optional user, port, and target directory from `AGOM_VPS_USER`, `AGOM_VPS_PORT`, and `AGOM_VPS_TARGET_DIR`.
3. Run the default backup command:

```powershell
.\scripts\backup-vps-postgres.ps1
```

4. Confirm the script reports the remote archive path, local archive path, byte size, and matching SHA-256.
5. Report the retained remote path and downloaded local path to the user.

## Common Operations

Download and revalidate the newest existing remote backup without creating another dump:

```powershell
.\scripts\backup-vps-postgres.ps1 -DownloadLatest
```

Choose a local destination:

```powershell
.\scripts\backup-vps-postgres.ps1 -OutputDir D:\Backups\AgomTradePro
```

Prune only remote `postgres-*.dump` files older than a chosen age after a successful backup:

```powershell
.\scripts\backup-vps-postgres.ps1 -PruneRemoteOlderThanDays 30
```

Do not enable pruning unless the user explicitly requests retention cleanup.

## Safety Contract

- Never write `AGOM_VPS_PASS`, database passwords, Django secrets, or encryption keys into the repository or command output.
- Never use `docker volume prune`, delete the PostgreSQL volume, or stop the database for a logical backup.
- Keep the remote archive by default. Local output defaults to the Git-ignored `backups/vps-postgres/` directory.
- Treat restore as a separate destructive workflow. Never restore a dump unless the user explicitly requests it and confirms the target.
- A backup is successful only after remote `pg_restore --list`, complete SFTP download, size comparison, and local SHA-256 comparison all pass.

## Expected Report

- Operation: created a new dump or downloaded the latest existing dump.
- Remote archive path and whether retention pruning was disabled or enabled.
- Local clickable archive path and checksum file path.
- Archive size and SHA-256 result.
- Any unverified item or failure; never describe a partial download as a successful backup.
