# Setup And Auth

Use this reference when the agent needs to configure or verify MCP/SDK access.

## Install

From the project root:

```bash
cd D:/githv/agomTradePro/sdk
pip install -e .
```

Recommended versions from project docs:

- Python `>=3.11`
- `mcp>=1.20,<2`

Verify:

```bash
python -m pip show agomtradepro-sdk mcp
```

## Required environment

- `AGOMTRADEPRO_BASE_URL`
- `AGOMTRADEPRO_API_TOKEN` preferred
- Or `AGOMTRADEPRO_USERNAME` + `AGOMTRADEPRO_PASSWORD`
- `AGOMTRADEPRO_DEFAULT_ACCOUNT_ID` optional

If localhost traffic is affected by proxy settings:

```bash
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
```

## Token generation

For a local Django environment:

```bash
cd D:/githv/agomTradePro
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

UI alternative from project docs:

- `/account/admin/tokens/`

## Claude Code MCP config

Preferred MCP server shape:

```json
{
  "mcpServers": {
    "agomtradepro": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "D:/githv/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://localhost:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true"
      }
    }
  }
}
```

Important notes:

- `sdk/.mcp/claude-desktop-config.json` currently uses `AGOMTRADEPRO_API_BASE_URL`; project docs consistently use `AGOMTRADEPRO_BASE_URL`.
- `sdk/agomtradepro_mcp/__main__.py` and `sdk/agomtradepro_mcp/server.py` are the implementation sources to trust over stale examples.

## RBAC

Recommended defaults from `docs/mcp/mcp_guide.md`:

- `AGOMTRADEPRO_MCP_ENFORCE_RBAC=true`
- Prefer backend-derived role over hardcoding `AGOMTRADEPRO_MCP_ROLE`
- Optional override: `AGOMTRADEPRO_MCP_ROLE=<role>`
- Optional source: `AGOMTRADEPRO_MCP_ROLE_SOURCE=backend`
- Optional fallback: `AGOMTRADEPRO_MCP_DEFAULT_ROLE=read_only`

Supported roles called out in docs:

- `admin`
- `owner`
- `analyst`
- `investment_manager`
- `trader`
- `risk`
- `read_only`

## Smoke checks

### MCP registration

```bash
cd D:/githv/agomTradePro/sdk
python -c "import asyncio; from agomtradepro_mcp.server import server; print(len(asyncio.run(server.list_tools())))"
```

### SDK connectivity

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here",
)

print(client.regime.get_current())
```

### Minimal MCP tool probe

Ask the agent to call one read tool first:

- `get_current_regime`
- `get_policy_status`
- `list_signals`

If these fail, fix auth/config before attempting writes.
