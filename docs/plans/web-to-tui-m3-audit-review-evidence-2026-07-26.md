# Web → TUI M3 Audit Review Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-audit-review-w41`；覆盖审计复盘首页、归因报告列表、本人/管理员
  操作日志、本人/管理员决策链共 6 个 route template，统一进入
  `execution.audit`。
- 新增 10 个 curated action：复盘概览、归因报告列表、报告生成预览与确认生成、
  owner/admin 操作日志列表与详情、管理员统计与 JSON 证据导出、owner/admin
  决策链列表与详情。
- 新增两个认证只读 adapter。概览只返回最新验证、最近 5 份报告和最多 5 个待复盘
  回测；报告列表按 `heuristic` / `brinson` 筛选并限制为 50 条，同时标记已生成和
  待生成回测。适配层只调用 Audit Application service，不直接访问 ORM。
- 报告生成继续复用既有 preview 与正式生成 API；TUI 正式动作要求确认和审计，
  未复制归因业务逻辑。
- 操作日志和决策链继续复用 owner API 的最终授权：普通用户仅能读取本人证据，
  审计管理员可读取全量。统计与 JSON 导出 action 只对管理员发布；CSV 由 TUI
  datagrid 的本地导出能力覆盖。
- 6 个 Classic 页面均可得到准确 deep link；`decision_traces_admin.html` 继承
  `my_decision_traces.html` 的迁移提示。所有 Classic 页面继续保留到 M5。

## 验证与风险

- Audit API edge：`9 passed`，其中新增报告筛选、候选标记与非法方法拒绝契约。
- Audit TUI 元数据定向：`1 passed`，验证普通用户/管理员 action 可见性、确认生成
  与 datagrid 语义。
- Audit Classic 页面与权限回归：`59 passed`。
- 完整 TUI Workbench：`230 passed`；inventory/static：`5 passed`。
- migration inventory：196 templates / 117 route pages / A131 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `ruff` 通过；5 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 概览空态、报告 preview→generate、owner/admin 隔离、日志详情与
  JSON 导出失败态 UAT 尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和
  telemetry 门槛约束。
