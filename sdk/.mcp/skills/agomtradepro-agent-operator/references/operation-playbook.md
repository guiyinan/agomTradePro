# Operation Playbook

Use this reference when the agent needs to decide how to act on the system and which tools to call.

## Tool selection

Choose MCP first when:

- The task is conversational and tool-at-a-time
- The needed capability exists in `sdk/agomtradepro_mcp/server.py`
- Audit and RBAC visibility should remain explicit

Choose SDK first when:

- The task needs loops, retries, polling, batching, or local aggregation
- The agent must orchestrate several dependent steps in code
- You need finer error handling than a single tool call

Choose direct REST only when:

- Verifying an endpoint mismatch
- Comparing MCP/SDK behavior to backend behavior
- Inspecting a route that is not yet wrapped

## Intent-to-interface map

### Read market or system state

- MCP: `get_current_regime`, `get_policy_status`, `data_center_list_indicators`, `data_center_get_macro_series`, `get_market_summary`
- SDK: `client.regime.get_current()`, `client.policy.get_status()`, `client.data_center.list_indicators()`, `client.realtime.get_market_summary()`

### Work with signals

- MCP: `check_signal_eligibility`, `create_signal`, `approve_signal`, `reject_signal`, `invalidate_signal`, `list_signals`
- SDK: `client.signal.check_eligibility()`, `client.signal.create()`, `client.signal.approve()`, `client.signal.reject()`, `client.signal.invalidate()`, `client.signal.list()`

### Run backtests

- MCP: `run_backtest`, `get_backtest_result`, `get_backtest_equity_curve`, `list_backtests`
- SDK: `client.backtest.run()`, `client.backtest.get_result()`, `client.backtest.get_equity_curve()`, `client.backtest.list_backtests()`

### Manage strategy and position rules

- MCP: `list_strategies`, `create_strategy`, `execute_strategy`, `bind_portfolio_strategy`, `unbind_portfolio_strategy`, `list_position_rules`, `create_position_rule`, `evaluate_position_rule`, `evaluate_strategy_position_management`
- SDK: matching `client.strategy.*` methods from `docs/sdk/api_reference.md`

### Decision rhythm and prechecks

- MCP: `submit_decision_request`, `list_decision_requests`, `decision_execute_request`, `decision_cancel_request`, `get_decision_request`, `decision_workflow_precheck`, `decision_workflow_check_beta_gate`, `decision_workflow_check_quota`, `decision_workflow_check_cooldown`
- SDK: `client.decision_rhythm.*`, `client.decision_workflow.*`

### Simulated trading

- MCP: `list_simulated_accounts`, `get_simulated_account`, `execute_simulated_trade`, `run_simulated_daily_inspection`, `list_simulated_daily_inspections`
- SDK: `client.simulated_trading.*`

### Rotation configuration

- MCP: `list_rotation_regimes`, `list_rotation_templates`, `list_account_rotation_configs`, `get_account_rotation_config`, `create_account_rotation_config`, `update_account_rotation_config`, `apply_rotation_template_to_account_config`
- SDK: `client.rotation.*`

## Safe execution patterns

### Create or approve a signal

1. Read regime and policy state.
2. Run `check_signal_eligibility`.
3. If eligible, create or approve the signal.
4. Re-read the signal or list filtered signals to confirm status.

### Submit a decision request

1. Read the target strategy, account, or alpha candidate state.
2. Run `decision_workflow_precheck`.
3. Run beta gate, quota, and cooldown checks if the path is gated.
4. Submit with `submit_decision_request`.
5. Re-read using `get_decision_request`.

### Execute simulated trade

1. Read account, positions, and market price.
2. Validate side, quantity, and account scope.
3. Execute the trade once.
4. Re-read positions and performance.

### Update rotation config

1. Read current config by `config_id` or `account_id`.
2. Prefer applying a template if the user asks for a standard profile.
3. If sending custom allocations, ensure each regime allocation sums to about `1.0`.
4. Re-read the config after update.

## Write safeguards

- Never write before confirming the target object ID.
- Never chain multiple writes if the first write changes server-side state that must be reloaded.
- If an MCP write tool is unavailable but the SDK supports it, use the SDK and report the exact endpoint or method used.
- If the role is read-only, stop before mutation and report the RBAC limitation.

## Reporting format

When the agent completes an operation, report:

- Interface used: MCP or SDK
- Objects touched: IDs, portfolio IDs, signal IDs, strategy IDs, candidate IDs
- Final state: created, approved, rejected, queued, executed, updated, unchanged
- Any follow-up: extra approval, manual review, or rerun conditions
