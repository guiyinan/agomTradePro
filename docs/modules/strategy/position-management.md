# 策略仓位管理（数据库驱动）

## 目标

仓位管理规则全部由数据库配置，不在代码中硬编码买卖价、止盈止损与仓位公式。

## 数据模型

- 表：`position_management_rule`
- 关联：`strategy` 一对一
- 关键字段：
  - `buy_condition_expr` / `sell_condition_expr`：买卖触发条件（布尔表达式）
  - `buy_price_expr` / `sell_price_expr`：买卖建议价（数值表达式）
  - `stop_loss_expr` / `take_profit_expr`：止损止盈价（数值表达式）
  - `position_size_expr`：仓位计算表达式（数值表达式）
  - `variables_schema`：变量定义（用于前端提示/文档）

## 表达式规则

- 使用受限 AST 安全解析
- 允许运算：
  - 算术：`+ - * / % **`
  - 比较：`== != < <= > >=`
  - 逻辑：`and or not`
  - 三元表达式：`a if condition else b`
- 允许函数：`min` `max` `abs` `round` `pow`
- 不允许导入、属性访问、内置函数逃逸等危险语法

## API

- `GET /api/strategy/position-rules/`
- `POST /api/strategy/position-rules/`
- `PATCH /api/strategy/position-rules/{id}/`
- `POST /api/strategy/position-rules/{id}/evaluate/`
- `GET /api/strategy/strategies/{id}/position_rule/`
- `POST /api/strategy/strategies/{id}/evaluate_position_management/`

请求示例：

```json
{
  "context": {
    "current_price": 98.0,
    "support_price": 97.5,
    "resistance_price": 108.0,
    "structure_low": 94.0,
    "atr": 1.5,
    "account_equity": 100000.0,
    "risk_per_trade_pct": 0.01
  }
}
```

返回示例：

```json
{
  "should_buy": false,
  "should_sell": false,
  "buy_price": 97.8,
  "sell_price": 107.85,
  "stop_loss_price": 94.0,
  "take_profit_price": 105.4,
  "position_size": 263.157895,
  "risk_reward_ratio": 2.0
}
```

## 初始化命令

命令：

```bash
python manage.py init_position_rules --template atr_risk
```

常用参数：

- `--strategy-id <id>`：只初始化某个策略
- `--template atr_risk|breakout_trend`：选择模板
- `--force`：覆盖已存在规则
- `--dry-run`：只预览，不写库

## 推荐做法

- 先由研究员在数据库配置模板规则，再按策略复制微调。
- 用 `variables_schema` 固化变量命名，避免线上运行缺变量。
- 上线前用 `evaluate` 接口批量回放历史样本，检查极端值和除零风险。

## 前端、SDK 与 MCP

前端入口：

- `/strategy/create/`
- `/strategy/{strategy_id}/edit/`
- `/strategy/{strategy_id}/`

创建/编辑策略页已经内置仓位规则编辑器，可直接选择模板并微调表达式。

SDK：

```python
client.strategy.create_position_rule(...)
client.strategy.update_position_rule(rule_id, is_active=False)
client.strategy.evaluate_strategy_position_management(strategy_id, context)
```

MCP：

- `list_position_rules`
- `create_position_rule`
- `update_position_rule`
- `get_strategy_position_rule`
- `evaluate_position_rule`
- `evaluate_strategy_position_management`

完整策略、AI 配置、模拟盘自动交易链路见：

- [strategy-auto-trading-mcp.md](strategy-auto-trading-mcp.md)
