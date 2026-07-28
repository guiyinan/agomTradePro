# Web → TUI M2 Alpha Trigger Read Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-alpha-trigger-read-w17`；Classic routes：触发器/候选总览、
  触发器详情、候选详情和绩效复核，共 4 个 route templates。
- TUI：发布 10 个稳定业务 action，覆盖触发器列表/活跃项/详情、
  候选列表/可操作项/观察列表/详情，以及触发器统计、候选统计和绩效。
- `research.signals` 的默认任务和 P0 panel 改为 curated
  `alpha-trigger.candidate-actionable`，候选行可原生进入详情；不再把自动生成的
  API action key 作为用户入口真源。
- 候选视图保留风险等级、预期收益和执行跟踪；触发器详情保留触发条件、
  证伪条件、有效期和生命周期状态。
- 7 个 Alpha Trigger Classic page 均补齐登录保护；本 wave 的 4 个页面发布
  精确 TUI 兼容入口。

## 验证与风险

- Alpha Trigger API `22 passed`；Classic 登录边界包含其中 `4 passed`。
- TUI metadata 定向 `1 passed`；TUI 页面定向与 IA 合计 `7 passed`。
- ruff、增量 mypy、inventory 与 static contract 均通过。
- 真实 live-server 候选筛选→行详情→触发器详情→绩效窗口 UAT 待 M2
  合并前补齐。
- 创建、编辑和证伪规则构建器保留在下一 lifecycle-authoring wave；其
  Classic 页面暂留，不能在 mutation API gap 关闭前宣称任务等价。
