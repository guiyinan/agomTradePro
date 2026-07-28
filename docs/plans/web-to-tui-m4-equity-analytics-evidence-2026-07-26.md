# Web → TUI M4 Equity Analytics Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-equity-analytics-w50`；覆盖 Equity 个股详情、股票池和估值修复
  3 个 B 类 route template，用户任务统一进入 `research.asset-lab`。
- 个股详情复用既有 owner API，发布估值概览、技术价格、技术动量、日内价格和
  Regime 表现 5 个只读 action。价格/动量/日内使用 portable line，Regime 表现
  使用 bar；不把 Data Center 行情、资金流、新闻或 Pulse 任务复制到 Equity。
- 股票池复用既有列表和刷新 API，补充向后兼容的 `sector_distribution` 展示投影，
  发布摘要、8 列股票列表、板块 pie 和显式确认刷新 4 个 action。
- 估值修复复用既有列表、详情、历史和扫描 API；历史保留原始 0–1 `points`，
  新增 0–100 的 `chart_points` 展示投影，发布列表、详情、百分位 line 和显式确认
  扫描 4 个 action。两个新字段都只在 owner Interface 序列化边界生成，不新增平行
  API 或业务持久化。
- 三个 Classic 页面均显示准确的 action deep link，并继续保留到 M5；页面内容
  hash、兼容消费者和回归证据已回写迁移矩阵。

## 验证与风险

- Equity pool、估值修复与配置集成回归：`45 passed`；定向 TUI metadata：
  `1 passed`；完整 TUI Workbench：`238 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 13 migrated / 4 backlog。
- `black`、`ruff`、Django system check 和全仓 architecture verify 通过；4 个
  production 文件增量 mypy：`0 regressions`、`0 legacy errors`。
- 未完成 live-server 技术/日内/Regime 图表、股票池刷新与 pie、修复扫描与历史
  line、空态、键盘和三 viewport UAT；Classic 删除继续受 M5 稳定版本、不少于
  14 个自然日、旧入口占比、错误率和回滚演练门槛约束。
