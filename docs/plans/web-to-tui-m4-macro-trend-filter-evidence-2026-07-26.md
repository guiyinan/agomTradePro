# Web → TUI M4 Macro Trend Filter Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-macro-trend-filter-w49`；覆盖 Filter Dashboard 1 个 B 类 route
  template，替代任务进入 `research.asset-lab`。
- `apps.filter` 已进入弃用期，本 wave 不新增 Filter API、SDK、MCP 或 TUI
  消费者。Macro owner 新增认证只读 TUI adapter，通过 Data Center Application
  查询 canonical macro facts，并在 Macro composition root 注入共享趋势算法。
- Application service 只使用展示值计算 portable rows，不持久化结果：HP 固定使用
  扩张窗口，Kalman 固定使用单向局部线性趋势；输出报告期、原始值、长期趋势、周期
  分量和斜率，同时保留来源、新鲜度、decision grade、禁用决策标志和阻断原因。
- 新增 `macro.trend-filter-summary`、`macro.trend-filter-chart` 和
  `macro.trend-filter-components` 三个只读 action。指标代码、算法和历史点数均为有界
  scalar field，不暴露原始 JSON。
- 替代任务发布后，runtime load 裁掉原 `research.signals` 下五个 Filter 自动 action；
  generated/published 源图仍保留到后续治理批次，不把运行时迁移误作物理下线授权。
- Classic 页面显示准确 `research.asset-lab` deep link，并继续保留到 M5；旧 Filter
  API/SDK/MCP 兼容与 2026-09-30 sunset 规则不变。

## 验证与风险

- Macro trend Application/PIT 算法：`7 passed`；Macro/Regime TUI API：
  `14 passed`；旧 Filter API/Application/Domain 兼容基线：`37 passed`；定向 TUI
  replacement/pruning：`1 passed`。
- 完整 TUI Workbench：`237 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 10 migrated / 7 backlog。
- `black`、`ruff`、Django system check 和全仓 architecture verify（1911 files /
  0 boundary / 0 audit violations）通过；7 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server HP/Kalman 切换、空态、decision-grade 告警、长序列 tooltip、
  键盘和三 viewport UAT；Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、
  旧入口占比、错误率和回滚演练门槛约束。
