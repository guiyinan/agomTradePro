# Web → TUI M3 Simulated Trading Records Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-simulated-trading-records-w37`；覆盖本人账户持仓、交易记录和巡检通知
  配置 3 个 A 类 route template。
- canonical screen：`execution.accounts`。发布持仓、交易记录、巡检通知读取和巡检通知
  更新 4 个动作。
- 持仓与交易记录复用既有 owner-scoped JSON API；表格按 metadata v3 的 8 列上限发布
  P0 字段，接口仍保留全部明细。交易记录保留日期、资产、方向和返回数量筛选。
- 新增独立 typed GET/PATCH 巡检通知 API。读取与更新均先校验账户 owner scope；
  `notify_on` 使用有限选项，额外收件人使用最多 20 项的 EmailField 列表，不暴露
  原始 JSON 对象；更新动作显式确认并要求审计。
- 三个 Classic 页面均增加准确 TUI deep link，并继续作为 M5 前兼容和回滚工件。
  持仓页的手工交易导入属于 Audit owner，不计入本 wave。

## 验证与风险

- Simulated Trading TUI metadata、API 与 information architecture：`8 passed`。
- Simulated Trading API edge 全文件：`10 passed`。
- 完整 TUI Workbench：`225 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；5 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server owner/foreign/空态、交易筛选与通知读写 UAT 尚未完成；M4 图表页面不在
  本 wave。Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
