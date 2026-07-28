# Web → TUI M3 Ops Hubs Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-ops-hubs-w39`；覆盖管理控制台、设置中心、能力网关和 MCP 工具管理
  4 个 route template。
- 管理控制台与设置中心属于导航聚合页，不复制为新的 TUI screen。管理员复用
  `api-library.data-center` 及既有 owner screens；普通用户从设置中心进入
  `account.self-service`，Classic 兼容提示按角色给出准确入口。
- 能力网关按受众拆分：普通用户在 `capability-router.self-service` 获取 Token、
  Endpoint、Prompt 并管理自己的令牌；管理员在 `capability-router.mcp-center`
  查看语义键治理状态、审计和修正任务。
- MCP 工具管理复用既有 7 个 curated action，覆盖统计、列表、路由关闭列表、详情、
  同步、路由开关与 Terminal 开关，不新增重复的导航或 CRUD action。
- 语义治理新增 4 个管理员 action。既有批量 API 继续保持嵌套契约，新增
  `single-preview` / `single-apply` typed adapter，把一次修正收窄为标量字段；
  TUI 不要求用户填写 raw JSON。apply 保留幂等键、显式确认、审计和 owner
  Application 状态校验。
- 11 个近期兼容页共用一个迁移提示 partial。该 partial 已作为迁移期工件登记到
  矩阵与冻结规则，当前矩阵由 M0 的 195 个初始模板增至 196 个；它不是业务页面，
  将随最后一个 Classic 消费者在 M5 删除。

## 验证与风险

- Ops TUI/API/IA 定向：`8 passed`；Semantic Governance API 全文件：
  `6 passed`。
- MCP Tools 与设置中心页面回归：`44 passed`；完整 TUI Workbench：
  `227 passed`。
- inventory/static 单元测试：`5 passed`；migration inventory：
  196 templates / 117 route pages / A131 / B17 / C41 / D7；TUI static：
  407 rules / 5 sources。
- `black`、`ruff` 通过；4 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server Token/Prompt、MCP 同步/开关、语义预览/应用、角色跳转和错误态 UAT
  尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
