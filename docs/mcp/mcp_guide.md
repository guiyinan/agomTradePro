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
- `AGOMSAAF_DEFAULT_PORTFOLIO_ID` (optional, used by account resources)

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
        "AGOMSAAF_API_TOKEN": "your_token_here",
        "AGOMSAAF_MCP_ENFORCE_RBAC": "true",
        "AGOMSAAF_MCP_ROLE": "投资经理"
      }
    }
  }
}
```

## RBAC (Role-Based Access Control)

Enable RBAC:

- `AGOMSAAF_MCP_ENFORCE_RBAC=true`
- 推荐：不设置 `AGOMSAAF_MCP_ROLE`，MCP 会自动从 `account/api/profile/` 的 `rbac_role` 读取当前用户角色
- 可选覆盖：`AGOMSAAF_MCP_ROLE=<role>`（强制覆盖后端角色）
- 角色来源开关：`AGOMSAAF_MCP_ROLE_SOURCE=backend`（默认）
- 后备角色：`AGOMSAAF_MCP_DEFAULT_ROLE=read_only`

Supported roles (Chinese/English aliases):

- `管理员` / `admin`: full access
- `所有者` / `owner`: full except system-admin operations
- `分析师` / `analyst`: read-only tools
- `投资经理` / `investment_manager`: read all + write on trading/strategy/risk domains
- `交易员` / `trader`: read all + write on trading domain
- `风控` / `risk`: read all + write on risk domain
- `只读用户` / `read_only`: read-only (and stricter prompt limits)

Optional hard overrides:

- `AGOMSAAF_MCP_ALLOWED_TOOLS=tool_a,tool_b`
- `AGOMSAAF_MCP_DENIED_TOOLS=tool_x`
- `AGOMSAAF_MCP_ALLOWED_RESOURCES=agomsaaf://regime/current`
- `AGOMSAAF_MCP_DENIED_RESOURCES=agomsaaf://account/summary`
- `AGOMSAAF_MCP_ALLOWED_PROMPTS=analyze_macro_environment`
- `AGOMSAAF_MCP_DENIED_PROMPTS=check_signal_eligibility`

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

### Strategy Position Management Tools

```
bind_portfolio_strategy(portfolio_id, strategy_id)
unbind_portfolio_strategy(portfolio_id)
list_position_rules(strategy_id, is_active, limit)
create_position_rule(strategy_id, name, buy_price_expr, sell_price_expr, stop_loss_expr, take_profit_expr, position_size_expr, ...)
get_strategy_position_rule(strategy_id)
evaluate_position_rule(rule_id, context)
evaluate_strategy_position_management(strategy_id, context)
```

`context` is a JSON object with runtime variables (for example `current_price`, `atr`, `account_equity`, `risk_per_trade_pct`).

### Alpha Candidate Tools

```
list_alpha_candidates()
get_alpha_candidate(candidate_id)
update_alpha_candidate_status(candidate_id, status)
```

`status` supports: `WATCH`, `CANDIDATE`, `ACTIONABLE`, `EXECUTED`, `CANCELLED`.

### Simulated Trading Inspection Tools

```
list_simulated_accounts(status, limit)
get_simulated_account(account_id)
create_simulated_account(name, initial_capital, start_date)
execute_simulated_trade(account_id, asset_code, side, quantity, price)
get_simulated_positions(account_id)
get_simulated_performance(account_id)
run_simulated_daily_inspection(account_id, strategy_id, inspection_date)
list_simulated_daily_inspections(account_id, limit, inspection_date)
```

### Account Position Tools

```
get_positions_detailed(portfolio_id, include_closed)
import_positions_csv(portfolio_id, csv_text, mode, dry_run)
import_positions_json(portfolio_id, positions, mode, dry_run)
export_positions_csv(portfolio_id, include_closed)
export_positions_json(portfolio_id, include_closed)
```

`mode` supports:
- `upsert`: create/update only imported symbols
- `replace`: create/update imported symbols and close non-imported open positions

### Transaction Tools

```
get_transactions_detailed(portfolio_id)
import_transactions_csv(portfolio_id, csv_text, mode, dry_run)
import_transactions_json(portfolio_id, transactions, mode, dry_run)
export_transactions_csv(portfolio_id)
export_transactions_json(portfolio_id)
```

`mode` supports:
- `append`: append imported transactions
- `replace`: delete existing transactions in portfolio and import new ones

### Capital Flow Tools

```
get_capital_flows_detailed(portfolio_id)
import_capital_flows_csv(portfolio_id, csv_text, mode, dry_run)
import_capital_flows_json(portfolio_id, capital_flows, mode, dry_run)
export_capital_flows_csv(portfolio_id)
export_capital_flows_json(portfolio_id)
```

`mode` supports:
- `append`: append imported flows
- `replace`: delete existing flows in portfolio and import new ones

### Account Bundle Tools

```
get_portfolio_statistics(portfolio_id)
export_account_bundle_json(portfolio_id)
export_account_bundle_csv(portfolio_id)
```

Bundle export aggregates:
- portfolio detail
- portfolio statistics
- positions
- transactions
- capital flows

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
agomsaaf://account/summary   # Default portfolio summary
agomsaaf://account/positions # Default portfolio position snapshot
agomsaaf://account/recent-transactions # Default portfolio recent trades
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
