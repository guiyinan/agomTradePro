# Web → TUI M3 Decision Workspace Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-decision-workspace-w26`；覆盖每日决策工作台 1 个 route template。
- canonical screen：`command-center.decision-flow`。既有 owner JSON API 已覆盖工作台汇总、
  今日队列、推荐与冲突查询、推荐处置、调仓计划生成/更新/详情，以及执行审批的
  preview/approve/reject。
- 本 wave 补齐三个原 Classic 工作台仍依赖、但 published TUI 尚未提供的确认式任务：
  账户推荐刷新、系统证伪模板生成、AI 证伪草稿生成。字段使用普通表单、select、
  checkbox 和 textarea，不要求用户手写 raw JSON。
- Classic 页面发布准确的 TUI deep link，兼容期内继续保留。矩阵中的旧 URL 最终策略仍是
  `redirect_to_tui`，但只有满足 M5 的稳定版本、14 日、访问量、错误率和回滚演练门槛后
  才执行切换。

## HTML partial 边界

- `decision/steps/*.html` 由六个 HTMX 端点返回 HTML，不是 JSON API，不能作为 TUI action
  的完成证据。
- TUI 的主读取入口使用 `/api/decision/workspace/aggregated/` 等 owner JSON 契约。
- 六个 step partial 与一个无独立路由的 audit partial 已转入 M5 `remove_with_consumer`；
  在 Classic 工作台退出门槛满足前不删除。

## 验证与风险

- Decision owner/page 定向测试：`11 passed`，覆盖推荐刷新输入边界、系统/AI 证伪草稿、
  不可靠 Pulse 降级和 Classic 页面渲染。
- TUI metadata + IA：`7 passed`。
- 完整 `tests/unit/test_tui_workbench.py`：`214 passed`。
- `ruff` 通过；新增/修改 production metadata 文件 mypy：0 regressions、0 legacy errors。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7。
- TUI static source contract：407 rules / 5 sources。
- 真实 live-server 的“汇总→刷新推荐→采纳/忽略→生成计划→证伪草稿→审批”角色化 UAT、
  错误率与旧入口访问量观测尚未执行；这些是 M5 前的硬门槛。
