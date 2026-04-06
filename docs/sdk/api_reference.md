# AgomTradePro SDK API Reference

Complete API reference for the AgomTradePro Python SDK.

## AgomTradeProClient

### Constructor

```python
AgomTradeProClient(
    base_url: str = "http://localhost:8000",
    api_token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    config: ClientConfig | None = None
)
```

### Methods

| Method | Description |
|--------|-------------|
| `get(endpoint, params)` | Send GET request |
| `post(endpoint, data, json)` | Send POST request |
| `put(endpoint, data, json)` | Send PUT request |
| `patch(endpoint, data, json)` | Send PATCH request |
| `delete(endpoint, params)` | Send DELETE request |
| `close()` | Close HTTP session |

## Regime Module

```python
client.regime.get_current() -> RegimeState
client.regime.calculate(as_of_date, growth_indicator, inflation_indicator) -> RegimeState
client.regime.history(start_date, end_date, limit) -> list[RegimeState]
client.regime.get_regime_distribution(start_date, end_date) -> dict[RegimeType, int]
```

### RegimeState

| Attribute | Type | Description |
|-----------|------|-------------|
| `dominant_regime` | `RegimeType` | Recovery/Overheat/Stagflation/Repression |
| `observed_at` | `date` | Observation date |
| `growth_level` | `str` | up/down/neutral |
| `inflation_level` | `str` | up/down/neutral |
| `growth_indicator` | `str` | Indicator name |
| `inflation_indicator` | `str` | Indicator name |
| `growth_value` | `float | None` | Indicator value |
| `inflation_value` | `float | None` | Indicator value |

## Signal Module

```python
client.signal.list(status, asset_code, limit, offset) -> list[InvestmentSignal]
client.signal.get(signal_id) -> InvestmentSignal
client.signal.create(asset_code, logic_desc, invalidation_logic, threshold) -> InvestmentSignal
client.signal.approve(signal_id, approver) -> InvestmentSignal
client.signal.reject(signal_id, reason) -> InvestmentSignal
client.signal.invalidate(signal_id, reason) -> InvestmentSignal
client.signal.check_eligibility(asset_code, logic_desc, target_regime) -> dict
```

### InvestmentSignal

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `int` | Signal ID |
| `asset_code` | `str` | Asset code |
| `logic_desc` | `str` | Logic description |
| `status` | `SignalStatus` | pending/approved/rejected/invalidated |
| `created_at` | `datetime` | Creation time |
| `invalidation_logic` | `str | None` | Invalidation logic |
| `invalidation_threshold` | `float | None` | Invalidation threshold |

## Macro Module

```python
client.macro.list_indicators(data_source, frequency, limit) -> list[MacroIndicator]
client.macro.get_indicator(indicator_code) -> MacroIndicator
client.macro.get_indicator_data(indicator_code, start_date, end_date, limit) -> list[MacroDataPoint]
client.macro.get_latest_data(indicator_code) -> MacroDataPoint | None
client.macro.sync_indicator(indicator_code, force) -> dict
```

### MacroIndicator

| Attribute | Type | Description |
|-----------|------|-------------|
| `code` | `str` | Indicator code |
| `name` | `str` | Indicator name |
| `unit` | `str` | Unit |
| `frequency` | `str` | Frequency |
| `data_source` | `str` | Data source |

## Backtest Module

```python
client.backtest.run(strategy_name, start_date, end_date, initial_capital, params) -> BacktestResult
client.backtest.get_result(backtest_id) -> BacktestResult
client.backtest.list(strategy_name, status, limit) -> list[BacktestResult]
client.backtest.list_backtests(strategy_name, status, limit) -> list[BacktestResult]
client.backtest.delete_result(backtest_id) -> None
client.backtest.get_equity_curve(backtest_id) -> list[dict]
```

`client.backtest.list()` is the preferred public method. `list_backtests()` is retained for backward compatibility.

### BacktestResult

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `int` | Backtest ID |
| `status` | `str` | Status |
| `total_return` | `float` | Total return |
| `annual_return` | `float` | Annual return |
| `max_drawdown` | `float` | Max drawdown |
| `sharpe_ratio` | `float | None` | Sharpe ratio |

## Account Module

```python
client.account.list_accounts(account_type=None, active_only=True, limit=100) -> list[dict]
client.account.get_account(account_id) -> dict
client.account.create_account(name, initial_capital, account_type="simulated", ...) -> dict
client.account.get_account_positions(account_id, asset_code=None) -> list[dict]
client.account.get_account_performance(account_id, start_date=None, end_date=None) -> dict
client.account.get_portfolios(limit) -> list[Portfolio]
client.account.get_portfolio(portfolio_id) -> Portfolio
client.account.get_positions(portfolio_id, asset_code, limit) -> list[Position]
client.account.create_position(portfolio_id, asset_code, quantity, price) -> Position
client.account.update_position(position_id, quantity, price) -> Position
client.account.delete_position(position_id) -> None
```

Unified account methods are the canonical public surface. `portfolio` methods are compatibility helpers for the legacy account ledger.

Canonical REST paths for these methods are under `/api/account/accounts/*`. The module-native `/api/simulated-trading/accounts/*` endpoints remain available as implementation-aligned aliases.

### Portfolio

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `int` | Portfolio ID |
| `name` | `str` | Portfolio name |
| `total_value` | `float` | Total value |
| `cash` | `float` | Cash |
| `positions` | `list[Position]` | Positions |

### Trading Cost Config

```python
client.account.get_trading_cost_configs(limit) -> list[dict]
client.account.get_trading_cost_config(config_id) -> dict
client.account.create_trading_cost_config(portfolio_id, commission_rate, min_commission, stamp_duty_rate, transfer_fee_rate) -> dict
client.account.update_trading_cost_config(config_id, commission_rate, min_commission, stamp_duty_rate, transfer_fee_rate, is_active) -> dict
client.account.delete_trading_cost_config(config_id) -> None
client.account.calculate_trading_cost(config_id, action, amount, is_shanghai) -> dict
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `commission_rate` | `float` | 0.00025 | 佣金率（万2.5） |
| `min_commission` | `float` | 5.0 | 最低佣金（元） |
| `stamp_duty_rate` | `float` | 0.001 | 印花税率（千1，仅卖出） |
| `transfer_fee_rate` | `float` | 0.00002 | 过户费率（万0.2，沪市双向） |

## Simulated Trading Module

```python
client.simulated_trading.list_accounts(status=None, account_type=None, limit=100) -> list
client.simulated_trading.get_account(account_id) -> dict
client.simulated_trading.create_account(name, initial_capital, start_date, account_type="simulated") -> dict
client.simulated_trading.execute_trade(account_id, asset_code, side, quantity, price) -> dict
client.simulated_trading.get_positions(account_id, asset_code) -> list
client.simulated_trading.get_performance(account_id, start_date, end_date) -> dict
client.simulated_trading.reset_account(account_id, new_initial_capital) -> dict
client.simulated_trading.close_position(account_id, asset_code) -> dict
client.simulated_trading.run_daily_inspection(account_id, strategy_id, inspection_date) -> dict
client.simulated_trading.list_daily_inspections(account_id, limit, inspection_date) -> dict
```

## Equity Module

```python
client.equity.get_stock_score(stock_code, as_of_date) -> dict
client.equity.list_stocks(sector, min_score, limit) -> list
client.equity.get_stock_detail(stock_code) -> dict
client.equity.get_recommendations(regime, limit) -> list
client.equity.analyze_stock(stock_code, as_of_date) -> dict
client.equity.get_financials(stock_code, report_type, limit) -> list
client.equity.get_valuation(stock_code, as_of_date) -> dict
```

## Fund Module

```python
client.fund.get_fund_score(fund_code, as_of_date) -> dict
client.fund.list_funds(fund_type, min_score, limit) -> list
client.fund.get_fund_detail(fund_code) -> dict
client.fund.get_recommendations(regime, fund_type, limit) -> list
client.fund.analyze_fund(fund_code, as_of_date) -> dict
client.fund.get_performance(fund_code, period) -> dict
client.fund.get_holdings(fund_code, as_of_date) -> list
```

## Sector Module

```python
client.sector.list_sectors(limit) -> list
client.sector.get_sector_score(sector_name, as_of_date) -> dict
client.sector.get_recommendations(regime, limit) -> list
client.sector.analyze_sector(sector_name, as_of_date) -> dict
client.sector.get_sector_stocks(sector_name, order_by, limit) -> list
client.sector.get_hot_sectors(limit) -> list
client.sector.compare_sectors(sector_names) -> dict
```

## Strategy Module

```python
client.strategy.list_strategies(status, limit) -> list
client.strategy.get_strategy(strategy_id) -> dict
client.strategy.create_strategy(name, strategy_type, description, params) -> dict
client.strategy.execute_strategy(strategy_id, as_of_date) -> dict
client.strategy.bind_portfolio_strategy(portfolio_id, strategy_id) -> dict
client.strategy.unbind_portfolio_strategy(portfolio_id) -> dict
client.strategy.get_strategy_performance(strategy_id, start_date, end_date) -> dict
client.strategy.get_strategy_signals(strategy_id, status, limit) -> list
client.strategy.get_strategy_positions(strategy_id) -> list
client.strategy.list_position_rules(strategy_id, is_active, limit) -> list
client.strategy.get_position_rule(rule_id) -> dict
client.strategy.create_position_rule(...) -> dict
client.strategy.update_position_rule(rule_id, **updates) -> dict
client.strategy.evaluate_position_rule(rule_id, context) -> dict
client.strategy.get_strategy_position_rule(strategy_id) -> dict
client.strategy.evaluate_strategy_position_management(strategy_id, context) -> dict
```

### Alpha Trigger Module

```python
client.alpha_trigger.list_triggers() -> list[dict]
client.alpha_trigger.get_trigger(trigger_id) -> dict
client.alpha_trigger.create_trigger(payload) -> dict
client.alpha_trigger.list_candidates() -> list[dict]
client.alpha_trigger.get_candidate(candidate_id) -> dict
client.alpha_trigger.update_candidate_status(candidate_id, status) -> dict
```

`status` 支持：`WATCH` / `CANDIDATE` / `ACTIONABLE` / `EXECUTED` / `CANCELLED`

### Decision Rhythm Module

```python
client.decision_rhythm.list_quotas() -> list[dict]
client.decision_rhythm.list_cooldowns() -> list[dict]
client.decision_rhythm.list_requests() -> list[dict]
client.decision_rhythm.submit(payload) -> dict
client.decision_rhythm.submit_batch(payload) -> dict
client.decision_rhythm.summary(payload=None) -> dict
client.decision_rhythm.trend_data(payload=None) -> dict
client.decision_rhythm.reset_quota(payload) -> dict
client.decision_rhythm.update_quota(payload) -> dict
client.decision_rhythm.execute_request(request_id, payload) -> dict
client.decision_rhythm.cancel_request(request_id, reason=None) -> dict
client.decision_rhythm.get_request(request_id) -> dict
```

### Decision Workflow Module

```python
client.decision_workflow.precheck(candidate_id) -> dict
client.decision_workflow.list_recommendations(
    account_id,
    status=None,
    user_action=None,
    security_code=None,
    recommendation_id=None,
    include_ignored=False,
    page=1,
    page_size=20,
) -> dict
client.decision_workflow.refresh_recommendations(
    account_id=None,
    security_codes=None,
    force=False,
    async_mode=True,
) -> dict
client.decision_workflow.apply_recommendation_action(
    recommendation_id,
    action,
    account_id=None,
    note=None,
) -> dict
client.decision_workflow.get_funnel_context(
    trade_id="unknown",
    backtest_id=None,
) -> dict
```

`action` 支持：`watch` / `adopt` / `ignore` / `pending`

`client.decision_workflow.get_funnel_context()` 返回的 `data["step3_sectors"]` 额外包含：

| Field | Type | Description |
|-------|------|-------------|
| `rotation_data_source` | `str \| null` | `fresh_generation` / `stored_signal` / `stored_signal_fallback` |
| `rotation_is_stale` | `bool` | `true` 表示实时重算失败，当前回退到已落库旧信号 |
| `rotation_warning_message` | `str \| null` | 面向用户的降级提示 |
| `rotation_signal_date` | `str \| null` | 当前展示轮动信号的日期 |

### Pulse Module

```python
client.pulse.get_current() -> dict
client.pulse.get_history(limit=30) -> list[dict]
client.pulse.calculate() -> dict
client.pulse.get_navigator() -> dict
client.pulse.get_action_recommendation() -> dict
```

## Realtime Module

```python
client.realtime.get_price(asset_code) -> dict
client.realtime.get_multiple_prices(asset_codes) -> dict
client.realtime.get_price_history(asset_code, period, limit) -> list
client.realtime.get_market_summary() -> dict
client.realtime.get_sector_performance() -> list
client.realtime.get_top_movers(direction, limit) -> list
client.realtime.list_alerts(status, limit) -> list
client.realtime.create_alert(asset_code, condition, threshold, message) -> dict
client.realtime.delete_alert(alert_id) -> None
```

## Data Center Module

```python
client.data_center.list_providers() -> list[dict]
client.data_center.get_provider(provider_id) -> dict
client.data_center.create_provider(payload) -> dict
client.data_center.update_provider(provider_id, payload, partial=True) -> dict
client.data_center.delete_provider(provider_id) -> dict
client.data_center.test_provider_connection(provider_id) -> dict
client.data_center.get_provider_status() -> list[dict]
client.data_center.get_macro_series(indicator_code, start, end, limit, source) -> dict
client.data_center.get_price_history(asset_code, start, end, freq, adjustment, limit) -> dict
client.data_center.get_latest_quotes(asset_code) -> dict
client.data_center.get_fund_nav(fund_code, start, end, limit) -> dict
client.data_center.get_financials(asset_code, limit) -> dict
client.data_center.get_valuations(asset_code, start, end, limit) -> dict
client.data_center.get_news(asset_code, limit) -> dict
client.data_center.get_capital_flows(asset_code, period, limit) -> dict
```

### Quote Snapshot (dict)

| Key | Type | Description |
|-----|------|-------------|
| `stock_code` | `str` | Stock code (Tushare format) |
| `price` | `str` | Current price |
| `change` | `str \| None` | Price change |
| `change_pct` | `float \| None` | Change percentage |
| `volume` | `int \| None` | Volume |
| `amount` | `str \| None` | Turnover amount |
| `turnover_rate` | `float \| None` | Turnover rate |
| `source` | `str` | Provider name |

### Provider Status (dict)

| Key | Type | Description |
|-----|------|-------------|
| `provider_name` | `str` | Provider name |
| `capability` | `str` | realtime_quote/capital_flow/stock_news/technical_factors |
| `status` | `str` | healthy/degraded/circuit_open/unknown |
| `consecutive_failures` | `int` | Consecutive failure count |
| `avg_latency_ms` | `float \| None` | Average latency |

## Exceptions

| Exception | Description | HTTP Status |
|-----------|-------------|-------------|
| `AgomTradeProAPIError` | Base API error | - |
| `AuthenticationError` | Invalid credentials | 401, 403 |
| `ValidationError` | Invalid request data | 400 |
| `NotFoundError` | Resource not found | 404 |
| `ConflictError` | Resource conflict | 409 |
| `RateLimitError` | Rate limit exceeded | 429 |
| `ServerError` | Server error | 5xx |
| `ConnectionError` | Network error | - |
| `TimeoutError` | Request timeout | - |
| `ConfigurationError` | Invalid configuration | - |

## Type Aliases

```python
# Regime types
RegimeType = Literal["Recovery", "Overheat", "Stagflation", "Deflation"]
GrowthLevel = Literal["up", "down", "neutral"]
InflationLevel = Literal["up", "down", "neutral"]

# Signal types
SignalStatus = Literal["pending", "approved", "rejected", "invalidated"]

# Policy types
PolicyGear = Literal["stimulus", "neutral", "tightening"]
```
