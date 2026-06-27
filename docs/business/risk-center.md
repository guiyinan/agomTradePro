# 集中风控中心

> 最后更新：2026-06-27
> 状态：V1 已落地，已接入账户止盈止损、模拟盘自动交易买入前检查、策略执行编排买入前检查、SDK/MCP。

## 1. 定位

`risk_center` 是账户/组合级风控配置的统一来源，负责管理：

- 全局底线：系统级不可轻易突破的总仓位、单标的、现金、回撤、止损等约束。
- 全局模板：`conservative`、`moderate`、`aggressive`、`custom` 风险偏好模板。
- 账户策略：按 canonical `account_id` 独立设置，可从模板继承并覆盖部分字段。
- 管理员例外：必须包含 `reason`、`created_by`、`expires_at`，只在有效期内突破指定字段。
- 有效策略解析：输出最终参数、继承来源、底线压制和例外应用说明。

V1 的目标不是替换所有交易模块，而是提供统一配置、统一解析、统一前置风控门。后续新增交易入口必须优先调用 `risk_center.application.trade_guard.EvaluatePreTradeRiskUseCase` 或对应 SDK/MCP 能力。

## 2. 覆盖优先级

有效策略按以下顺序解析：

1. 账户策略优先于模板；账户策略未设置字段从模板继承。
2. 没有账户策略时，按账户风险偏好匹配模板；仍没有则使用 `moderate` fallback 模板。
3. 全局底线默认不可突破。
4. 有效管理员例外可以临时突破指定字段，但只能在 `expires_at` 前生效。
5. 解析结果会返回 `sources`、`floor_applied`、`exceptions_applied`，供 API、页面、MCP 和审计解释。

所有比例字段统一使用小数比例：`0.8` 表示 80%，`0.05` 表示 5%。

## 3. 参数契约

| 字段 | 含义 | 典型用途 |
|------|------|----------|
| `max_total_position_pct` | 总持仓占总资产上限 | 买入前限制组合总暴露 |
| `max_single_position_pct` | 单标的占总资产上限 | 买入前限制个券集中度 |
| `max_daily_loss_pct` | 最大日亏损比例 | 策略执行风险门、后续日内交易守门 |
| `max_drawdown_pct` | 最大回撤比例 | 账户级停机/降风险依据 |
| `max_stop_loss_pct` | 最大止损比例 | 账户止损任务会收紧现有持仓止损配置 |
| `take_profit_pct` | 止盈比例 | 账户止盈任务会收紧现有止盈目标 |
| `min_cash_pct` | 最低现金比例 | 买入前限制现金底线 |
| `force_stop_loss` | 是否强制止损 | 后续交易执行链路统一读取 |
| `hard_exclusions` | 硬排除标的列表 | 买入/卖出前置检查均会拒绝命中标的 |

## 4. 已接入交易链路

### 4.1 账户止盈止损任务

账户层周期任务已读取 `ResolveEffectiveRiskPolicyForAccountUseCase`：

- `max_stop_loss_pct` 会收紧原有持仓止损比例。
- `take_profit_pct` 会收紧原有止盈触发比例。
- 风控中心解析失败时沿用原持仓配置，避免历史任务中断。

### 4.2 模拟盘自动交易

`apps.simulated_trading.application.auto_trading_engine.AutoTradingEngine` 已在两条买入路径接入集中风控：

- 策略信号买入：下单前调用 `EvaluatePreTradeRiskUseCase`。
- 传统候选池买入：下单前调用 `EvaluatePreTradeRiskUseCase`。

当前检查内容：

- `hard_exclusions`
- `max_total_position_pct`
- `max_single_position_pct`
- `min_cash_pct`
- 可用现金是否覆盖订单金额

自动交易采用失败关闭策略：风控解析异常或风控拒绝时跳过买入；卖出不被仓位/现金上限阻断，便于降风险。

### 4.3 策略执行编排

`apps.strategy.application.execution_orchestrator.ExecutionOrchestrator` 已在原有 `PreTradeRiskGate` 之后、`OrderIntent` 保存之前接入集中风控。

效果：

- 风控中心拒绝时返回 `status="rejected"`。
- 不保存 `OrderIntent`。
- 不提交 paper/broker adapter。
- 风控中心异常按拒单处理，避免自动执行绕过集中底线。

## 5. HTTP API

所有接口都需要认证。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/risk-center/floor/` | 读取全局底线 |
| `PUT` | `/api/risk-center/floor/` | 更新全局底线，管理员权限 |
| `GET` | `/api/risk-center/templates/` | 列出模板 |
| `POST` | `/api/risk-center/templates/` | 创建模板，管理员权限 |
| `GET` | `/api/risk-center/templates/{id}/` | 读取模板 |
| `PUT/PATCH` | `/api/risk-center/templates/{id}/` | 更新模板，管理员权限 |
| `GET` | `/api/risk-center/account-policies/` | 列出账户策略 |
| `POST` | `/api/risk-center/account-policies/` | 创建或更新账户策略 |
| `GET` | `/api/risk-center/account-policies/by-account/{account_id}/` | 按账户读取策略 |
| `PUT/PATCH` | `/api/risk-center/account-policies/{id}/` | 更新账户策略 |
| `POST` | `/api/risk-center/account-policies/{id}/apply-template/` | 对账户策略应用模板 |
| `GET` | `/api/risk-center/exceptions/` | 列出例外，可用 `account_id` 过滤 |
| `POST` | `/api/risk-center/exceptions/` | 创建例外，管理员权限 |
| `GET` | `/api/risk-center/effective-policy/?account_id=...` | 解析账户最终生效策略 |

页面入口：`/risk-center/`。

## 6. SDK

Python SDK 入口：

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient()
floor = client.risk_center.get_floor()
effective = client.risk_center.get_effective_policy(account_id=1)
client.risk_center.upsert_account_policy(
    {
        "account_id": 1,
        "risk_profile": "moderate",
        "max_total_position_pct": 0.75,
        "reason": "reduce exposure after drawdown",
    }
)
```

核心方法：

- `get_floor()`
- `update_floor(payload)`
- `list_templates()`
- `create_template(payload)`
- `update_template(template_id, payload, partial=True)`
- `list_account_policies()`
- `upsert_account_policy(payload)`
- `update_account_policy(policy_id, payload, partial=True)`
- `get_account_policy(account_id)`
- `apply_template_to_policy(policy_id, template_id)`
- `list_exceptions(account_id=None)`
- `create_exception(payload)`
- `get_effective_policy(account_id)`

## 7. MCP 工具

真实 MCP 工具已注册在 `sdk/agomtradepro_mcp/tools/risk_center_tools.py`：

| 工具名 | 说明 |
|--------|------|
| `get_risk_floor` | 读取全局底线 |
| `update_risk_floor` | 更新全局底线 |
| `list_risk_templates` | 列出风险模板 |
| `upsert_account_risk_policy` | 创建或更新账户策略 |
| `get_account_risk_policy` | 按账户读取账户策略 |
| `get_effective_risk_policy` | 解析最终生效策略 |
| `list_risk_exceptions` | 列出管理员例外 |
| `create_risk_exception` | 创建管理员例外 |

这些工具通过 SDK 调用 HTTP API，不直接访问 Django ORM。

## 8. 后续接入要求

新增交易入口必须满足：

1. 下单前调用集中风控解析或 `EvaluatePreTradeRiskUseCase`。
2. 买入必须执行硬排除、总仓位、单标的、现金底线检查。
3. 风控中心异常默认失败关闭，除非该入口明确是只读预览。
4. 拒单结果必须可被审计，至少保留 `violations` 和 `effective_policy` 摘要。
5. 不允许在交易模块重新硬编码全局底线；全局底线只归 `risk_center`。

## 9. 测试覆盖

当前覆盖：

- Domain 策略解析：模板继承、全局底线、例外有效期、fallback 模板。
- Application 交易门：允许、硬排除/限额拒绝、卖出不受买入限额阻断。
- 自动交易：风控中心拒绝时不调用买入用例。
- 策略执行：风控中心拒绝时不保存订单、不提交 adapter。
- API：全局底线、模板、账户策略、例外、生效策略。
- MCP：注册 smoke test 和工具执行 smoke test。
