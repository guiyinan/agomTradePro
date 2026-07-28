# Web → TUI M4 Sentiment Dashboard Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-sentiment-dashboard-w48`；覆盖 Sentiment Dashboard 1 个 B 类
  route template，进入既有 `research.signals`。
- Sentiment owner 新增认证只读 TUI adapter，复用最近指数与健康 Application
  service，将 canonical `index`、`sources` 嵌套对象扁平为日期、综合/新闻/政策情绪、
  置信度、数据充分性和来源计数行；旧 API 契约保持不变。
- 新增 `sentiment.dashboard-summary` 与 `sentiment.index-trend`，分别承载最新指数
  P0 摘要和三序列 line；继续复用 M3 已发布的文本分析与健康检查 action。
- TUI 对 `days` 使用 1-365 的明确输入边界，错误时返回 400，不沿用旧兼容 API
  的静默回退。
- Classic 页面显示准确 `research.signals` deep link，并继续保留到 M5。

## 验证与风险

- Sentiment API 与 TUI 投影：`13 passed`；owner component 视图：`23 passed`；
  定向静态发布图：`1 passed`。
- 完整 TUI Workbench：`236 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 9 migrated / 8 backlog。
- `black`、`ruff`、Django system check 通过；3 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 最新指数空态、长序列、三序列 tooltip、键盘和三 viewport
  UAT；Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口占比、错误率
  和回滚演练门槛约束。
