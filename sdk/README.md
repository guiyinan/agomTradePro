# AgomSAAF SDK & MCP Server

Python SDK and MCP (Model Context Protocol) Server for AgomSAAF - Macro Environment Admission System.

## Overview

AgomSAAF SDK provides two ways to interact with the AgomSAAF system:

1. **Python SDK** - Full-featured Python client for complete system access
2. **MCP Server** - AI-native tools for Claude Code and other AI agents

## Installation

```bash
# From the AgomSAAF project
cd D:/githv/agomSAAF/sdk

# Install in development mode
pip install -e .

# With development dependencies
pip install -e ".[dev]"

# With pandas support
pip install -e ".[pandas]"
```

## Compatibility

- Python: `>=3.11`
- MCP Python SDK: `mcp>=1.20,<2`

Verify installed versions:

```bash
python -m pip show agomsaaf-sdk mcp
```

## Authentication

AgomSAAF backend uses DRF Token authentication.

- Header format: `Authorization: Token <your_token>`
- SDK `api_token` can be either raw token or prefixed form (`Token ...` / `Bearer ...`).

Generate a token for an existing user (example: `admin`):

```bash
cd D:/githv/agomSAAF
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='sdk-readme'); print(key)"
```

## Quick Start

### Python SDK

```python
from agomsaaf import AgomSAAFClient

# Initialize client
client = AgomSAAFClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Get current regime
regime = client.regime.get_current()
print(f"Current regime: {regime.dominant_regime}")

# Check signal eligibility
eligibility = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI rising, economic recovery"
)

# Create signal
if eligibility["is_eligible"]:
    signal = client.signal.create(
        asset_code="000001.SH",
        logic_desc="PMI rising, economic recovery",
        invalidation_logic="PMI falls below 50",
        invalidation_threshold=49.5
    )
    print(f"Signal created: {signal.id}")
```

### MCP Server

Configure in `~/.config/claude-code/mcp_servers.json`:

```json
{
  "mcpServers": {
    "agomsaaf_local": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "http://127.0.0.1:8000",
        "AGOMSAAF_API_BASE_URL": "http://127.0.0.1:8000",
        "AGOMSAAF_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

You can also start MCP manually (for smoke testing):

```bash
agomsaaf-mcp
```

Recommended:

- repo `.mcp.json`: keep only `agomsaaf_local`
- client global config: split `agomsaaf_local` and `agomsaaf_prod`
- do not switch environments by editing one shared server entry

If your environment has a global proxy, set local bypass for loopback:

```bash
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
```

Then use directly in Claude Code:

```
User: What's the current macro regime?
Claude: [calls get_current_regime tool]
       Current regime: Recovery (growth up, inflation down)
```

## Configuration

Three methods (priority order):

1. **Constructor parameters**
2. **Environment variables**:
   - `AGOMSAAF_BASE_URL`
   - `AGOMSAAF_API_BASE_URL` (legacy alias, still supported)
   - `AGOMSAAF_API_TOKEN`
   - `AGOMSAAF_USERNAME`
   - `AGOMSAAF_PASSWORD`
3. **Config files**:
   - `.agomsaaf.json` (current directory)
   - `~/.agomsaaf/config.json` (user directory)

## SDK Modules

| Module | Description |
|--------|-------------|
| `client.regime` | Regime determination - get current regime, calculate regime, history |
| `client.signal` | Investment signals - create, approve, check eligibility |
| `client.macro` | Macro data - indicators, data points, sync |
| `client.policy` | Policy events - status, event management, **workbench operations** |
| `client.backtest` | Backtesting - run, get results, equity curve |
| `client.account` | Account management - portfolios, positions |
| `client.simulated_trading` | Simulated trading - accounts, execution, performance |
| `client.equity` | Stock analysis - scoring, recommendations, financials |
| `client.fund` | Fund analysis - scoring, performance, holdings |
| `client.sector` | Sector analysis - scoring, hot sectors, comparison |
| `client.strategy` | Strategy management - create/execute strategy, bind/unbind portfolio strategy, DB-driven position rules |
| `client.realtime` | Real-time prices - market data, alerts, top movers |
| `client.rotation` | Rotation - recommendations, templates, per-account regime allocation configs |
| `client.alpha` | Alpha scoring - scores, provider status, universes, health, factor exposure |
| `client.decision_workflow` | **Decision workflow (V3.4+)** - precheck |
| `client.decision_rhythm` | **Decision rhythm (V3.4+)** - submit, execute, cancel, get decision requests |
| `client.config_center` | **Config center** - unified config snapshot and capabilities |

## MCP Tools (60+)

Canonical API routing for SDK/MCP is documented in:

- [`docs/development/api-mcp-sdk-alignment-2026-03-14.md`](../docs/development/api-mcp-sdk-alignment-2026-03-14.md)

### Core Tools
- **Regime**: `get_current_regime`, `calculate_regime`, `get_regime_history`, `explain_regime`
- **Signal**: `list_signals`, `create_signal`, `check_signal_eligibility`, `approve_signal`
- **Macro**: `list_macro_indicators`, `get_macro_data`, `sync_macro_indicator`
- **Backtest**: `run_backtest`, `get_backtest_result`, `get_backtest_equity_curve`
- **Policy**: `get_policy_status`, `get_policy_events`, `create_policy_event`
- **Alpha Trigger**: `list_alpha_candidates`, `get_alpha_candidate`, `update_alpha_candidate_status`

### Workbench Tools (New)
- **Workbench**: `get_workbench_summary`, `get_workbench_items`
- **Review**: `approve_workbench_event`, `reject_workbench_event`, `rollback_workbench_event`, `override_workbench_event`
- **Gate**: `get_sentiment_gate_state`

### Extended Tools
- **Simulated Trading**: `list_simulated_accounts`, `execute_simulated_trade`, `get_simulated_performance`, `run_simulated_daily_inspection`, `list_simulated_daily_inspections`
- **Equity**: `get_stock_score`, `list_stocks`, `get_stock_recommendations`
- **Fund**: `get_fund_score`, `list_funds`, `get_fund_performance`
- **Sector**: `list_sectors`, `get_hot_sectors`, `compare_sectors`
- **Strategy**: `list_strategies`, `create_strategy`, `execute_strategy`
- **Rotation**: `list_rotation_regimes`, `list_rotation_templates`, `list_account_rotation_configs`, `get_account_rotation_config`, `create_account_rotation_config`, `update_account_rotation_config`, `apply_rotation_template_to_account_config`
- **Strategy Assignment**: `bind_portfolio_strategy`, `unbind_portfolio_strategy`
- **Decision Rhythm**: `submit_decision_request`, `list_decision_requests`, `decision_execute_request`, `decision_cancel_request`, `get_decision_request`
- **Decision Workflow (V3.4+)**: `decision_workflow_precheck`
- **Realtime**: `get_realtime_price`, `get_market_summary`, `create_price_alert`
- **Config Center**: `list_config_capabilities`, `get_config_center_snapshot`

## Rotation Account Config Examples

```python
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient(
    base_url="http://localhost:8000",
    api_token="your_token_here",
)

templates = client.rotation.list_templates()
regimes = client.rotation.list_regimes()

config = client.rotation.get_account_config_by_account(308)

updated = client.rotation.update_account_config(
    config["id"],
    {
        "risk_tolerance": "moderate",
        "is_enabled": True,
        "regime_allocations": config["regime_allocations"],
    },
)

client.rotation.apply_template_to_account_config(updated["id"], "moderate")
```

## Documentation

| Document | Description |
|----------|-------------|
| [Quick Start Guide](../docs/sdk/quickstart.md) | Getting started with the SDK |
| [MCP Guide](../docs/mcp/mcp_guide.md) | MCP server setup and usage |
| [Smoke Test Guide](../docs/sdk/smoke_test.md) | End-to-end local smoke checklist |
| [API Reference](../docs/sdk/api_reference.md) | Complete API documentation |
| [Implementation Plan](../docs/plans/sdk-mcp-implementation.md) | Implementation status and plan |

## Migration Guide (V3.5)

### API Route Migration

Starting from V3.5, AgomSAAF uses unified API route format: `/api/{module}/{resource}/`

**SDK users**: No code changes required! Simply upgrade to the latest SDK version:

```bash
pip install --upgrade agomsaaf-sdk
```

The SDK automatically uses the new routes while maintaining backward compatibility.

**What changed**:

| Old Route | New Route |
|-----------|-----------|
| `/regime/api/current/` | `/api/regime/current/` |
| `/signal/api/` | `/api/signal/` |
| `/account/api/portfolios/` | `/api/account/portfolios/` |
| `/macro/api/supported-indicators/` | `/api/macro/supported-indicators/` |
| `/filter/api/` | `/api/filter/` |
| `/backtest/api/backtests/` | `/api/backtest/backtests/` |
| `/ai/api/providers/` | `/api/ai/providers/` |
| `/prompt/api/templates/` | `/api/prompt/templates/` |
| `/macro/api/supported-indicators/` | `/api/macro/supported-indicators/` |
| `/policy/api/events/` | `/api/policy/events/` |
| `/factor/api/` | `/api/factor/` |

For detailed migration information, see:
- [API Route Migration Guide](../docs/migration/route-migration-guide.md) - Complete migration guide
- [Migration Quick Reference](../docs/migration/migration-quick-reference.md) - Quick lookup table

**Important dates**:
- 2026-03-04: New routes released, old routes marked deprecated
- 2026-04-01: Old routes enter read-only mode (GET only)
- 2026-06-01: Old routes will be removed

## Examples

| Example | Description |
|---------|-------------|
| [basic_usage.py](../docs/sdk/examples/basic_usage.py) | Basic SDK operations |
| [backtesting.py](../docs/sdk/examples/backtesting.py) | Running and analyzing backtests |
| [data_analysis.py](../docs/sdk/examples/data_analysis.py) | Data analysis with pandas |
| [simulated_trading.py](../docs/sdk/examples/simulated_trading.py) | Simulated trading workflow |
| [equity_fund_analysis.py](../docs/sdk/examples/equity_fund_analysis.py) | Stock and fund analysis |
| [realtime_strategy.py](../docs/sdk/examples/realtime_strategy.py) | Real-time monitoring and strategies |

## Notes

- `client.backtest.list()` is the preferred SDK list method. `client.backtest.list_backtests()` remains supported as a compatibility alias.
- `tests/integration/test_realtime_monitoring_flow.py` is a live-market integration test. It is skipped by default unless `AGOMSAAF_RUN_LIVE_REALTIME_TESTS=1` is set.

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black agomsaaf/ agomsaaf_mcp/
isort agomsaaf/ agomsaaf_mcp/

# Type check
mypy agomsaaf/

# Run MCP server
agomsaaf-mcp
```

## Project Status

- **Version**: 1.2.0
- **Modules**: 15 business modules
- **MCP Tools**: 65+ tools
- **Test Coverage**: Core modules covered
- **Documentation**: Complete
- **Last Updated**: 2026-03-01

## License

MIT License - see LICENSE file.
