# AgomSAAF MCP Server Guide

The MCP (Model Context Protocol) Server enables AI agents like Claude Code to interact with AgomSAAF through native tools.

## Setup

### 1. Install the SDK

```bash
cd D:/githv/agomSAAF/sdk
pip install -e .
```

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
python -m agomsaaf_mcp.server
```

### Connection Errors

1. Check AgomSAAF server is running: `http://localhost:8000`
2. Verify API token is correct
3. Check firewall settings

### Tool Not Available

1. Restart Claude Code
2. Verify MCP server config is correct
3. Check SDK is installed: `pip show agomsaaf-sdk`
