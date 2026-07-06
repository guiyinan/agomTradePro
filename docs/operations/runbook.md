# AgomTradePro Operations Runbook

> **Last updated**: `2026-07-05`
> **Release line**: `0.8.0`

---

## 1. What this runbook standardizes

This runbook defines the official `0.8.0` operator flow for:

- `task_monitor`
- readiness evidence
- scheduler verification
- local strict acceptance
- VPS scheduler-clean acceptance

The goal is to replace ad-hoc operator memory with fixed commands, fixed evidence paths, and fixed pass conditions.

## 2. Standard evidence artifacts

### Evidence location

```text
var/readiness-evidence/
```

Expected file pair per target trading day:

- `YYYY-MM-DD-personal-readiness.json`
- `YYYY-MM-DD-personal-readiness.md`

### Primary inspection commands

```bash
python manage.py show_personal_readiness_status --json
python manage.py inspect_personal_readiness_evidence --target-date <YYYY-MM-DD> --json
python manage.py validate_personal_readiness_window --json
```

## 3. Local strict acceptance

Use this when validating the local runtime as a release candidate or daily decision workstation.

### Standard commands

```bash
python manage.py setup_personal_readiness_daily
python manage.py init_scheduler_defaults

powershell -ExecutionPolicy Bypass -File scripts/check-personal-readiness-monitor.ps1 -SummaryOnly
powershell -ExecutionPolicy Bypass -File scripts/check-personal-readiness-monitor.ps1 -StrictAcceptance
```

### Local pass conditions

- readiness monitor stays green before the scheduled window
- strict acceptance passes only when the formal gate is truly accepted
- worker/beat runtime proof is visible
- quote pre-refresh and daily evidence schedule are post-close and safe
- latest formal evidence is readable and attributable

## 4. VPS scheduler-clean acceptance

Use this when validating the production-like sustained run on VPS.

### Standard operator flow

1. Confirm beat, worker, and queues are alive.
2. Confirm the readiness schedule is safe.
3. Let scheduler-owned quote pre-refresh and daily evidence run.
4. Re-check that the latest formal evidence advanced with `source=scheduler`.
5. Confirm the scheduler-clean suffix advanced without manual formal evidence.

### Standard commands

```bash
powershell -ExecutionPolicy Bypass -File scripts/check-personal-readiness-monitor.ps1 -SummaryOnly
python manage.py show_personal_readiness_status --json --strict-monitor --require-local-scheduler-runtime
python manage.py inspect_personal_readiness_evidence --target-date <latest_closed_trade_date> --json
python manage.py validate_personal_readiness_window --json
```

### Scheduler-clean rules

- do not use manual formal readiness evidence during a normal scheduler-clean day
- `run_personal_readiness_daily` is for explicit backfill/diagnosis, not normal proof generation
- the accepted evidence chain must remain continuous

## 5. Standard failure triage

### Scheduler safety or runtime issue

```bash
python manage.py show_personal_readiness_status --json --strict-monitor --require-local-scheduler-runtime
```

Check:

- worker/beat presence
- scheduler timezone/day-of-week/post-close timing
- queue routing drift
- one-off/expiry/headers/args drift

### Evidence file exists but failed

```bash
python manage.py inspect_personal_readiness_evidence --target-date <blocked_date> --json
```

### Evidence missing for closed trading day

```bash
python manage.py validate_personal_readiness_window --json
```

If the day should already have been produced and the scheduler missed it, repair scheduler/runtime first before considering manual backfill.

## 6. Task Monitor surfaces

### Preferred daily entry

```text
/ops/task-monitor/readiness/
```

Use this for:

- readiness monitor summary
- schedule controls
- lightweight operations status

### Full operations entry

```text
/ops/task-monitor/
```

Use this when you need:

- full `PeriodicTask` catalog
- Celery inspect output
- recent task failures

## 7. Production persistence expectations

Formal `0.8.0` production assumes:

- PostgreSQL as the primary database
- Redis for queue/cache runtime
- persisted `var/readiness-evidence/`
- persisted media/log/audit artifacts as applicable

SQLite on VPS is a transitional or diagnostic posture only.

## 8. Release sign-off checklist

The release-closure path is considered complete only when all of the following are true:

1. Version/docs/build metadata are aligned on `0.8.0`.
2. `task_monitor` is no longer documented as unfinished.
3. Local strict acceptance is repeatable from standard commands.
4. VPS scheduler-clean acceptance is repeatable from standard commands.
5. Production database posture is explicit and non-conflicting.
6. Evidence files and pass/fail conditions are documented and inspectable.

## 9. Related docs

- [../VERSION.md](../VERSION.md)
- [../governance/SYSTEM_BASELINE.md](../governance/SYSTEM_BASELINE.md)
- [../deployment/database_configuration.md](../deployment/database_configuration.md)
- [../testing/personal-investment-readiness-2026-06-30.md](../testing/personal-investment-readiness-2026-06-30.md)
