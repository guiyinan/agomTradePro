---
name: mcp-remote-agomtradepro
description: "Connect to a remote AgomTradePro VPS through the current MCP/SDK contract. Use when querying regime, policy, signal, or data-center APIs, or when validating remote production behavior."
---

# MCP Remote AgomTradePro Connection

## Overview

Use this skill when a task needs to inspect or operate against a remote AgomTradePro VPS by HTTP API or MCP tooling. The canonical external contract is the current `/api/*` surface exposed by the production app, not legacy pre-cutover aliases.

## Connection Info

- **Base URL**: `http://your-vps-ip:8000`
- **Health**: `GET /api/health/`
- **Readiness**: `GET /api/ready/`
- **API root**: `GET /api/`
- **Data Center root**: `GET /api/data-center/`

## Authentication

- The external token value is the `key` field of `UserAccessTokenModel`.
- Header format remains:

```bash
Authorization: Token <user_access_token_key>
```

- Recommended shell setup:

```bash
export AGOM_REMOTE_API_TOKEN="<UserAccessTokenModel.key>"
export AGOM_REMOTE_BASE_URL="http://your-vps-ip:8000"
```

- Read-only tokens may call `GET/HEAD/OPTIONS` only. Write APIs require a read-write token and still pass normal role checks.

## Canonical Endpoints

### Core probes

```bash
curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/health/"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/ready/"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/"
```

### Regime / Policy

```bash
curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/regime/current/"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/policy/status/"
```

### Signals

```bash
curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/signal/"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/signal/active/"
```

### Data Center

```bash
curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/data-center/"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/data-center/indicators/"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/data-center/macro/series/?indicator_code=CN_PMI"

curl -s -H "Authorization: Token $AGOM_REMOTE_API_TOKEN" \
  "$AGOM_REMOTE_BASE_URL/api/data-center/prices/quotes/?asset_code=510300.SH"
```

## Python Client Skeleton

```python
import os
import requests


class AgomTradeProClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ["AGOM_REMOTE_BASE_URL"]).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Token {token or os.environ['AGOM_REMOTE_API_TOKEN']}"}
        )

    def _get(self, endpoint: str, **params):
        response = self.session.get(f"{self.base_url}{endpoint}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def health(self):
        return self._get("/api/health/")

    def readiness(self):
        return self._get("/api/ready/")

    def api_root(self):
        return self._get("/api/")

    def get_current_regime(self):
        return self._get("/api/regime/current/")

    def get_policy_status(self):
        return self._get("/api/policy/status/")

    def list_signals(self, **params):
        return self._get("/api/signal/", **params)

    def list_indicators(self, **params):
        return self._get("/api/data-center/indicators/", **params)

    def get_macro_series(self, indicator_code: str, **params):
        return self._get("/api/data-center/macro/series/", indicator_code=indicator_code, **params)

    def get_quote(self, asset_code: str):
        return self._get("/api/data-center/prices/quotes/", asset_code=asset_code)
```

## MCP Server Environment

When wiring the local SDK/MCP runtime to a remote VPS, keep these environment variables aligned:

```json
{
  "AGOMTRADEPRO_BASE_URL": "http://your-vps-ip:8000",
  "AGOMTRADEPRO_API_TOKEN": "${AGOM_REMOTE_API_TOKEN}",
  "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true"
}
```

The MCP audit client derives `/api/audit/internal/operation-logs/` from
`AGOMTRADEPRO_BASE_URL` and authenticates the audit write with the same user
access token. `AGOMTRADEPRO_AUDIT_URL` remains available only when audit ingest
is hosted at a different origin. Do not distribute `AUDIT_INTERNAL_SECRET_KEY`
to remote user clients; it is reserved for trusted service-to-service HMAC.

## Contract Notes

- Use `/api/signal/`, not legacy `/api/signals/`.
- Use `/api/data-center/*`, not legacy `/api/macro/*` discovery paths.
- Prefer API root discovery before hardcoding subpaths in diagnostics.
- If a remote environment is intentionally SQLite-backed, treat that as deployment policy unless the task is specifically about database migration.

## Troubleshooting

1. `401 Unauthorized`
   - Verify the token came from `UserAccessTokenModel.key`.
   - Confirm the user is active and `mcp_enabled` is still on.

2. `403 Forbidden`
   - The token may be read-only while the request is a write.
   - The user account may lack the required app permission.

3. `404 Not Found`
   - Re-check the endpoint against `GET /api/` or `GET /api/data-center/`.
   - Do not assume old aliases like `/api/signals/` or `/api/macro/supported-indicators/` still exist.
