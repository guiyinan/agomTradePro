# Web → TUI M4 Audit Manual Trade Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-audit-manual-trade-w44`；覆盖手动交易复盘 1 个 B 类 route
  template，进入 `execution.audit`。
- 新增 6 个 curated action：导入批次、最近成交、CSV 预览、CSV 确认导入、
  推荐执行关联和四分支决策复盘。
- Audit 新增 owner-scoped 汇总 adapter；Account 新增 UTF-8 CSV TUI
  preview/commit adapter；Backtest 新增四分支比较用例和 typed API。业务逻辑留在
  owner Application 层，Terminal 只发布 metadata 和通用结果投影。
- TUI 文件字段按 runtime 真实能力读取文本，限制为 UTF-8 CSV、2 MiB；Classic
  继续承载 XLS/XLSX 和更大文件，不把二进制格式伪装成已迁能力。
- 四分支复盘一次运行 `actual`、`no_action`、`system_plan`、`delayed_1d`，
  返回日期对齐净值曲线与分支指标。新增产品无关的 `table_chart` 投影契约，
  同一动作同时呈现图表和表格，避免为看完整结果重复创建回测。
- CSV 正式导入和四分支复盘均要求确认并记录审计；Account/Backtest owner API
  继续执行组合归属和认证边界。
- Classic 页面显示准确 `execution.audit` deep link，并继续保留到 M5。

## 验证与风险

- 核心定向：`5 passed`，覆盖 owner CSV、越权拒绝、四分支合并、TUI 发布和
  `table_chart` 投影。
- Manual Trade、Audit API edge 与 inventory/static 联合回归：`27 passed`。
- 完整 TUI Workbench：`233 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  4 migrated / 13 backlog。
- `black`、`ruff` 通过；14 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server CSV preview→commit、导入后刷新、四分支图表空态/部分失败、
  键盘与三 viewport UAT；XLS/XLSX 仍仅由 Classic 承载。Classic 删除继续受
  M5 稳定版本、不少于 14 个自然日、旧入口占比、错误率和回滚演练门槛约束。
