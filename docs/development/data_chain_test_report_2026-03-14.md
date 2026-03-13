# AgomSAAF Data Chain Test Report

**Test Date**: 2026-03-14
**Test Environment**: 127.0.0.1:8000 (Local via MCP SDK)
**API Token**: 56d30eb16b230581312397997d27b3b613941811

## Summary

| Status | Count | Percentage |
|--------|-------|------------|
| OK | 10 | 83.3% |
| FAIL | 2 | 16.7% |
| **Total** | **12** | **100%** |

## Results by Category

### Core Modules (3/3 OK)
| Endpoint | Path | Status |
|----------|------|--------|
| Regime Current | `regime/current/` | OK |
| Policy Status | `policy/status/` | OK |
| Policy Workbench | `policy/workbench/` | OK |

### Data Modules (2/2 OK)
| Endpoint | Path | Status |
|----------|------|--------|
| Macro Indicators | `macro/supported-indicators/` | OK |
| Market Summary | `realtime/market-summary/` | OK |

### Alpha Modules (3/3 OK)
| Endpoint | Path | Status |
|----------|------|--------|
| Alpha Health | `/api/alpha/health/` | OK |
| Alpha Providers | `/api/alpha/providers/status/` | OK |
| Alpha Universes | `/api/alpha/universes/` | OK |

### Sentiment Modules (1/2 OK)
| Endpoint | Path | Status | Error |
|----------|------|--------|-------|
| Sentiment Health | `/api/sentiment/health/` | OK | - |
| Sentiment Index | `/api/sentiment/index/` | FAIL | 404 - Wrong path |

**Fix**: Use `/api/sentiment/index/recent/` instead of `/api/sentiment/index/`

### Signal Modules (1/2 OK)
| Endpoint | Path | Status | Error |
|----------|------|--------|-------|
| Signal List | `signal/` | OK | - |
| Signal Health | `/api/signal/health/` | FAIL | 404 - Route order issue |

**Fix**: Reordered routes in `apps/signal/interface/urls.py` - health/ before router. **Requires Django server restart.**

## Broken Chains Summary

| # | Module | Endpoint | Issue | Fix Status |
|---|--------|----------|-------|------------|
| 1 | Sentiment | `/api/sentiment/index/` | Wrong endpoint path | Use `/api/sentiment/index/recent/` |
| 2 | Signal | `/api/signal/health/` | Route order (router catches first) | Fixed - needs server restart |

## Recommendations

1. **Restart Django Server**: The signal health fix requires server restart to load new URL configuration.

2. **Update SDK Endpoints**:
   - Change `sentiment/index/` to `sentiment/index/recent/` in SDK module

3. **Add API URL Separation**: Consider creating separate `api_urls.py` files for modules that have both page and API routes to avoid routing conflicts.

## MCP Configuration

The MCP configuration at `.mcp.json` is correctly configured:

```json
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "http://127.0.0.1:8000",
        "AGOMSAAF_API_TOKEN": "56d30eb16b230581312397997d27b3b613941811",
        "AGOMSAAF_MCP_ENFORCE_RBAC": "true"
      }
    }
  }
}
```

## Code Changes Made

### apps/signal/interface/urls.py
- Reordered routes: `health/` now comes BEFORE `include(router.urls)` to prevent router from catching the path first.

```python
# Before:
path('', include(router.urls)),
path('health/', SignalHealthView.as_view(), name='health'),

# After:
path('health/', SignalHealthView.as_view(), name='health'),
path('', include(router.urls)),
```

## Next Steps

1. Restart Django server: `python manage.py runserver`
2. Re-run this test to verify all 12 endpoints are working
3. Update SDK `sentiment` module to use correct endpoint path
