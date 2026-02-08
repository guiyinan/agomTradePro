# 模拟盘日更巡检（MCP/SDK/定时任务）

## 目标

为模拟账户提供每日自动巡检能力，输出：
- 宏观状态（Regime）
- 政策档位（Policy）
- 仓位偏离与再平衡建议
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

## 后端 API

- `POST /simulated-trading/api/accounts/{account_id}/inspections/run/`
  - 手动触发巡检
  - body: `{ "strategy_id": 4, "inspection_date": "2026-02-08" }`（可选）
- `GET /simulated-trading/api/accounts/{account_id}/inspections/?limit=20&inspection_date=2026-02-08`
  - 查询巡检历史

## SDK

`sdk/agomsaaf/modules/simulated_trading.py` 新增：
- `run_daily_inspection(account_id, strategy_id=None, inspection_date=None)`
- `list_daily_inspections(account_id, limit=20, inspection_date=None)`

## MCP Tools

`sdk/agomsaaf_mcp/tools/simulated_trading_tools.py` 新增：
- `run_simulated_daily_inspection(account_id, strategy_id=None, inspection_date=None)`
- `list_simulated_daily_inspections(account_id, limit=20, inspection_date=None)`

## 说明

- 若不传 `strategy_id`，服务会优先匹配 `position_rule.metadata.account_id == account_id` 的启用规则。
- 再平衡阈值和目标权重来自规则 `metadata.rebalance`。
