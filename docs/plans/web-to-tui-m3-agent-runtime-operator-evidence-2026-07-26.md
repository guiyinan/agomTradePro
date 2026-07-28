# Web → TUI M3 Agent Runtime Operator Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-agent-runtime-operator-w38`；覆盖任务列表/详情与提案列表/详情 4 个
  operator route template。
- canonical screen：`ai-ops.terminal`（兼容 alias：`ai-ops.agent-runtime`）。新增 9 个
  curated 动作：治理总览、任务列表/详情、提案列表/详情，以及提交、批准、拒绝、
  执行四个 proposal 状态机动作。
- 新增独立 typed operator API，保留 Classic 任务队列的状态/任务域/search/attention
  筛选和提案队列的状态/审批/风险/search 筛选；proposal detail 返回 guardrail、
  execution 与 task timeline 证据。任务详情复用既有 Operator Dashboard owner API。
- TUI 的 operator 动作使用 group-aware 可见性 predicate：普通认证用户不看到动作，
  staff/superuser 和 `operator` 组可见；API 仍以 `IsStaffOrOperator` 等价权限作为
  最终授权。四个 mutation 均显式确认并要求审计，状态机与 guardrail 仍由 owner
  Application use case 判定。
- 四个 Classic 页面增加准确 deep link；两个共享 partial 不冒充独立任务，转入 M5
  随消费者一起清理。

## 验证与风险

- Agent Runtime operator TUI/API/IA 定向：`8 passed`。
- Operator Dashboard 与 route compatibility：`37 passed`。
- 完整 TUI Workbench：`226 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；6 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 提交→批准/拒绝→执行、guardrail blocked、执行失败和空队列 UAT 尚未
  完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
