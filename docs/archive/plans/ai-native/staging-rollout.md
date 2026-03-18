# AI-Native Agent Runtime - Staging Rollout Guide

> **Version**: M4 Release
> **Date**: 2026-03-16

## 1. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_SETTINGS_MODULE` | Yes | `core.settings.development` | Use `core.settings.production` for staging |
| `DATABASE_URL` | Yes | SQLite | PostgreSQL connection string for staging |
| `AGOMSAAF_BASE_URL` | Yes | `http://127.0.0.1:8000` | Base URL of the staging server |
| `AGOMSAAF_API_TOKEN` | Yes | — | Staff-level API token |
| `AGOMSAAF_MCP_ENFORCE_RBAC` | No | `true` | Enable RBAC enforcement on MCP tools |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/0` | Redis broker for async tasks |
| `SECRET_KEY` | Yes | — | Django secret key (must not be default) |

## 2. RBAC Defaults

The agent runtime respects existing Django permission groups:

| Group | Permissions |
|-------|-------------|
| `staff` | Full read/write on tasks, proposals, dashboard |
| `operator` | Read all, write tasks, approve/reject proposals |
| `agent` | Create tasks, create proposals, read own data |
| `viewer` | Read-only access to dashboard |

Default setup:
```bash
python manage.py shell -c "
from django.contrib.auth.models import Group
for name in ['operator', 'agent', 'viewer']:
    Group.objects.get_or_create(name=name)
print('Groups created.')
"
```

## 3. Feature Flags

The agent runtime uses no external feature flag system. Behavior is controlled via:

| Setting | Location | Default | Description |
|---------|----------|---------|-------------|
| `AGENT_RUNTIME_ENABLED` | `core/settings/base.py` | `True` | Master switch for agent runtime API |
| `GUARDRAIL_STRICT_MODE` | Guardrail engine | `True` | Block on any gate failure vs. degrade |
| `PROPOSAL_AUTO_APPROVE_LOW_RISK` | Proposal use case | `False` | Auto-approve low-risk proposals |

To disable the runtime without removing code:
```python
# core/settings/staging.py
AGENT_RUNTIME_ENABLED = False
```

## 4. Migration Procedure

### Pre-migration checklist
- [ ] Database backup completed
- [ ] Current schema version noted (`python manage.py showmigrations agent_runtime`)
- [ ] Staging environment variables set

### Steps

```bash
# 1. Pull latest code
git pull origin main

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations
python manage.py migrate --run-syncdb

# 4. Verify migrations applied
python manage.py showmigrations agent_runtime

# 5. Create RBAC groups (if first deploy)
python manage.py shell -c "
from django.contrib.auth.models import Group
for name in ['operator', 'agent', 'viewer']:
    Group.objects.get_or_create(name=name)
"

# 6. Collect static files
python manage.py collectstatic --noinput

# 7. Start server
python manage.py runserver 0.0.0.0:8000
```

## 5. Rollback Steps

### Quick rollback (code only)
```bash
# Revert to previous release tag
git checkout <previous-tag>
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
```

### Full rollback (with migration revert)
```bash
# 1. Identify the last good migration
python manage.py showmigrations agent_runtime

# 2. Revert to specific migration
python manage.py migrate agent_runtime <migration_name>

# 3. Checkout previous code
git checkout <previous-tag>
pip install -r requirements.txt

# 4. Restart
python manage.py runserver 0.0.0.0:8000
```

### Data preservation
- Agent tasks, proposals, and timeline events are append-only
- Rollback does not delete existing records
- Guardrail decisions and execution records remain intact

## 6. Smoke Tests

Run after every staging deploy:

```bash
TOKEN="YOUR_STAGING_TOKEN"
BASE="http://staging-host:8000"

# 1. Health check
curl -s "$BASE/api/agent-runtime/health/" \
  -H "Authorization: Token $TOKEN" | python -m json.tool
# Expected: 200, {"status": "ok"}

# 2. Create a research task
TASK=$(curl -s -X POST "$BASE/api/agent-runtime/tasks/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_domain":"research","task_type":"smoke_test","input_payload":{"test":true}}')
echo "$TASK" | python -m json.tool
# Expected: 201, task with status "draft"

TASK_ID=$(echo "$TASK" | python -c "import sys,json; print(json.load(sys.stdin)['task']['id'])")

# 3. Get task timeline
curl -s "$BASE/api/agent-runtime/tasks/$TASK_ID/timeline/" \
  -H "Authorization: Token $TOKEN" | python -m json.tool
# Expected: 200, at least one event

# 4. Dashboard summary
curl -s "$BASE/api/agent-runtime/dashboard/summary/" \
  -H "Authorization: Token $TOKEN" | python -m json.tool
# Expected: 200, counts present

# 5. Create and approve a proposal
PROP=$(curl -s -X POST "$BASE/api/agent-runtime/proposals/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"proposal_type\":\"config_read\",\"risk_level\":\"low\",\"proposal_payload\":{\"test\":true},\"task_id\":$TASK_ID}")
echo "$PROP" | python -m json.tool
# Expected: 201

echo "=== Smoke tests completed ==="
```

## 7. Post-Deploy Verification

| Check | Command | Expected |
|-------|---------|----------|
| API responds | `curl /api/agent-runtime/health/` | 200 |
| Migrations applied | `python manage.py showmigrations agent_runtime` | All `[X]` |
| RBAC groups exist | `python manage.py shell -c "from django.contrib.auth.models import Group; print(Group.objects.filter(name__in=['operator','agent','viewer']).count())"` | 3 |
| Dashboard accessible | `curl /api/agent-runtime/dashboard/summary/` | 200 with counts |
| Task creation works | Smoke test #2 above | 201 |

## 8. Support Ownership

| Area | Owner | Escalation |
|------|-------|------------|
| Agent Runtime API | Backend team | On-call engineer |
| Guardrail Engine | Backend team | Tech lead |
| MCP Tools | SDK team | SDK maintainer |
| Dashboard | Frontend team | Product owner |
