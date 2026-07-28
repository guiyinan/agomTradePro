# Web → TUI M4 Dashboard Overview Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-dashboard-overview-w46`；覆盖投资指挥中心 1 个 B 类 route
  template，进入 `command-center.overview`。
- 新增 P0 投资指挥摘要，并把既有资产配置、组合表现两个自动 action 从泛型
  `status` 升级为 portable `pie` / `line` chart；复用原 action key，避免菜单出现
  同义重复任务。
- Dashboard owner 新增 typed overview adapter，调用既有 `build_dashboard_data`
  Application facade，一次返回摘要、资产配置和收益历史。资产配置在 HTTP 边界计算
  百分比，收益率做有界舍入；Terminal 不包含 Dashboard 业务逻辑。
- 摘要只保留环境、资产、收益、仓位、信号、待复盘和数据健康 P0 字段；Alpha、
  Pulse、决策流等任务继续复用先前已迁 action。
- Classic 页面显示准确 `command-center.overview` deep link，并继续保留到 M5。

## 验证与风险

- 定向 API/TUI：`2 passed`，覆盖配置占比、收益舍入和 auto action replacement。
- Dashboard API、收益曲线、页面结构与 inventory/static 联合回归：`33 passed`。
- 完整 TUI Workbench：`235 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  6 migrated / 11 backlog。
- `black`、`ruff` 通过；4 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 摘要空态、pie 文本摘要、长日期序列、键盘和三 viewport
  UAT；Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口占比、
  错误率和回滚演练门槛约束。

## M5 深链复核（2026-07-27）

矩阵驱动浏览器巡检发现三个 M4 runtime actions 已发布，但 immersive
`command-center.overview` 缺对应 dashboard panels，导致
`dashboard.overview-summary` Classic deep link 无法定位。现已同步补齐：

- IA 与 published graph 的 P0 投资指挥摘要、资产配置 pie、组合表现 line panels；
- compiler approved operation action 与 runtime injection 的 summary 主任务语义；
- immersive dashboard deep-link panel 定位和 JS 回归；
- compiler 对 runtime-only row actions 的静态发布裁剪。

修复后 metadata validator、IA `7 passed`、TUI JS `26 passed`、runtime sync 和
108/108 migrated route deep-link browser smoke 通过。主任务空态/长序列 UAT 仍按本报告
原范围保留为 M5 待办。
