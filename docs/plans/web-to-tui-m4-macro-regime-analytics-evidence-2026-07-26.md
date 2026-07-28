# Web → TUI M4 Macro / Regime Analytics Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-macro-regime-analytics-w47`；覆盖 Macro 数据中心与 Regime 判定
  2 个 B 类 route template，统一进入 `macro-regime.overview`。
- Macro owner 新增认证只读 TUI adapter，复用
  `get_macro_data_page_snapshot`，输出指标覆盖摘要、选中指标标准化序列，以及扁平化的
  市场温度 / Pulse 风险时序；Terminal 不承载宏观业务拼装。
- Regime owner 新增认证只读 TUI adapter，复用
  `get_regime_dashboard_payload` 与 `GetRegimeNavigatorHistoryUseCase`，输出指定时点
  象限摘要、概率分布、增长 / 通胀动量，以及 Regime / Pulse / 风险预算 / 资产权重
  的联合历史行。
- 发布 7 个 runtime action：Macro 摘要、指标 line、风险 line；Regime 当前详情、
  概率 pie、动量 line、导航历史 line。`regime.current` 与
  `regime.navigator_history` 复用既有 action key，消除同义任务。
- `/api/macro/tui/overview/` 不恢复已退役的 Macro CRUD；旧
  `/api/macro/data/` 等契约继续保持 404。两个 Classic 页面仅增加准确 deep link，
  继续保留到 M5。

## 验证与风险

- Owner TUI API：`7 passed`，覆盖指标选择、风险时序、象限分布、动量、联合历史，
  以及日期、月份和标识长度边界。
- Macro / Regime owner、API root 与旧路由联合回归：`77 passed`。
- 定向 TUI 发布图：`1 passed`；完整 TUI Workbench：`236 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 8 migrated / 9 backlog。
- `black`、`ruff`、Django system check 通过；7 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 指标切换、空数据、概率 pie、长历史、键盘和三 viewport
  UAT；Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口占比、错误率
  和回滚演练门槛约束。
