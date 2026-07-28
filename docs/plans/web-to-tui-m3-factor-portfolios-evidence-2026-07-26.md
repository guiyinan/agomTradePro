# Web → TUI M3 Factor Portfolios Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-factor-portfolios-w33`；覆盖因子组合配置 1 个 route template，并完成
  Factor 三个 route consumer 的 M3 收口。
- canonical screen：`research.asset-lab`。发布列表、详情、创建、局部更新、设置/移除
  单项因子权重、启用、停用、生成组合和删除 10 个动作。
- TUI 配置表单只发布名称、股票池、筛选条件、选股数量、调仓频率、持仓权重方式与风险
  上限等标量字段；`factor_weights` 原始 JSON 未进入创建或更新表单。
- 新增 owner `factor-weight` / `remove-factor-weight` API。Application 先验证新增权重引用的
  因子定义，Repository 再原子更新 JSON 存储中的单个键；移除动作允许清理定义已删除的
  陈旧键。
- 股票池、调仓频率和权重方式的选项抽为 Factor Application 唯一真源，页面 use case、
  serializer 和 TUI metadata 共用；serializer 同步补齐数值范围与 ChoiceField 边界。
- Classic 页面增加准确 TUI deep link；三个 route consumer 均已迁移，因此
  `factor/base.html` 转入 M5 随消费者清理，不冒充独立任务。

## 验证与风险

- 组合配置 CRUD、逐项权重、8 组非法输入、TUI metadata 与 IA：`17 passed`。
- 完整 TUI Workbench：`221 passed`。
- Django reverse 已确认三个关键 action 路径与 metadata 完全一致。
- `ruff` 通过；7 个 production owner / metadata 文件 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 配置草稿、逐项配权、绝对权重和校验、生成成功/失败、持仓长结果 UAT
  尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
