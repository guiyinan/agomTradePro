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

### VPS database roles

The VPS Compose stack separates schema ownership, deployment migrations, and
application traffic. `agomtradepro_owner` is a `NOLOGIN` owner; the one-shot
`migrator` service receives `MIGRATOR_DATABASE_URL` and runs Django migrations
with `SET ROLE agomtradepro_owner`; web and Celery receive only
`DATABASE_URL` for `agomtradepro_runtime`. Runtime startup checks this identity
and the account-authority generation ACL before starting each web or worker
process. The generation trigger and lock functions must use exactly
`search_path=pg_catalog`.

| Role | Login | Intended permission |
|---|---:|---|
| `agomtradepro_owner` | No | Owns the 22 authority source tables and generation objects; has schema DDL rights. |
| `agomtradepro_migrator` | Yes | Has only `SET ROLE` membership in the owner role; its command wrapper accepts `migrate`, `flush`, and `loaddata` for deployment and SQLite snapshot import. |
| `agomtradepro_runtime` | Yes | Application DML on source tables, generation `SELECT`, and fence-lock wrapper `EXECUTE`; no owner membership or generation writes. |

The explicit role-membership options in the bootstrap require PostgreSQL 16;
the VPS Compose default is PostgreSQL 16. Do not apply this bootstrap to an
older external PostgreSQL server without first upgrading or providing an
equivalent reviewed migration.

The migrator sets the owner role on its PostgreSQL session before invoking
Django. Keep `MIGRATOR_DATABASE_URL` on a direct PostgreSQL connection or a
session-pooling endpoint; transaction-pooling endpoints do not preserve that
session role across migration statements.

The shared deployment helper preserves a configured non-placeholder,
URL-safe `POSTGRES_PASSWORD` of at least 32 characters, or generates a replacement
when it does not meet that contract, then persists it with distinct runtime and migrator
passwords in the protected VPS environment files. Remote deployment's already
generated admin password is reused unchanged. The bootstrap updates the current
`POSTGRES_USER` password and both role passwords inside its transaction so the
running database credentials match the persisted environment. The checked-in
example values are placeholders and are rejected by the bootstrap. The deployment helper waits for
PostgreSQL readiness, applies the role bootstrap with the admin connection, then
runs migrations through the one-shot migrator. The older `deploy-on-vps.sh`
path follows the same readiness, bootstrap, migrate, then runtime-start order.
For a manual operation, inspect first, then apply the role bootstrap:

```bash
bash scripts/bootstrap_vps_postgres_roles.sh /opt/agomtradepro --plan
bash scripts/bootstrap_vps_postgres_roles.sh /opt/agomtradepro --apply
docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env \
  --profile ops run --rm migrator
docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env \
  exec -T web python scripts/check_postgres_role_contract.py
```

Role bootstrap transfers public relations currently owned by `POSTGRES_USER`
to the owner role and resets generation ACLs if those objects exist. It rejects
the bootstrap if the runtime role still owns any public database object. It is
idempotent, but it changes object ownership and grants, so take a database
backup and review the plan output before applying it. During the bootstrap
maintenance window, disable PostgreSQL statement logging that records SQL
statement text; the admin and role-password update statements could otherwise
expose the new credentials in server logs. A reviewed secure credential-delivery
path for bootstrap remains follow-up work.

The SQLite snapshot import reads the source database through a web container
configured explicitly for SQLite, then runs PostgreSQL `flush` and `loaddata`
through the migrator manager. The manager rejects all commands outside its
`migrate`, `flush`, and `loaddata` allowlist.

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
