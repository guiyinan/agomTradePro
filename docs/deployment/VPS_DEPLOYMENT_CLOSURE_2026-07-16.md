# VPS Deployment Closure (2026-07-16)

## Objective

Harden the personal-demo VPS release path while retaining SQLite, the existing
Docker volumes, and the current encryption key. Normal releases use a single
`agomtradepro` Compose project and a maintenance window of no more than five
minutes.

## Completed implementation

- TUI runtime integrity is content-addressed by file SHA and `build_id`; the
  recorded upstream commit is provenance and must be a valid ancestor.
- The one-click entry point runs `npm ci`, the TUI integrity check, and the TUI
  JavaScript suite before opening an SSH connection.
- Normal deployment no longer requests global Docker cleanup. The destructive
  `--wipe-docker` path remains an explicit emergency option.
- A release is built under `/opt/agomtradepro/releases`, labeled with its source
  commit, and reported with Git SHA, image ID, image label, and build time.
- Before service replacement, SQLite is copied with the online backup API,
  checked with `PRAGMA integrity_check`, compressed, and persisted under
  `/opt/agomtradepro/backups/database`. Redis, secrets, and deployment metadata
  are included in the pre-deploy backup set.
- Release symlinks are replaced atomically. Deployment failures and mandatory
  post-deploy acceptance failures restore the recorded previous release.
- Backup and secret directories use mode `700`; secret, environment, and backup
  files use mode `600` on the Linux host.
- Web and Celery Beat memory defaults are 1 GiB and 512 MiB. Acceptance warns
  above 80% and fails above 95%, after OOM, or after an unexpected restart.
- Task history uses 30-day success/revoked and 90-day failure/timeout retention,
  converts active records older than seven days to timeout, and deletes in
  batches of 2,000. Daily backup is 03:00 and cleanup is 04:00.
- Macro sync exposes `success | partial | failure` semantics. Partial macro and
  repeated quote degradation create aggregated Task Monitor alerts through an
  Application facade.

## Release acceptance

The release is accepted only when all of the following hold:

- local TUI checks and the required CI workflows are green;
- deployed Git SHA equals the image OCI source label and the requested commit;
- HTTPS is 2xx and the certificate remains valid for at least 21 days;
- Django deploy checks, migrations, Qlib identity, Celery services, and Celery
  ping pass;
- secrets and backups have the required permissions and a verified database
  backup is no older than 26 hours;
- Web and Beat have no OOM/restart evidence and remain below the critical memory
  threshold;
- Alpha and task-history freshness checks use Django model metadata and pass.

## Rollback points and remaining risk

Each release retains the previous release path, image reference, environment
snapshot, and pre-deploy backup. Automatic rollback reactivates the previous
Compose release and rechecks local health and Celery. Database migrations in this
phase are intentionally absent; any future destructive migration requires a
separate rollout and restore drill.

The remaining operational risks are external provider outages and the intrinsic
write-concurrency limits of SQLite. These are acceptable for the personal-demo
environment and are surfaced as degraded/blocked alerts rather than silently
treated as healthy data.
