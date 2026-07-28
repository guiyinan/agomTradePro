# Web → TUI M3 Hedge Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-hedge-w34`；覆盖对冲对、组合快照和风险告警 3 个 route templates。
- canonical screen：`macro-regime.strategy`。发布 15 个动作：对冲对列表/详情/完整
  CRUD/启停/有效性检查，快照列表/最新/全量更新，以及告警列表/近期未解决/监控/解决。
- 普通认证用户仅能看到 7 个读或只读计算动作；管理员额外看到 8 个配置、状态和监控写
  动作。TUI 可见性与 owner `IsAdminUser` 权限双重保持，所有写入均显式确认。
- 对冲方法选项直接复用 `HedgeMethod` Domain enum；对冲对表单完整覆盖权重、调仓阈值、
  相关性窗口/范围、告警阈值、成本上限、目标 Beta 与启用状态。
- 三个 Classic 页面增加各自准确 deep link；全部 route consumer 已迁移，因此
  `hedge/base.html` 与其免责声明引用转入 M5 随消费者清理。

## 验证与风险

- Hedge owner API 与 TUI information architecture：`24 passed`。
- TUI 普通用户/管理员可见性与 15 动作完整性：`1 passed`。
- `ruff` 通过；2 个 production metadata 文件 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 对冲 CRUD、有效性计算、快照更新、监控生成与解决告警 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
