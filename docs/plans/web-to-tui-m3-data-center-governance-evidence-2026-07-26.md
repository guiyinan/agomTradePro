# Web → TUI M3 Data Center Governance Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-data-center-governance-w42`；覆盖宏观数据治理、市场温度计、发布机构、
  Universe、Provider 健康和 Provider 配置共 6 个 route template，统一进入
  staff-only `api-library.data-center`。
- 发布 20 个管理员任务：宏观治理证据/执行，Provider 列表/连接测试/健康，
  Publisher 列表/详情/增删改，Universe 配置/摘要/更新，市场温度计当前值/配置/
  更新/同步/重算/导入预览/正式导入。
- Provider 与 Publisher 的既有 auto read action 由 curated metadata 原位替换，
  保留稳定 action key 与既有 `04 服务商` / `05 发布机构` 分组，同时补充真实
  datagrid 契约并收紧为管理员可见。Indicator 管理 read 的错误 audience 也修正为
  admin；Data Center screen 对普通用户继续整体返回 403。
- 新增 staff-only 宏观治理 adapter：GET 返回治理证据；POST 只接受四个
  allow-listed action，并调用既有 Application service。正式动作要求确认与审计。
- 新增市场温度计配置 adapter：把阈值对象展开为 9 个可选标量字段，在 owner
  Interface 合并回既有配置契约；TUI 不接受 raw `thresholds` 对象。
- 开户数 CSV 通过 textarea 进入既有 owner import API，并拆成 `dry_run=true`
  预览和确认正式写入。Universe 交易所使用 list 字段，不暴露 JSON 编辑器。
- 6 个 Classic 页面增加准确 deep link，并继续保留到 M5。

## 验证与风险

- 新增 Data Center TUI API / metadata 定向：`3 passed`。
- Universe、Provider connection、Market Thermometer、Governance console 与路由
  owner 回归：`42 passed`。
- inventory/static：`5 passed`。
- `ruff` 通过；7 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 完整 TUI Workbench 首轮为 `228 passed / 2 failed`；两处失败均为 metadata
  兼容口径（既有任务分组名、重复 patch 计数），修正后精确回归 `2 passed`；
  完整复跑 `230 passed`。
- migration inventory：196 templates / 117 route pages / A131 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- live-server 治理动作、Provider 连接、Publisher CRUD、Universe 更新、市场温度计
  配置/同步/重算/导入及失败态 UAT 尚未完成；Classic 删除仍受 M5 稳定发布、
  14 天兼容窗口和 telemetry 门槛约束。
