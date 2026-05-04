# AgomTradePro SDK/MCP Smoke Test

This checklist verifies that the local backend, SDK, and MCP server work end-to-end.

## 1. Prerequisites

- Django service can start (`python manage.py runserver 127.0.0.1:8000 --noreload`)
- PostgreSQL is reachable by project settings
- SDK installed:

```bash
cd sdk
pip install -e .
```

## 2. Prepare Token

Generate or fetch a DRF token for an active user:

```bash
cd .
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='sdk-smoke'); print(key)"
```

Set env vars:

#### Windows PowerShell

```powershell
$env:AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
$env:AGOMTRADEPRO_API_TOKEN="<paste_token_here>"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
```

#### Linux/macOS (bash)

```bash
export AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
export AGOMTRADEPRO_API_TOKEN="<paste_token_here>"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
```

If you prefer UI management, as admin open `/account/admin/tokens/` and generate/rotate token there.

## 3. Health Check

```bash
python -c "import requests; print(requests.get('http://127.0.0.1:8000/api/health/', timeout=8).status_code)"
```

Expected: `200`

## 4. SDK Smoke

```bash
python -c "from agomtradepro import AgomTradeProClient; c=AgomTradeProClient(); print(type(c.regime.get_current()).__name__); print(type(c.policy.get_status()).__name__); print(len(c.signal.list(limit=5)))"
```

Expected:
- `RegimeState`
- `PolicyStatus`
- signal list length prints a number

## 5. MCP Smoke

```bash
python -c "import asyncio; from agomtradepro_mcp.server import server; async def main(): print(len(await server.list_tools())); print(type(await server.call_tool('get_current_regime', {})).__name__); print(type(await server.call_tool('list_signals', {})).__name__); asyncio.run(main())"
```

Expected:
- tool count > 0
- tool calls return successfully

## 6. Fund Research Smoke

Use the dedicated local smoke script when you need to verify the canonical fund
research chain end-to-end across HTTP API, SDK, and MCP:

```bash
cd D:/githv/agomTradePro
python scripts/run_fund_research_smoke.py --auto-token-user admin
```

Optional:

```bash
python scripts/run_fund_research_smoke.py --api-token <token> --report-json reports/fund-smoke.json
```

What it verifies:

- current regime resolution
- `/api/fund/rank/`
- `/api/fund/screen/`
- `/api/fund/info/{fund_code}/`
- `/api/fund/nav/{fund_code}/`
- `/api/fund/holding/{fund_code}/`
- `/api/fund/performance/calculate/`
- `client.fund.rank_funds()` / `screen_funds()` / `get_fund_detail()` / `get_nav_history()` / `get_holdings()` / `get_performance()`
- MCP `rank_funds` / `screen_funds` / `get_fund_detail` / `get_fund_nav_history` / `get_fund_holdings` / `get_fund_performance`

The script auto-discovers a real local holding sample from Django ORM, so it can
use an actually existing `fund_code + report_date` pair instead of hardcoding a stale report date.

## 7. Troubleshooting

- `401 Authentication failed`: token missing/invalid; regenerate token.
- `404 Resource not found`: SDK route mismatch or endpoint not mounted.
- `503` or connection refused: backend/db not ready.
- Requests routed via proxy: ensure `NO_PROXY` contains `127.0.0.1,localhost`.
- `Fund API rank returned no candidates`: first check whether the local runserver is using the latest code and whether fund research data has been prepared.
- `No fund holding sample found in local database`: seed or sync fund holdings before expecting holding smoke to pass.
