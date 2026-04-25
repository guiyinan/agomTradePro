# 策略配置、MCP 与模拟盘自动交易

> 更新日期：2026-04-25

## 能力边界

本链路面向模拟盘与研究验证，不直接连接券商实盘。

可用能力：

- 在前端创建/编辑策略，配置规则、脚本、AI 参数和仓位规则。
- 将策略绑定到模拟账户。
- 通过页面、REST API、SDK 或 MCP 手动触发策略执行与模拟盘自动交易。
- 自动交易会记录订单、持仓、交易历史和账户绩效，后续可用回测/审计模块复盘。

不可视为已完成的实盘能力：

- 券商柜台/交易终端下单。
- 实盘订单回报、撤单、部分成交处理。
- 实盘级审批、熔断和灾备。

## 前端入口

- 策略列表：`/strategy/`
- 创建策略：`/strategy/create/`
- 编辑策略：`/strategy/{strategy_id}/edit/`
- 策略详情与执行测试：`/strategy/{strategy_id}/`
- 模拟账户管理：`/simulated-trading/accounts/`

创建/编辑策略页支持：

- 基础风控：单资产最大持仓、总持仓上限、止损比例。
- 规则策略：JSON 规则条件。
- 脚本策略：Python 脚本配置。
- AI 策略：Prompt 模板、Chain 配置、AI 服务商、温度、Token 上限、审核模式、置信度阈值。
- 仓位规则：买卖触发条件、建议买卖价、止损止盈、仓位计算表达式。

## REST API

### 策略管理

- `GET /api/strategy/strategies/`
- `POST /api/strategy/strategies/`
- `POST /strategy/{strategy_id}/execute/`
- `POST /api/strategy/bind-strategy/`
- `POST /api/strategy/unbind-strategy/`

### AI 策略配置

- `GET /api/strategy/ai-configs/?strategy={strategy_id}`
- `POST /api/strategy/ai-configs/`
- `PATCH /api/strategy/ai-configs/{config_id}/`

字段：

```json
{
  "strategy": 12,
  "prompt_template": null,
  "chain_config": null,
  "ai_provider": 3,
  "temperature": 0.3,
  "max_tokens": 1200,
  "approval_mode": "conditional",
  "confidence_threshold": 0.75
}
```

`approval_mode` 可选值：

- `always`：必须人工审核
- `conditional`：按置信度条件审核
- `auto`：自动执行并监控

### 仓位规则

- `GET /api/strategy/position-rules/?strategy={strategy_id}`
- `POST /api/strategy/position-rules/`
- `PATCH /api/strategy/position-rules/{rule_id}/`
- `POST /api/strategy/position-rules/{rule_id}/evaluate/`
- `GET /api/strategy/strategies/{strategy_id}/position_rule/`
- `POST /api/strategy/strategies/{strategy_id}/evaluate_position_management/`

### 模拟盘自动交易

- `POST /api/simulated-trading/auto-trading/run/`

请求：

```json
{
  "trade_date": "2026-04-25",
  "account_ids": [7, 8]
}
```

`account_ids` 可省略；省略时扫描所有活跃且开启自动交易的模拟账户。

执行原则：

- 账户绑定激活策略时，走 `StrategyExecutionGateway`。
- 账户未绑定策略时，走兼容的旧自动交易逻辑。
- 指定 `account_ids` 时只处理目标账户。

## Python SDK

```python
from datetime import date

from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(
    base_url="http://127.0.0.1:8000",
    api_token="your_token",
)

strategy = client.strategy.create_strategy(
    name="AI 模拟盘策略",
    strategy_type="ai_driven",
    description="用于模拟盘自动交易验证",
    params={"max_position_pct": 20, "max_total_position_pct": 95},
)

client.strategy.create_ai_strategy_config(
    strategy_id=strategy["id"],
    ai_provider_id=None,
    temperature=0.3,
    max_tokens=1200,
    approval_mode="conditional",
    confidence_threshold=0.75,
)

client.strategy.create_position_rule(
    strategy_id=strategy["id"],
    name="ATR 风险仓位规则",
    buy_condition_expr="current_price <= support_price",
    sell_condition_expr="current_price >= resistance_price",
    buy_price_expr="support_price",
    sell_price_expr="resistance_price",
    stop_loss_expr="buy_price - 2 * atr",
    take_profit_expr="buy_price + 3 * atr",
    position_size_expr="(account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price)",
)

client.strategy.bind_portfolio_strategy(portfolio_id=7, strategy_id=strategy["id"])

result = client.simulated_trading.run_auto_trading(
    trade_date=date(2026, 4, 25),
    account_ids=[7],
)
```

## MCP 工具

策略配置：

- `list_strategies`
- `create_strategy`
- `execute_strategy`
- `bind_portfolio_strategy`
- `unbind_portfolio_strategy`
- `list_ai_strategy_configs`
- `get_strategy_ai_config`
- `create_ai_strategy_config`
- `update_ai_strategy_config`
- `list_position_rules`
- `create_position_rule`
- `update_position_rule`
- `get_strategy_position_rule`
- `evaluate_position_rule`
- `evaluate_strategy_position_management`

模拟盘：

- `list_simulated_accounts`
- `get_simulated_account`
- `execute_simulated_trade`
- `get_simulated_positions`
- `get_simulated_performance`
- `run_simulated_auto_trading`
- `run_simulated_daily_inspection`
- `list_simulated_daily_inspections`

Agent 操作示例：

```text
1. 调用 list_simulated_accounts(status="active") 找到账户。
2. 调用 list_strategies(status="active") 找到策略。
3. 调用 bind_portfolio_strategy(portfolio_id, strategy_id) 绑定。
4. 调用 get_strategy_ai_config(strategy_id) 检查 AI 配置。
5. 调用 get_strategy_position_rule(strategy_id) 检查仓位规则。
6. 调用 run_simulated_auto_trading(account_ids=[portfolio_id]) 执行模拟盘自动交易。
7. 调用 get_simulated_performance(account_id) 和 list_simulated_daily_inspections(account_id) 复盘。
```

## 验证命令

```bash
pytest sdk/tests/test_sdk/test_strategy_module.py sdk/tests/test_sdk/test_extended_module_endpoints.py -q
pytest sdk/tests/test_mcp/test_tool_registration.py sdk/tests/test_mcp/test_tool_execution.py -q
pytest tests/integration/strategy/test_strategy_page_save_flow.py tests/integration/test_strategy_auto_trading_integration.py -q
```
