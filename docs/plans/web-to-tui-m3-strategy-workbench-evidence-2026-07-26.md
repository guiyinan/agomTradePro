# Web → TUI M3 Strategy Workbench Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-strategy-workbench-w40`；覆盖策略列表、创建、详情、编辑 4 个 route
  template，统一进入 `macro-regime.strategy`。
- 新增 35 个 curated action，覆盖策略列表/详情、默认停用创建、版本化更新、启停、
  删除，条件规则，脚本、AI、仓位配置，执行日志、预览与正式执行。
- 新增 typed strategy adapter：创建时强制 `is_active=false`；更新时不允许切换策略
  类型并由服务端把版本递增一次，保持 Classic 的版本语义。
- 新增 typed rule adapter。宏观、Regime、信号和双条件组合规则都通过标量、选择项
  与列表字段输入，由 owner Interface 生成 `condition_json`；请求中的未知字段会被
  拒绝，TUI 不接受也不展示 raw JSON。
- 规则、脚本、AI、仓位配置继续由既有 owner-scoped API 最终授权；普通用户只能
  操作本人策略，staff/superuser 保留现有全局运维覆盖。所有 mutation 显式确认并
  要求审计。
- `technical` 规则未发布创建动作：owner `CompositeRuleEvaluator` 当前明确标记为
  未实现，Classic 的该选项不能产生有效执行结果；本 wave 不把无效配置能力冒充为
  TUI 主任务。
- 4 个 Classic 页面增加准确 deep link；4 个策略编辑 partial 随 create/edit
  消费者进入 M5 清理，不冒充独立 route 任务。

## 验证与风险

- Strategy TUI/IA 定向：`7 passed`；typed adapter API：`2 passed`。
- Strategy API 全文件：`33 passed`；Classic 保存流、view 结构和前端绑定：
  `12 passed`。
- 完整 TUI Workbench：`228 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：196 templates / 117 route pages / A131 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；5 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 创建→配置→预览→启用→执行→日志、跨用户隔离、空态和失败态 UAT
  尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
