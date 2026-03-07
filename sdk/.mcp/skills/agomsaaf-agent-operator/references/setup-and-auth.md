# Setup And Auth

Use this reference when the agent needs to configure or verify MCP/SDK access.

## Install

From the project root:

```bash
cd D:/githv/agomSAAF/sdk
pip install -e .
```

Recommended versions from project docs:

- Python `>=3.11`
- `mcp>=1.20,<2`

Verify:

```bash
python -m pip show agomsaaf-sdk mcp
```

## Required environment

- `AGOMSAAF_BASE_URL`
- `AGOMSAAF_API_TOKEN` preferred
- Or `AGOMSAAF_USERNAME` + `AGOMSAAF_PASSWORD`
- `AGOMSAAF_DEFAULT_PORTFOLIO_ID` optional

If localhost traffic is affected by proxy settings:

```bash
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
```

## Token generation

For a local Django environment:

```bash
cd D:/githv/agomSAAF
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

UI alternative from project docs:

- `/account/admin/tokens/`

## Claude Code MCP config

Preferred MCP server shape:

```json
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "http://localhost:8000",
        "AGOMSAAF_API_TOKEN": "your_token_here",
        "AGOMSAAF_MCP_ENFORCE_RBAC": "true"
      }
    }
  }
}
```

Important notes:

- `sdk/.mcp/claude-desktop-config.json` currently uses `AGOMSAAF_API_BASE_URL`; project docs consistently use `AGOMSAAF_BASE_URL`.
- `sdk/agomsaaf_mcp/__main__.py` and `sdk/agomsaaf_mcp/server.py` are the implementation sources to trust over stale examples.

## RBAC

Recommended defaults from `docs/mcp/mcp_guide.md`:

- `AGOMSAAF_MCP_ENFORCE_RBAC=true`
- Prefer backend-derived role over hardcoding `AGOMSAAF_MCP_ROLE`
- Optional override: `AGOMSAAF_MCP_ROLE=<role>`
- Optional source: `AGOMSAAF_MCP_ROLE_SOURCE=backend`
- Optional fallback: `AGOMSAAF_MCP_DEFAULT_ROLE=read_only`

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
cd D:/githv/agomSAAF/sdk
python -c "import asyncio; from agomsaaf_mcp.server import server; print(len(asyncio.run(server.list_tools())))"
```

### SDK connectivity

```python
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient(
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
