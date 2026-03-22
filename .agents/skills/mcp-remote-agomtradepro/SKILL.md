---
name: mcp-remote-agomtradepro
description: "Connect to remote VPS AgomTradePro system (your-vps-ip:8000) via MCP tools or direct API calls. Use when querying regime status, macro data, signals, backtest results, or managing account positions on the production system."
---

# MCP Remote AgomTradePro Connection

## Overview

Connect to the production AgomTradePro system on VPS using MCP (Model Context Protocol) or direct REST API calls. This skill enables querying macro regime, policy status, signals, backtest results, and managing account data on the remote system.

## Connection Info

- **VPS URL**: `http://your-vps-ip:8000`
- **API Token**: `28c11b3441d70f581c7410faeb5baeb90901c005`
- **Health Check**: `http://your-vps-ip:8000/api/health/`

## Verified API Endpoints

Based on actual testing, these endpoints are working:

### Core Endpoints
```bash
# Health check (returns {"status": "ok", ...})
curl -s -H "Authorization: Token 28c11b3441d70f581c7410faeb5baeb90901c005" \
  http://your-vps-ip:8000/api/health/

# Current regime (returns dominant_regime, confidence, etc.)
curl -s -H "Authorization: Token 28c11b3441d70f581c7410faeb5baeb90901c005" \
  http://your-vps-ip:8000/api/regime/current/

# Policy status (returns current_level, level_name, recommendations)
curl -s -H "Authorization: Token 28c11b3441d70f581c7410faeb5baeb90901c005" \
  http://your-vps-ip:8000/api/policy/status/

# List signals
curl -s -H "Authorization: Token 28c11b3441d70f581c7410faeb5baeb90901c005" \
  http://your-vps-ip:8000/api/signals/

# Supported macro indicators (52 indicators available)
curl -s -H "Authorization: Token 28c11b3441d70f581c7410faeb5baeb90901c005" \
  http://your-vps-ip:8000/api/macro/supported-indicators/

# API root (lists all available endpoints)
curl -s -H "Authorization: Token 28c11b3441d70f581c7410faeb5baeb90901c005" \
  http://your-vps-ip:8000/api/
```

## Current System State (2026-03-07)

```json
// Regime
{
  "dominant_regime": "Deflation",
  "confidence": 0.477,
  "observed_at": "2026-03-07",
  "source": "akshare"
}

// Policy
{
  "current_level": "P0",
  "level_name": "常态",
  "is_intervention_active": false,
  "is_crisis_mode": false
}
```

## Option 1: Direct API Calls (curl)

```bash
# Set token as variable for reuse
TOKEN="28c11b3441d70f581c7410faeb5baeb90901c005"
BASE="http://your-vps-ip:8000"

# Quick health check
curl -s -H "Authorization: Token $TOKEN" $BASE/api/health/

# Get regime
curl -s -H "Authorization: Token $TOKEN" $BASE/api/regime/current/ | python -m json.tool

# Get policy
curl -s -H "Authorization: Token $TOKEN" $BASE/api/policy/status/ | python -m json.tool

# Get macro indicators
curl -s -H "Authorization: Token $TOKEN" $BASE/api/macro/supported-indicators/ | python -m json.tool

# List signals
curl -s -H "Authorization: Token $TOKEN" $BASE/api/signals/ | python -m json.tool
```

## Option 2: Python Client

```python
import requests

class AgomTradeProClient:
    """Client for AgomTradePro VPS API"""

    def __init__(self, base_url="http://your-vps-ip:8000",
                 token="28c11b3441d70f581c7410faeb5baeb90901c005"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Token {token}"})

    def _get(self, endpoint):
        """Make GET request and return JSON"""
        resp = self.session.get(f"{self.base_url}{endpoint}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint, data=None):
        """Make POST request and return JSON"""
        resp = self.session.post(f"{self.base_url}{endpoint}", json=data, timeout=60)
        resp.raise_for_status()
        return resp.json()

    # Health
    def health(self):
        return self._get("/api/health/")

    # Regime
    def get_current_regime(self):
        return self._get("/api/regime/current/")

    def get_regime_history(self, start_date=None, end_date=None):
        params = []
        if start_date: params.append(f"start_date={start_date}")
        if end_date: params.append(f"end_date={end_date}")
        query = "&".join(params)
        return self._get(f"/api/regime/history/?{query}" if query else "/api/regime/history/")

    # Policy
    def get_policy_status(self):
        return self._get("/api/policy/status/")

    # Signals
    def list_signals(self, status=None, asset_code=None):
        params = []
        if status: params.append(f"status={status}")
        if asset_code: params.append(f"asset_code={asset_code}")
        query = "&".join(params)
        return self._get(f"/api/signals/?{query}" if query else "/api/signals/")

    def create_signal(self, asset_code, logic_desc, invalidation_logic=None, threshold=None):
        data = {"asset_code": asset_code, "logic_desc": logic_desc}
        if invalidation_logic: data["invalidation_logic"] = invalidation_logic
        if threshold: data["invalidation_threshold"] = threshold
        return self._post("/api/signals/", data)

    # Macro
    def list_macro_indicators(self):
        return self._get("/api/macro/supported-indicators/")

    def get_macro_data(self, indicator_code, start_date=None, end_date=None):
        params = [f"indicator_code={indicator_code}"]
        if start_date: params.append(f"start_date={start_date}")
        if end_date: params.append(f"end_date={end_date}")
        return self._get(f"/api/macro/data/?{'&'.join(params)}")

    # Account
    def get_profile(self):
        return self._get("/api/account/profile/")

    def list_portfolios(self):
        return self._get("/api/account/portfolios/")

    # Backtest
    def list_backtests(self):
        return self._get("/api/backtest/")


# Usage
client = AgomTradeProClient()

# Get current state
regime = client.get_current_regime()
print(f"Regime: {regime['data']['dominant_regime']} (confidence: {regime['data']['confidence']:.2%})")

policy = client.get_policy_status()
print(f"Policy: {policy['level_name']} ({policy['current_level']})")
```

## Option 3: MCP Server Configuration

To use MCP tools directly in Claude Code, configure `~/.config/claude-code/mcp_servers.json`:

```json
{
  "mcpServers": {
    "agomtradepro-vps": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "D:/githv/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://your-vps-ip:8000",
        "AGOMTRADEPRO_API_TOKEN": "28c11b3441d70f581c7410faeb5baeb90901c005",
        "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true"
      }
    }
  }
}
```

After configuration, restart Claude Code. MCP tools available:
- `get_current_regime()` - Get current macro regime
- `get_policy_status()` - Get policy status
- `list_signals()` - List investment signals
- `list_macro_indicators()` - List macro indicators
- `run_backtest()` - Run backtest
- `get_portfolio_summary()` - Get portfolio summary

## Full API Endpoint Reference

### Regime & Policy
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/regime/current/` | GET | Current macro regime |
| `/api/regime/history/` | GET | Regime history |
| `/api/policy/status/` | GET | Current policy status |
| `/api/policy/events/` | GET | Policy events list |

### Signals
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/signals/` | GET | List signals |
| `/api/signals/` | POST | Create signal |
| `/api/signals/{id}/approve/` | POST | Approve signal |
| `/api/signals/{id}/reject/` | POST | Reject signal |

### Macro Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/macro/supported-indicators/` | GET | List 52 supported indicators |
| `/api/macro/data/` | GET | Get indicator time series |
| `/api/macro/sync/` | POST | Sync indicator from source |

### Account
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/account/profile/` | GET | User profile |
| `/api/account/portfolios/` | GET | List portfolios |
| `/api/account/portfolios/{id}/` | GET | Portfolio detail |

### Backtest
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/backtest/` | GET | List backtests |
| `/api/backtest/` | POST | Run new backtest |
| `/api/backtest/{id}/` | GET | Get backtest result |

## Troubleshooting

1. **Connection refused**
   ```bash
   ping your-vps-ip
   curl -I http://your-vps-ip:8000/
   ```

2. **401 Unauthorized**: Verify token is correct

3. **404 Not Found**: Check endpoint path - use `/api/` to list all endpoints

4. **Timeout**: VPS may be slow, increase timeout to 30+ seconds

5. **Empty data**: Database may need initial sync of macro indicators
