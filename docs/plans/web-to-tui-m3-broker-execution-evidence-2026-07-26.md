# Web → TUI M3 Broker Execution Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-broker-execution-w36`；覆盖 1 个共享 route template、7 个 Classic
  route pattern。
- canonical screen：`execution.accounts`，审计与对账动作仍按 metadata 归入
  `execution.audit`。共发布 33 个运行时动作，覆盖实盘就绪、订单列表/详情、连接状态、
  审批/拒绝/撤单、对账处置、操作审计、停止/恢复交易，以及管理员接入治理。
- 本 wave 补齐 15 个 Classic 管理员接入动作：投顾建议单下发、本地 Agent 绑定、
  账户授权、凭证轮换/撤销、连接同步和执行设置。除只读授权列表外，均采用
  preview/commit 双动作；commit 保留显式确认与审计要求。
- TUI 只发布有界标量或列表字段，不向用户暴露原始 JSON 对象。凭证密文结果使用
  `copyable_secret` 专用语义；普通用户看不到管理员接入动作，最终授权继续由
  Broker Execution owner Application/API 判定。
- Classic 共享工作台增加准确 TUI deep link，并继续作为 M5 前兼容和回滚工件。
  Classic 中的手工交易 CSV 属于 Audit owner，不计入本 wave 的迁移完成范围。

## 验证与风险

- Broker Execution TUI metadata 与 information architecture：`9 passed`。
- Broker Execution 全组件回归：`63 passed`。
- 完整 TUI Workbench：`224 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；runtime metadata 增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server preview→commit、一次性凭证展示、跨用户隔离、Agent/QMT 连接和失败恢复
  UAT 尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
