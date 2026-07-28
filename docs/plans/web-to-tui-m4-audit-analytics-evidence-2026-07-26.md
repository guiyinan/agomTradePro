# Web → TUI M4 Audit Analytics Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-audit-analytics-w43`；覆盖归因明细、指标绩效和阈值验证 3 个
  B 类 route template，统一进入 `execution.audit`。
- 新增 12 个 curated action：归因明细与贡献柱状图、指标绩效列表/柱状图/详情、
  阈值列表/历史折线图、阈值更新 preview/commit、验证运行 preview/commit 和
  验证详情。
- 新增 3 个认证只读 TUI adapter。适配层只调用 Audit Application service，
  不直接访问 ORM；归因收益统一投影为百分比，指标 F1/稳定性统一投影为百分比，
  阈值历史统一展开为带观测标签、旧值、新值和差异值的图表行。
- schema v3、metadata validator 与结果投影显式支持 `line`、`bar`、`pie`
  `chart_type`。未声明时继续默认 `line`，保持既有 action 兼容；本 wave 使用
  `bar` 表达归因贡献和指标对比，使用 `line` 表达阈值历史。
- 阈值更新和验证运行只对管理员发布，正式动作要求确认和审计，并继续由 owner
  API 执行最终授权；普通用户只能读取已授权的分析结果。
- 3 个 Classic 页面均显示迁移提示并提供 `execution.audit` deep link；页面继续
  保留到 M5，不在兼容观察期内提前删除。

## 验证与风险

- 定向 Audit API/TUI/static：`16 passed`，覆盖百分比投影、阈值历史展开、
  `bar` 图表投影和管理员 mutation 可见性。
- Audit 阈值/验证接口回归：`11 passed`。
- Audit 归因工作流、API 与 Classic 页面回归：`39 passed`。
- 完整 TUI Workbench：`231 passed`；inventory/static：`5 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  3 migrated / 14 backlog。
- `ruff` 通过；6 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 图表空态、tooltip/键盘、三 viewport、阈值
  preview→commit 和 owner/admin 隔离 UAT；Classic 删除仍受 M5 稳定发布、
  不少于 14 个自然日、旧入口占比、错误率和回滚演练门槛约束。
