# AgomTradePro SDK & MCP Server

Python SDK and MCP (Model Context Protocol) Server for AgomTradePro - Macro Environment Admission System.

## Overview

AgomTradePro SDK provides two ways to interact with the AgomTradePro system:

1. **Python SDK** - Full-featured Python client for complete system access
2. **MCP Server** - AI-native tools for Claude Code and other AI agents

## Installation

```bash
# From the AgomTradePro project
cd D:/githv/agomTradePro/sdk

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
python -m pip show agomtradepro-sdk mcp
```

## Authentication

AgomTradePro backend uses DRF Token authentication.

- Header format: `Authorization: Token <your_token>`
- SDK `api_token` can be either raw token or prefixed form (`Token ...` / `Bearer ...`).

Generate a token for an existing user (example: `admin`):

```bash
cd D:/githv/agomTradePro
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='sdk-readme'); print(key)"
```

## Quick Start

### Python SDK

```python
from agomtradepro import AgomTradeProClient

# Initialize client
client = AgomTradeProClient(
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
    "agomtradepro_local": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "D:/githv/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://127.0.0.1:8000",
        "AGOMTRADEPRO_API_BASE_URL": "http://127.0.0.1:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_DEFAULT_ACCOUNT_ID": "1"
      }
    }
  }
}
```

You can also start MCP manually (for smoke testing):

```bash
agomtradepro-mcp
```

Recommended:

- repo `.mcp.json`: keep only `agomtradepro_local`
- client global config: split `agomtradepro_local` and `agomtradepro_prod`
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
   - `AGOMTRADEPRO_BASE_URL`
   - `AGOMTRADEPRO_API_BASE_URL` (legacy alias, still supported)
   - `AGOMTRADEPRO_API_TOKEN`
   - `AGOMTRADEPRO_USERNAME`
   - `AGOMTRADEPRO_PASSWORD`
3. **Config files**:
   - `.agomtradepro.json` (current directory)
   - `~/.agomtradepro/config.json` (user directory)

## SDK Modules

| Module | Description |
|--------|-------------|
| `client.regime` | Regime determination - get current regime, calculate regime, history |
| `client.signal` | Investment signals - create, approve, check eligibility |
| `client.data_center` | Unified data center - provider status, indicator governance, macro/price/fund/news facts |
| `client.policy` | Policy events - status, event management, **workbench operations** |
| `client.backtest` | Backtesting - run, get results, equity curve |
| `client.account` | Unified account management - accounts, positions, performance; old portfolio APIs remain compatibility-only |
| `client.simulated_trading` | Unified account trading/execution module; module name retained for compatibility |
| `client.equity` | Stock analysis - scoring, recommendations, financials |
| `client.fund` | Fund analysis - scoring, performance, holdings |
| `client.sector` | Sector analysis - scoring, hot sectors, comparison |
| `client.strategy` | Strategy management - create/execute strategy, bind/unbind portfolio strategy, AI strategy config, DB-driven position rules |
| `client.realtime` | Real-time prices - market data, alerts, top movers |
| `client.rotation` | Rotation - recommendations, templates, per-account regime allocation configs |
| `client.alpha` | Alpha scoring + ops console bridges - scores, provider status, universes, health, factor exposure, inference/data ops |
| `client.dashboard` | Dashboard account view - Alpha candidates, history, async refresh status, and recommendation contract |
| `client.decision_workflow` | **Decision workflow (V3.4+)** - precheck, workspace recommendation bridge, funnel context |
| `client.pulse` | **Pulse + Navigator** - pulse snapshot/history, regime navigator, action recommendation |
| `client.decision_rhythm` | **Decision rhythm (V3.4+)** - submit, execute, cancel, get decision requests |
| `client.config_center` | **Config center** - unified config snapshot and capabilities |

## MCP Tools

Current local MCP registration snapshot on `2026-05-03`: `318` tools.

Canonical API routing for SDK/MCP is documented in:

- [`docs/development/api-mcp-sdk-alignment-2026-03-14.md`](../docs/development/api-mcp-sdk-alignment-2026-03-14.md)

### Core Tools
- **Regime**: `get_current_regime`, `calculate_regime`, `get_regime_history`, `explain_regime`
- **Signal**: `list_signals`, `create_signal`, `check_signal_eligibility`, `approve_signal`
- **Data Center Macro**: `data_center_list_indicators`, `data_center_get_macro_series`, `data_center_sync_macro`
- **Backtest**: `run_backtest`, `get_backtest_result`, `get_backtest_equity_curve`
- **Policy**: `get_policy_status`, `get_policy_events`, `create_policy_event`
- **Alpha Trigger**: `list_alpha_candidates`, `get_alpha_candidate`, `update_alpha_candidate_status`

### Macro Governance Contract

Current macro governance contract after the 2026-05-03 repair:

- runtime truth source = `IndicatorCatalog` + `IndicatorUnitRule` + `data_center_macro_fact`
- staff governance console = `/data-center/governance/`
- MCP/SDK should still read/write only through canonical data-center APIs and tools
- runtime schedule / publication / period override metadata now begins to live in `IndicatorCatalog.extra`

High-risk code semantics that callers must now treat as canonical:

- `CN_GDP` = quarterly cumulative level
- `CN_GDP_YOY` = GDP YoY rate
- `CN_FIXED_INVESTMENT` = fixed investment cumulative level
- `CN_FAI_YOY` = fixed investment cumulative YoY rate
- `CN_SOCIAL_FINANCING` = monthly social financing flow
- `CN_SOCIAL_FINANCING_YOY` = monthly social financing flow YoY rate
- `CN_EXPORTS` = monthly export amount, display unit `亿美元`
- `CN_EXPORT_YOY` = monthly export amount YoY rate
- `CN_IMPORTS` = monthly import amount, display unit `亿美元`
- `CN_IMPORT_YOY` = monthly import amount YoY rate

Compatibility note:

- `CN_CPI_YOY` is retained only as a compatibility alias code. Canonical lookup should prefer `CN_CPI_NATIONAL_YOY`.
- callers should interpret macro runtime metadata in this priority order:
  - `series_semantics` / `paired_indicator_code` for meaning
  - `schedule_frequency` / `schedule_day_of_month` / `schedule_release_months` for cadence
  - `publication_lag_days` for freshness expectation
  - `orm_period_type_override` / `domain_period_type_override` for storage/runtime period semantics
- do not infer macro meaning or cadence solely from code suffixes such as `_YOY` / `_MOM` / `GDP`.

### Dashboard Alpha Contract

`client.dashboard.alpha_stocks(...)` and MCP `get_dashboard_alpha_candidates(...)` include a `contract` object. Agents should only treat the response as a recommendation when `contract.recommendation_ready=true`; `contract.async_refresh_queued=true` means scoped Qlib inference is still running, and `contract.must_not_treat_as_recommendation=true` means pending requests or refresh status must not be shown as current Alpha picks.

`client.dashboard.alpha_refresh(...)` and MCP `trigger_dashboard_alpha_refresh(...)` only queue backend inference for the account-driven pool. They never return recommendations directly.

Dashboard Alpha caller-controlled pool selection:

- `client.dashboard.alpha_stocks(..., pool_mode="strict_valuation" | "market" | "price_covered")`
- `client.dashboard.alpha_refresh(..., pool_mode="strict_valuation" | "market" | "price_covered")`
- MCP `get_dashboard_alpha_candidates(..., pool_mode=...)`
- MCP `trigger_dashboard_alpha_refresh(..., pool_mode=...)`

This keeps SDK/MCP behavior aligned with the dashboard UI: callers can explicitly choose the Alpha screening universe instead of relying only on the backend default.

### Alpha Ops Console

The Alpha ops console is also exposed through SDK/MCP for operator workflows:

- `client.alpha.get_ops_inference_overview()`
- `client.alpha.trigger_ops_inference(...)`
- `client.alpha.get_ops_qlib_data_overview()`
- `client.alpha.refresh_ops_qlib_data(...)`
- MCP `get_alpha_ops_inference_overview`
- MCP `trigger_alpha_ops_inference`
- MCP `get_alpha_ops_qlib_data_overview`
- MCP `refresh_alpha_qlib_data`

These calls mirror the staff/superuser web console:

- overview calls are read-only operational snapshots
- trigger / refresh calls only queue backend jobs
- duplicate in-flight work may return the backend conflict payload instead of a fresh task

### Workbench Tools (New)
- **Workbench**: `get_workbench_summary`, `get_workbench_items`
- **Review**: `approve_workbench_event`, `reject_workbench_event`, `rollback_workbench_event`, `override_workbench_event`
- **Gate**: `get_sentiment_gate_state`

### Extended Tools
- **Unified Accounts**: `list_accounts`, `get_account`, `create_account`, `get_account_positions`, `get_account_performance`
- **Simulated Trading Compat**: `list_simulated_accounts`, `execute_simulated_trade`, `get_simulated_performance`, `run_simulated_auto_trading`, `run_simulated_daily_inspection`, `list_simulated_daily_inspections`
- **Equity**: `get_stock_score`, `list_stocks`, `get_stock_recommendations`
- **Fund**: `get_fund_score`, `list_funds`, `get_fund_performance`
- **Sector**: `list_sectors`, `get_hot_sectors`, `compare_sectors`
- **Strategy**: `list_strategies`, `create_strategy`, `execute_strategy`, `list_ai_strategy_configs`, `get_strategy_ai_config`, `create_ai_strategy_config`, `update_ai_strategy_config`, `list_position_rules`, `create_position_rule`, `update_position_rule`
- **Rotation**: `list_rotation_regimes`, `list_rotation_templates`, `list_account_rotation_configs`, `get_account_rotation_config`, `create_account_rotation_config`, `update_account_rotation_config`, `apply_rotation_template_to_account_config`
- **Strategy Assignment**: `bind_portfolio_strategy`, `unbind_portfolio_strategy`
- **Decision Rhythm**: `submit_decision_request`, `list_decision_requests`, `decision_execute_request`, `decision_cancel_request`, `get_decision_request`
- **Decision Workflow (V3.4+)**: `decision_workflow_precheck`, `decision_workflow_list_recommendations`, `decision_workflow_refresh_recommendations`, `decision_workflow_apply_recommendation_action`, `decision_workflow_get_funnel_context`
- **Pulse + Navigator**: `get_pulse_current`, `get_pulse_history`, `get_regime_navigator`, `get_action_recommendation`
- **Realtime**: `get_realtime_price`, `get_market_summary`, `create_price_alert`
- **Config Center**: `list_config_capabilities`, `get_config_center_snapshot`

Decision workflow note:

- `decision_workflow_get_funnel_context` now exposes Step 3 freshness metadata in `step3_sectors`: `rotation_data_source`, `rotation_is_stale`, `rotation_warning_message`, `rotation_signal_date`.

## Rotation Account Config Examples

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(
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

Starting from V3.5, AgomTradePro uses unified API route format: `/api/{module}/{resource}/`

**SDK users**: No code changes required! Simply upgrade to the latest SDK version:

```bash
pip install --upgrade agomtradepro-sdk
```

The SDK automatically uses the new routes while maintaining backward compatibility.

**What changed**:

| Old Route | New Route |
|-----------|-----------|
| `/regime/api/current/` | `/api/regime/current/` |
| `/signal/api/` | `/api/signal/` |
| `/account/api/portfolios/` | `/api/account/portfolios/` |
| `/macro/api/supported-indicators/` | `/api/data-center/indicators/` |
| `/filter/api/` | `/api/filter/` |
| `/backtest/api/backtests/` | `/api/backtest/backtests/` |
| `/ai/api/providers/` | `/api/ai/providers/` |
| `/prompt/api/templates/` | `/api/prompt/templates/` |
| `/macro/api/indicator-data/` | `/api/data-center/macro/series/` |
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
- `tests/integration/test_realtime_monitoring_flow.py` is a live-market integration test. It is skipped by default unless `AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1` is set.

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black agomtradepro/ agomtradepro_mcp/
isort agomtradepro/ agomtradepro_mcp/

# Type check
mypy agomtradepro/

# Run MCP server
agomtradepro-mcp
```

## Project Status

- **Version**: 1.2.0
- **App Modules**: 35 business modules
- **SDK Modules**: 36 service modules
- **MCP Tools**: 302 tools
- **Test Coverage**: Core modules covered
- **Documentation**: Complete
- **Last Updated**: 2026-04-21

## License

Apache License 2.0 - see [LICENSE](../LICENSE) for details.
