# Web → TUI M4 合并证据（W43–W51，2026-07-26）

> **合并日期**: 2026-07-28
> **范围**: M4 已完成 wave 的实现、契约、验证与后续约束
> **来源**: 9 份原始 wave 证据无损合并；仅统一标题层级，原文件 SHA-256 见下表，完整历史保留在 Git

## 原始证据清单

| Wave | 原文件 | SHA-256 |
|---|---|---|
| W43 | `web-to-tui-m4-audit-analytics-evidence-2026-07-26.md` | `71ddf86ba42db1dc61e585581981c86d58fdac7255ab80e496b192430e1dee60` |
| W44 | `web-to-tui-m4-audit-manual-trade-evidence-2026-07-26.md` | `e6d86c1634d66706a622338ebcf08db1f0f30091ee212f76031ed75ca7869f60` |
| W45 | `web-to-tui-m4-account-overview-evidence-2026-07-26.md` | `409f8b5e1907d4f46cf4e86805cd0bdbebeec5cf080d2c9a8f1241695b573b0c` |
| W46 | `web-to-tui-m4-dashboard-overview-evidence-2026-07-26.md` | `5517e0387f9aa2577a2b63f8af75b8dbfa0c82b9d72c797a4685ad86e9f7513a` |
| W47 | `web-to-tui-m4-macro-regime-analytics-evidence-2026-07-26.md` | `8e410f86148f86b5ed63aef793dd76b9dc725845782df32d38200e360ee842ad` |
| W48 | `web-to-tui-m4-sentiment-dashboard-evidence-2026-07-26.md` | `fc7dd6ae19a807c3d26934d94fae748ea3401f1e09277433bd9d1b7a8d0016b2` |
| W49 | `web-to-tui-m4-macro-trend-filter-evidence-2026-07-26.md` | `0b1b0bb84ccb46186de3ba69856e0da37400f08d0f2f688632b79c43f37219b7` |
| W50 | `web-to-tui-m4-equity-analytics-evidence-2026-07-26.md` | `dc378aabac6bcfa498dfd88d50bdeca9bcea5ee811297ee3597007838e0a7df1` |
| W51 | `web-to-tui-m4-simulated-accounts-evidence-2026-07-26.md` | `8ecd18505eb7bfb9ae27cb69f26cf3fae457298fd5fd3727869fe6c2195dc2cb` |

## 合并正文

---

<!-- merged-from: web-to-tui-m4-audit-analytics-evidence-2026-07-26.md; sha256: 71ddf86ba42db1dc61e585581981c86d58fdac7255ab80e496b192430e1dee60 -->

## Web → TUI M4 Audit Analytics Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M4-audit-analytics-w43`；覆盖归因明细、指标绩效和阈值验证 3 个
  B 类 route template，统一进入 `execution.audit`。
- 新增 12 个 curated action：归因明细与贡献柱状图、指标绩效列表/柱状图/详情、
  阈值列表/历史折线图、阈值更新 preview/commit、验证运行 preview/commit 和
  验证详情。
- 新增 3 个认证只读 TUI adapter。适配层只调用 Audit Application service，
  不直接访问 ORM；归因收益统一投影为百分比，指标 F1/稳定性统一投影为百分比，
  阈值历史统一展开为带观测标签、旧值、新值和差异值的图表行。
- schema v3、metadata validator 与结果投影显式支持 `line`、`bar`、`pie`
  `chart_type`。未声明时继续默认 `line`，保持既有 action 兼容；本 wave 使用
  `bar` 表达归因贡献和指标对比，使用 `line` 表达阈值历史。
- 阈值更新和验证运行只对管理员发布，正式动作要求确认和审计，并继续由 owner
  API 执行最终授权；普通用户只能读取已授权的分析结果。
- 3 个 Classic 页面均显示迁移提示并提供 `execution.audit` deep link；页面继续
  保留到 M5，不在兼容观察期内提前删除。

### 验证与风险

- 定向 Audit API/TUI/static：`16 passed`，覆盖百分比投影、阈值历史展开、
  `bar` 图表投影和管理员 mutation 可见性。
- Audit 阈值/验证接口回归：`11 passed`。
- Audit 归因工作流、API 与 Classic 页面回归：`39 passed`。
- 完整 TUI Workbench：`231 passed`；inventory/static：`5 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  3 migrated / 14 backlog。
- `ruff` 通过；6 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 图表空态、tooltip/键盘、三 viewport、阈值
  preview→commit 和 owner/admin 隔离 UAT；Classic 删除仍受 M5 稳定发布、
  不少于 14 个自然日、旧入口占比、错误率和回滚演练门槛约束。

---

<!-- merged-from: web-to-tui-m4-audit-manual-trade-evidence-2026-07-26.md; sha256: e6d86c1634d66706a622338ebcf08db1f0f30091ee212f76031ed75ca7869f60 -->

## Web → TUI M4 Audit Manual Trade Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M4-audit-manual-trade-w44`；覆盖手动交易复盘 1 个 B 类 route
  template，进入 `execution.audit`。
- 新增 6 个 curated action：导入批次、最近成交、CSV 预览、CSV 确认导入、
  推荐执行关联和四分支决策复盘。
- Audit 新增 owner-scoped 汇总 adapter；Account 新增 UTF-8 CSV TUI
  preview/commit adapter；Backtest 新增四分支比较用例和 typed API。业务逻辑留在
  owner Application 层，Terminal 只发布 metadata 和通用结果投影。
- TUI 文件字段按 runtime 真实能力读取文本，限制为 UTF-8 CSV、2 MiB；Classic
  继续承载 XLS/XLSX 和更大文件，不把二进制格式伪装成已迁能力。
- 四分支复盘一次运行 `actual`、`no_action`、`system_plan`、`delayed_1d`，
  返回日期对齐净值曲线与分支指标。新增产品无关的 `table_chart` 投影契约，
  同一动作同时呈现图表和表格，避免为看完整结果重复创建回测。
- CSV 正式导入和四分支复盘均要求确认并记录审计；Account/Backtest owner API
  继续执行组合归属和认证边界。
- Classic 页面显示准确 `execution.audit` deep link，并继续保留到 M5。

### 验证与风险

- 核心定向：`5 passed`，覆盖 owner CSV、越权拒绝、四分支合并、TUI 发布和
  `table_chart` 投影。
- Manual Trade、Audit API edge 与 inventory/static 联合回归：`27 passed`。
- 完整 TUI Workbench：`233 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  4 migrated / 13 backlog。
- `black`、`ruff` 通过；14 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server CSV preview→commit、导入后刷新、四分支图表空态/部分失败、
  键盘与三 viewport UAT；XLS/XLSX 仍仅由 Classic 承载。Classic 删除继续受
  M5 稳定版本、不少于 14 个自然日、旧入口占比、错误率和回滚演练门槛约束。

---

<!-- merged-from: web-to-tui-m4-account-overview-evidence-2026-07-26.md; sha256: 409f8b5e1907d4f46cf4e86805cd0bdbebeec5cf080d2c9a8f1241695b573b0c -->

## Web → TUI M4 Account Overview Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M4-account-overview-w45`；覆盖账户资料与组合波动率 1 个 B 类 route
  template，进入 `execution.accounts`。
- 新增 3 个 curated read action：账户资料、波动率摘要和波动率趋势；账户、持仓、
  交易与通知继续复用 W37 已发布的 owner-scoped action，不重复发布。
- Account owner 新增 typed TUI 波动率 adapter，直接调用
  `VolatilityAnalysisUseCase`。30/60/90 日、目标值、目标上下限和建议仓位统一投影为
  百分比，历史按日期排序交给 portable line chart。
- 无活跃组合时返回成功的明确空态和空历史，不把正常初始化状态当作 404；浮点百分比
  在 HTTP 边界做有界舍入，避免用户可见二进制浮点噪声。
- Classic 页面显示准确 `execution.accounts` deep link，并继续保留到 M5。

### 验证与风险

- 定向 API/TUI：`3 passed`，覆盖百分比、空态和元数据列契约。
- Account API edge 与 inventory/static 联合回归：`66 passed`。
- 完整 TUI Workbench：`234 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  5 migrated / 12 backlog。
- `black`、`ruff` 通过；4 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 空态、降仓告警、日期密度、键盘和三 viewport UAT；
  Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口占比、错误率和
  回滚演练门槛约束。

---

<!-- merged-from: web-to-tui-m4-dashboard-overview-evidence-2026-07-26.md; sha256: 5517e0387f9aa2577a2b63f8af75b8dbfa0c82b9d72c797a4685ad86e9f7513a -->

## Web → TUI M4 Dashboard Overview Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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

### M5 深链复核（2026-07-27）

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

---

<!-- merged-from: web-to-tui-m4-macro-regime-analytics-evidence-2026-07-26.md; sha256: 8e410f86148f86b5ed63aef793dd76b9dc725845782df32d38200e360ee842ad -->

## Web → TUI M4 Macro / Regime Analytics Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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

---

<!-- merged-from: web-to-tui-m4-sentiment-dashboard-evidence-2026-07-26.md; sha256: fc7dd6ae19a807c3d26934d94fae748ea3401f1e09277433bd9d1b7a8d0016b2 -->

## Web → TUI M4 Sentiment Dashboard Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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

---

<!-- merged-from: web-to-tui-m4-macro-trend-filter-evidence-2026-07-26.md; sha256: 0b1b0bb84ccb46186de3ba69856e0da37400f08d0f2f688632b79c43f37219b7 -->

## Web → TUI M4 Macro Trend Filter Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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

---

<!-- merged-from: web-to-tui-m4-equity-analytics-evidence-2026-07-26.md; sha256: dc378aabac6bcfa498dfd88d50bdeca9bcea5ee811297ee3597007838e0a7df1 -->

## Web → TUI M4 Equity Analytics Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

- Equity pool、估值修复与配置集成回归：`45 passed`；定向 TUI metadata：
  `1 passed`；完整 TUI Workbench：`238 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 13 migrated / 4 backlog。
- `black`、`ruff`、Django system check 和全仓 architecture verify 通过；4 个
  production 文件增量 mypy：`0 regressions`、`0 legacy errors`。
- 未完成 live-server 技术/日内/Regime 图表、股票池刷新与 pie、修复扫描与历史
  line、空态、键盘和三 viewport UAT；Classic 删除继续受 M5 稳定版本、不少于
  14 个自然日、旧入口占比、错误率和回滚演练门槛约束。

---

<!-- merged-from: web-to-tui-m4-simulated-accounts-evidence-2026-07-26.md; sha256: 8ecd18505eb7bfb9ae27cb69f26cf3fae457298fd5fd3727869fe6c2195dc2cb -->

## Web → TUI M4 Simulated Accounts Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M4-simulated-accounts-w51`；覆盖模拟交易 dashboard、旧 account detail、
  我的账户和我的账户详情 4 个 B 类 route template，完成最后一批 B 类实现。
- 四个页面均引入 Chart.js，但仓内没有 `<canvas>`、`new Chart` 或图表实例，M0 的
  B 分类属于依赖标记的保守静态命中。迁移没有虚报旧图表复刻；在
  `execution.accounts` 复用 owner equity-curve API 发布真实 portable line。
- 新增账户列表、详情、创建、删除、批量删除、绩效、净值曲线、策略选项、绑定和
  解绑 10 个 action，并复用 W37 的持仓、交易和巡检通知 4 个 action。所有账户
  owner scope 和策略 owner scope 继续由最终 API 授权，mutation 显式确认并审计。
- 正式 IA 真源新增 `simulated-accounts` P0 面板，提供账户详情和删除 row action；
  runtime screen patch 同步保留非 IA payload 的兼容投影。Classic dashboard 的
  硬编码定时状态没有提升为运行时事实。
- 分享链接继续使用 `execution.share`，手动成交流水继续使用 `execution.audit`，
  实时行情继续由 Data Center 承载；不在模拟交易屏复制同义任务。
- 四个 Classic 页面均显示准确 action deep link，并继续保留到 M5；页面 hash、
  兼容消费者和回归证据已回写迁移矩阵。

### 验证与风险

- Simulated Trading 账户 API、创建/删除/隔离集成与 Strategy owner API：
  `56 passed`；定向 TUI metadata + 全量 IA/幂等：`7 passed`；AGENTS.md 固定
  其余三组最小回归：`35 passed`；完整 TUI Workbench：`239 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 17 migrated / 0 backlog。
- `black`、`ruff`、Django system check 和全仓 architecture verify（1912 files /
  0 boundary violations）通过；3 个
  production 文件增量 mypy：`0 regressions`、`0 legacy errors`。
- 未完成 live-server 账户 CRUD/批量删除、策略绑定/解绑、净值曲线、空态、键盘和
  三 viewport UAT；Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口
  占比、错误率和回滚演练门槛约束。
