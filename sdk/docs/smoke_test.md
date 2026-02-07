# AgomSAAF SDK/MCP Smoke Test

This checklist verifies that the local backend, SDK, and MCP server work end-to-end.

## 1. Prerequisites

- Django service can start (`python manage.py runserver 127.0.0.1:8000 --noreload`)
- PostgreSQL is reachable by project settings
- SDK installed:

```bash
cd D:/githv/agomSAAF/sdk
pip install -e .
```

## 2. Prepare Token

Generate or fetch a DRF token for an active user:

```bash
cd D:/githv/agomSAAF
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

Set env vars:

```bash
set AGOMSAAF_BASE_URL=http://127.0.0.1:8000
set AGOMSAAF_API_TOKEN=<paste_token_here>
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
```

If you prefer UI management, as admin open `/account/admin/tokens/` and generate/rotate token there.

## 3. Health Check

```bash
python -c "import requests; print(requests.get('http://127.0.0.1:8000/health/', timeout=8).status_code)"
```

Expected: `200`

## 4. SDK Smoke

```bash
python -c "from agomsaaf import AgomSAAFClient; c=AgomSAAFClient(); print(type(c.regime.get_current()).__name__); print(type(c.policy.get_status()).__name__); print(len(c.signal.list(limit=5)))"
```

Expected:
- `RegimeState`
- `PolicyStatus`
- signal list length prints a number

## 5. MCP Smoke

```bash
python -c "import asyncio; from agomsaaf_mcp.server import server; async def main(): print(len(await server.list_tools())); print(type(await server.call_tool('get_current_regime', {})).__name__); print(type(await server.call_tool('list_signals', {})).__name__); asyncio.run(main())"
```

Expected:
- tool count > 0
- tool calls return successfully

## 6. Troubleshooting

- `401 Authentication failed`: token missing/invalid; regenerate token.
- `404 Resource not found`: SDK route mismatch or endpoint not mounted.
- `503` or connection refused: backend/db not ready.
- Requests routed via proxy: ensure `NO_PROXY` contains `127.0.0.1,localhost`.
