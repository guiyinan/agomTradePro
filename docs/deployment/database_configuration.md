# AgomTradePro Database Strategy

> **Last updated**: `2026-07-05`
> **Release line**: `0.8.0`

---

## 1. Official recommendation

AgomTradePro now uses a **two-posture database strategy**:

| Posture | Database | Intended use |
|------|------|------|
| Local first-run / lightweight development | `SQLite` | fastest startup, demo, local feature work |
| Formal production | `PostgreSQL` | VPS deployment, sustained scheduler/runtime operation, formal readiness acceptance |

### Formal 0.8.0 production database posture

For any environment that is called “production” in `0.8.0`, the recommended primary database is:

```text
PostgreSQL 15+
```

SQLite on VPS remains acceptable only for:

- one-off demo environments
- explicit snapshot seed / restore workflows
- short diagnostic runs
- legacy migration handoff

It is no longer the formal production recommendation.

## 2. Why PostgreSQL is the production default

- better write concurrency than SQLite
- safer fit for Celery worker + beat + web shared runtime
- clearer backup / restore / migration posture
- aligns with readiness evidence persistence and sustained scheduler verification

## 3. Local-first posture

You do **not** need PostgreSQL to run the system locally for the first time.

Default local path:

```bash
python manage.py bootstrap_local_env
python manage.py migrate
python manage.py runserver
```

If `DATABASE_URL` is unset, the project can use local SQLite for the lightweight path.

## 4. Formal production checklist

### Required components

- PostgreSQL 15+
- Redis 7+
- Celery worker
- Celery beat
- persisted application data paths:
  - database storage
  - `var/readiness-evidence/`
  - media/log/audit artifacts as applicable

### Expected connection variables

```env
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>
REDIS_URL=redis://<host>:6379/0
```

## 5. PostgreSQL verification commands

```bash
# Connectivity
python manage.py migrate

# App health
python manage.py healthcheck --json

# Runtime acceptance
python manage.py show_personal_readiness_status --json --strict-monitor --require-local-scheduler-runtime
```

Docker-hosted PostgreSQL example:

```bash
docker exec -it <postgres_container> pg_isready -U <user>
docker exec -it <postgres_container> psql -U <user> -d <database>
```

## 6. SQLite usage policy

### Allowed

- local development
- first-run preview
- feature work without Redis/Celery
- explicit SQLite export/import bundle workflows

### Not recommended as formal production

- long-running VPS scheduler acceptance
- formal release sign-off
- sustained concurrent web/worker/beat operation

## 7. Migration posture

If an environment currently uses SQLite and is being promoted to formal production:

1. freeze the environment
2. export the data
3. import into PostgreSQL
4. point `DATABASE_URL` to PostgreSQL
5. rerun migrations and health checks
6. rerun readiness/runtime verification

## 8. Related docs

- [VPS Bundle Deployment](VPS_BUNDLE_DEPLOYMENT.md)
- [Operations Runbook](../operations/runbook.md)
- [System Baseline](../governance/SYSTEM_BASELINE.md)

