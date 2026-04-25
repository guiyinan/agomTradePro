# 模拟盘日更巡检（MCP/SDK/定时任务）

## 目标

为模拟账户提供每日自动巡检能力，输出：
- 宏观状态（Regime）
- 政策档位（Policy）
- Regime 配比矩阵驱动的大类偏离
- 策略配置驱动的单资产偏离与再平衡建议
- Pulse 战术覆盖（转折预警/弱脉搏时收紧大类偏离判断）
- 仓位规则评估（买卖价、止盈止损、建议仓位）

巡检结果全部入库，不做硬编码输出。

## 数据库模型

- 表：`simulated_daily_inspection_report`
- 模型：`DailyInspectionReportModel`
- 关键字段：
  - `account` / `strategy` / `position_rule`
  - `inspection_date`
  - `status` (`ok|warning|error`)
  - `macro_regime` / `policy_gear`
  - `checks`（逐标的明细 JSON）
  - `summary`（汇总 JSON）

唯一键：`(account, inspection_date)`，同日重复执行会覆盖更新。

## 定时任务

- 任务名：`simulated.daily_portfolio_inspection`
- 入口：`apps.simulated_trading.application.tasks.daily_portfolio_inspection_task`
- 默认参数：
  - `account_id=679`
  - `strategy_id=4`
- Beat 配置：`core/settings/base.py`
  - 每个交易日 `17:10` 自动执行

## 邮件通知

巡检任务结束后自动尝试发送邮件（`daily_portfolio_inspection_task` 内置）：
- 配置来源：数据库模型 `DailyInspectionNotificationConfigModel`（按账户管理）
- 支持：
  - 是否启用通知
  - 触发级别（仅预警/异常 或 全部状态）
  - 是否包含账户 owner 邮箱
  - 额外收件人邮箱列表

前端管理页面：
- `GET/POST /simulated-trading/my-accounts/{account_id}/inspection-notify/`

环境变量：
- `DEFAULT_FROM_EMAIL`（默认 `noreply@agomtradepro.com`）
- `DAILY_INSPECTION_EMAIL_ENABLED`（全局开关，默认 `true`）

## 后端 API

- `POST /api/simulated-trading/accounts/{account_id}/inspections/run/`
  - 手动触发巡检
  - body: `{ "strategy_id": 4, "inspection_date": "2026-02-08", "auto_create_proposal": false }`（可选）
- `GET /api/simulated-trading/accounts/{account_id}/inspections/?limit=20&inspection_date=2026-02-08`
  - 查询巡检历史

## SDK

`sdk/agomtradepro/modules/simulated_trading.py` 新增：
- `run_daily_inspection(account_id, strategy_id=None, inspection_date=None, auto_create_proposal=False)`
- `list_daily_inspections(account_id, limit=20, inspection_date=None)`

## MCP Tools

`sdk/agomtradepro_mcp/tools/simulated_trading_tools.py` 新增：
- `run_simulated_daily_inspection(account_id, strategy_id=None, inspection_date=None, auto_create_proposal=False)`
- `list_simulated_daily_inspections(account_id, limit=20, inspection_date=None)`

## 说明

- 若不传 `strategy_id`，服务会优先匹配 `position_rule.metadata.account_id == account_id` 的启用规则。
- 大类目标来自 `strategy.domain.allocation_matrix`，由当前 Regime、Policy 档位和 `metadata.allocation.risk_profile` 决定。
- 大类偏离阈值来自 `metadata.allocation.class_drift_threshold`，默认 `0.05`。
- Pulse 可通过 `metadata.allocation.pulse_overlay_enabled` 开关控制；默认开启。转折预警或 `regime_strength=weak` 时会降低权益目标并收紧大类偏离阈值，相关上下文写入巡检 `summary.pulse` 和再平衡草案 `metadata.pulse`。
- 单资产再平衡阈值和目标权重来自规则 `metadata.rebalance`。
- 未配置 `metadata.rebalance.target_weights` 时，单资产层只输出持仓检查，不会把目标权重默认为 0 触发误卖。

规则 metadata 示例：

```json
{
  "allocation": {
    "risk_profile": "moderate",
    "class_drift_threshold": 0.05,
    "asset_class_overrides": {
      "511010.SH": "fixed_income"
    },
    "pulse_overlay_enabled": true,
    "pulse_warning_equity_multiplier": 0.85,
    "pulse_weak_equity_multiplier": 0.9,
    "pulse_drift_threshold_multiplier": 0.75
  },
  "rebalance": {
    "target_weights": {
      "512880.SH": 0.3
    },
    "drift_threshold": 0.05
  }
}
```
