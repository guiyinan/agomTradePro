# AgomTradePro MCP Server Guide

The MCP (Model Context Protocol) Server enables AI agents like Claude Code to interact with AgomTradePro through native tools.

## Setup

### 1. Install the SDK

```bash
cd sdk
pip install -e .
```

Recommended runtime versions:

- Python `>=3.11`
- `mcp>=1.20,<2`

Verify:

```bash
python -m pip show agomtradepro-sdk mcp
```

### Runtime Environment Variables

MCP server uses SDK credentials to call AgomTradePro backend:

- `AGOMTRADEPRO_BASE_URL` (required)
- `AGOMTRADEPRO_API_TOKEN` (recommended)
- Or `AGOMTRADEPRO_USERNAME` + `AGOMTRADEPRO_PASSWORD`
- `AGOMTRADEPRO_DEFAULT_PORTFOLIO_ID` (optional, used by account resources)

Auth format on backend is DRF Token (`Authorization: Token <token>`).

Create token for an existing user:

```bash
cd .
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

### Runtime Setup by Platform

#### Windows PowerShell

```powershell
$env:AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
$env:AGOMTRADEPRO_API_TOKEN="your_token_here"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
```

#### Linux/macOS (bash)

```bash
export AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
export AGOMTRADEPRO_API_TOKEN="your_token_here"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
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

Windows path example:

```json
{
  "mcpServers": {
    "agomtradepro": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "D:/path/to/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://localhost:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true",
        "AGOMTRADEPRO_MCP_ROLE": "投资经理"
      }
    }
  }
}
```

Linux/macOS path example:

```json
{
  "mcpServers": {
    "agomtradepro": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "/path/to/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://localhost:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true",
        "AGOMTRADEPRO_MCP_ROLE": "投资经理"
      }
    }
  }
}
```

## RBAC (Role-Based Access Control)

Enable RBAC:

- `AGOMTRADEPRO_MCP_ENFORCE_RBAC=true`
- 推荐：不设置 `AGOMTRADEPRO_MCP_ROLE`，MCP 会自动从 `account/api/profile/` 的 `rbac_role` 读取当前用户角色
- 可选覆盖：`AGOMTRADEPRO_MCP_ROLE=<role>`（强制覆盖后端角色）
- 角色来源开关：`AGOMTRADEPRO_MCP_ROLE_SOURCE=backend`（默认）
- 后备角色：`AGOMTRADEPRO_MCP_DEFAULT_ROLE=read_only`

Supported roles (Chinese/English aliases):

- `管理员` / `admin`: full access
- `所有者` / `owner`: full except system-admin operations
- `分析师` / `analyst`: read-only tools
- `投资经理` / `investment_manager`: read all + write on trading/strategy/risk domains
- `交易员` / `trader`: read all + write on trading domain
- `风控` / `risk`: read all + write on risk domain
- `只读用户` / `read_only`: read-only (and stricter prompt limits)

Optional hard overrides:

- `AGOMTRADEPRO_MCP_ALLOWED_TOOLS=tool_a,tool_b`
- `AGOMTRADEPRO_MCP_DENIED_TOOLS=tool_x`
- `AGOMTRADEPRO_MCP_ALLOWED_RESOURCES=agomtradepro://regime/current`
- `AGOMTRADEPRO_MCP_DENIED_RESOURCES=agomtradepro://account/summary`
- `AGOMTRADEPRO_MCP_ALLOWED_PROMPTS=analyze_macro_environment`
- `AGOMTRADEPRO_MCP_DENIED_PROMPTS=check_signal_eligibility`

### 3. Test the Connection

Restart Claude Code and ask:
```
What's the current macro regime?
```

Claude should call the `get_current_regime` tool and respond with the current regime.

You can validate tool registration locally:

```bash
python -c "import asyncio; from agomtradepro_mcp.server import server; print(len(asyncio.run(server.list_tools())))"
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

### Rotation Account Config Tools

```
list_rotation_regimes()
list_rotation_templates()
list_account_rotation_configs()
get_account_rotation_config(config_id, account_id)
create_account_rotation_config(account_id, risk_tolerance, is_enabled, regime_allocations)
update_account_rotation_config(config_id, payload, partial)
delete_account_rotation_config(config_id)
apply_rotation_template_to_account_config(config_id, template_key)
```

Notes:

- `get_account_rotation_config` accepts either `config_id` or `account_id`; `config_id` wins if both are provided.
- `template_key` usually uses `conservative`, `moderate`, or `aggressive`.
- `regime_allocations` shape is `{regime_name: {asset_code: weight}}`, and each regime should sum to `1.0` within backend tolerance.

Example:

```json
{
  "account_id": 308,
  "risk_tolerance": "moderate",
  "is_enabled": true,
  "regime_allocations": {
    "Overheat": {
      "510300": 0.4,
      "518880": 0.2,
      "511260": 0.4
    }
  }
}
```

### Alpha Upload And User-Isolation Tools

```
get_alpha_stock_scores(universe, trade_date, top_n, user_id)
upload_alpha_scores(universe_id, asof_date, intended_trade_date, scores, model_id, model_artifact_hash, scope)
```

Notes:

- `get_alpha_stock_scores` now supports optional `user_id`; only admin-backed tokens should use it to inspect another user's personal cache.
- Read priority is `personal > system`.
- `upload_alpha_scores(..., scope="user")` writes personal scores for the token owner.
- `upload_alpha_scores(..., scope="system")` writes system-level scores and requires an admin-capable backend user/token.
- This makes MCP suitable for "local Qlib inference -> upload to VPS -> isolated visibility" workflows.

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

### Decision Workflow Tools

```
decision_workflow_precheck(candidate_id)
decision_workflow_list_recommendations(account_id, status, user_action, security_code, recommendation_id, include_ignored, page, page_size)
decision_workflow_refresh_recommendations(account_id, security_codes, force, async_mode)
decision_workflow_apply_recommendation_action(recommendation_id, action, account_id, note)
```

Notes:

- `decision_workflow_list_recommendations` returns unified recommendation objects from the decision workspace.
- `decision_workflow_refresh_recommendations` is the bridge from homepage/equity recommendations into the decision workspace.
- `decision_workflow_apply_recommendation_action` records the user's explicit choice on a recommendation.
- `action` supports: `watch`, `adopt`, `ignore`, `pending`.

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
agomtradepro://regime/current    # Current regime state
agomtradepro://policy/status     # Current policy status
agomtradepro://account/summary   # Default portfolio summary
agomtradepro://account/positions # Default portfolio position snapshot
agomtradepro://account/recent-transactions # Default portfolio recent trades
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
cd sdk
agomtradepro-mcp
```

If this command fails with MCP API errors, verify `mcp` major version is `1.x`:

```bash
python -m pip show mcp
```

### Connection Errors

1. Check AgomTradePro server is running: `http://localhost:8000`
2. Verify API token is correct
3. Check firewall settings
4. If proxy is enabled globally, set `NO_PROXY=127.0.0.1,localhost`

### Tool Not Available

1. Restart Claude Code
2. Verify MCP server config is correct
3. Check SDK is installed: `pip show agomtradepro-sdk`
4. Check MCP SDK is installed: `pip show mcp`
5. Confirm tools are registered: `python -c "import asyncio; from agomtradepro_mcp.server import server; print(len(asyncio.run(server.list_tools())))"`
