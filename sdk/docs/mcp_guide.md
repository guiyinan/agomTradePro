# AgomSAAF MCP Server Guide

The MCP (Model Context Protocol) Server enables AI agents like Claude Code to interact with AgomSAAF through native tools.

## Setup

### 1. Install the SDK

```bash
cd D:/githv/agomSAAF/sdk
pip install -e .
```

Recommended runtime versions:

- Python `>=3.11`
- `mcp>=1.20,<2`

Verify:

```bash
python -m pip show agomsaaf-sdk mcp
```

### Runtime Environment Variables

MCP server uses SDK credentials to call AgomSAAF backend:

- `AGOMSAAF_BASE_URL` (required)
- `AGOMSAAF_API_TOKEN` (recommended)
- Or `AGOMSAAF_USERNAME` + `AGOMSAAF_PASSWORD`

Auth format on backend is DRF Token (`Authorization: Token <token>`).

Create token for an existing user:

```bash
cd D:/githv/agomSAAF
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

### Admin Token Management Page (Recommended)

If you are a system admin, you can manage DRF tokens in UI instead of shell scripts:

- Path: `/account/admin/tokens/`
- Features:
  - Search users by username/email
  - Filter users without token
  - Generate/rotate token per user
  - Revoke token per user

From the page, click "生成Token" or "重置Token" for target user. The new token will be shown once in success message, then only masked preview is displayed in list.

### 2. Configure Claude Code

Edit `~/.config/claude-code/mcp_servers.json`:

```json
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "http://localhost:8000",
        "AGOMSAAF_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

### 3. Test the Connection

Restart Claude Code and ask:
```
What's the current macro regime?
```

Claude should call the `get_current_regime` tool and respond with the current regime.

You can validate tool registration locally:

```bash
python -c "import asyncio; from agomsaaf_mcp.server import server; print(len(asyncio.run(server.list_tools())))"
```

## Available Tools

### Macro Regime Tools

```
get_current_regime()
calculate_regime(as_of_date, growth_indicator, inflation_indicator)
get_regime_history(start_date, end_date)
get_regime_distribution(start_date, end_date)
explain_regime(regime_type)
get_recommended_assets(regime_type)
```

### Signal Tools

```
list_signals(status, asset_code)
get_signal(signal_id)
check_signal_eligibility(asset_code, logic_desc)
create_signal(asset_code, logic_desc, invalidation_logic, threshold)
approve_signal(signal_id)
reject_signal(signal_id, reason)
invalidate_signal(signal_id, reason)
```

### Macro Data Tools

```
list_macro_indicators(data_source, frequency)
get_macro_indicator(indicator_code)
get_macro_data(indicator_code, start_date, end_date)
get_latest_macro_data(indicator_code)
sync_macro_indicator(indicator_code, force)
explain_macro_indicator(indicator_code)
```

### Backtest Tools

```
run_backtest(strategy_name, start_date, end_date, initial_capital)
get_backtest_result(backtest_id)
list_backtests(strategy_name, status)
get_backtest_equity_curve(backtest_id)
```

### Real-time Tools

```
get_realtime_price(asset_code)
get_multiple_realtime_prices(asset_codes)
get_market_summary()
get_top_movers(direction)
get_sector_realtime_performance()
```

## Example Conversations

### Conversation 1: Macro Analysis

```
User: What's the current macro environment?

Claude: [calls get_current_regime]
       Current Regime: Recovery
       Growth: up, Inflation: down

User: What assets should I invest in?

Claude: [calls get_recommended_assets]
       For Recovery regime, consider: stocks, commodities, real estate
```

### Conversation 2: Signal Creation

```
User: Can I create a signal for 000001.SH?

Claude: [calls check_signal_eligibility]
       Signal is eligible! Current regime matches your target.

User: Create it.

Claude: [calls create_signal]
       Signal created successfully. ID: 123
```

### Conversation 3: Backtesting

```
User: How would a momentum strategy perform?

Claude: [calls run_backtest]
       Running backtest for momentum strategy from 2023-01-01 to 2024-12-31...

       Results:
       - Annual Return: 12.5%
       - Max Drawdown: -15.2%
       - Sharpe Ratio: 1.35
```

## Resources

MCP Resources can be automatically read by AI:

```
agomsaaf://regime/current    # Current regime state
agomsaaf://policy/status     # Current policy status
```

## Prompts

Built-in prompt templates for common tasks:

```
analyze_macro_environment    # Analyze macro and suggest investments
check_signal_eligibility     # Check if signal is eligible
```

## Troubleshooting

### MCP Server Not Starting

```bash
# Test manually
cd D:/githv/agomSAAF/sdk
agomsaaf-mcp
```

If this command fails with MCP API errors, verify `mcp` major version is `1.x`:

```bash
python -m pip show mcp
```

### Connection Errors

1. Check AgomSAAF server is running: `http://localhost:8000`
2. Verify API token is correct
3. Check firewall settings
4. If proxy is enabled globally, set `NO_PROXY=127.0.0.1,localhost`

### Tool Not Available

1. Restart Claude Code
2. Verify MCP server config is correct
3. Check SDK is installed: `pip show agomsaaf-sdk`
4. Check MCP SDK is installed: `pip show mcp`
5. Confirm tools are registered: `python -c "import asyncio; from agomsaaf_mcp.server import server; print(len(asyncio.run(server.list_tools())))"`
