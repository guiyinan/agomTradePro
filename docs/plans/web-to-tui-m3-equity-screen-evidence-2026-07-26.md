# Web → TUI M3 Equity Screen Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-equity-screen-w29`；覆盖个股手动筛选 1 个复杂 route template。
- canonical screen：`research.asset-lab`；`equity.screen-stocks` 支持自动/指定 Regime、
  ROE、PE、PB、营收增长、利润增长、负债率和最多返回数量。
- TUI 不暴露 `custom_rule` raw JSON。Equity owner serializer 新增六个 write-only 扁平字段，
  在 Interface 边界合并为既有 `ScreenStocksRequest.custom_rule`，Domain/Application
  用例和筛选语义不变。
- 结果使用 8 列原生 datagrid，继续返回 owner API 的 `items`；执行动作显式确认。
- Classic 页增加准确 deep link。其系统 Alpha 推荐入口属于 Dashboard Alpha owner 的后续
  M3 wave，财务/估值同步属于数据修复支持任务，不被本 wave 虚报为已迁能力。

## 验证与风险

- serializer + TUI metadata + IA：`8 passed`。
- Classic 页面 + 实际 `/api/equity/screen/` 契约：`3 passed`。
- `ruff` 通过；Equity serializer 与 Terminal metadata mypy：0 regressions、0 legacy errors。
- live-server 条件筛选、空态、owner use-case 失败态、导出和长结果 UAT 尚未完成；Dashboard
  Alpha 自动推荐与数据同步需由对应后续 wave 提供完整 TUI 闭环。
