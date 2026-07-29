# Web → TUI M3 合并证据（W21–W42，2026-07-26）

> **合并日期**: 2026-07-28
> **范围**: M3 已完成 wave 的实现、契约、验证与后续约束
> **来源**: 22 份原始 wave 证据无损合并；仅统一标题层级，原文件 SHA-256 见下表，完整历史保留在 Git

## 原始证据清单

| Wave | 原文件 | SHA-256 |
|---|---|---|
| W21 | `web-to-tui-m3-task-monitor-evidence-2026-07-26.md` | `21c8ad4febf12e7cda74e3901c1e5897fafe17951b7a0da4d0ace3ea1a4a07bf` |
| W22 | `web-to-tui-m3-sentiment-evidence-2026-07-26.md` | `b203bdcc096d2b0a97020bc163c4f4ffb96b8cee65677f2e3e0ae25fb8ed3c27` |
| W23 | `web-to-tui-m3-terminal-config-evidence-2026-07-26.md` | `7524972576442551956ccaff700ae30cdc2a91fe42798eacc52dd0aa78059667` |
| W24 | `web-to-tui-m3-asset-analysis-evidence-2026-07-26.md` | `34e861ac5bb7868ce18c11dadb12e426ee4e71ddac770a6302e5373c0f596d64` |
| W25 | `web-to-tui-m3-risk-center-evidence-2026-07-26.md` | `f523df28ac70668d03fc896390fcfc5507619b23aa4ee18f72bf53beace6cfa7` |
| W26 | `web-to-tui-m3-decision-workspace-evidence-2026-07-26.md` | `52ea62d29ab87cf585b47a4a407a0759ac609bf5fd8397361b227d7bfcb3f85c` |
| W27 | `web-to-tui-m3-alpha-ops-evidence-2026-07-26.md` | `56ba9e2f209005610293ad88bf217f864c77104367656d7b7a085c416acbc8f9` |
| W28 | `web-to-tui-m3-equity-config-evidence-2026-07-26.md` | `c33825c9bd70af0906ca40926b1656c6e038f2c5f88540d47f4998a765ed3e39` |
| W29 | `web-to-tui-m3-equity-screen-evidence-2026-07-26.md` | `eb0ede55e81368c5edb27d62e1b2cb9f20aedd5182e533aba43ccc4abafe27b4` |
| W30 | `web-to-tui-m3-dashboard-alpha-evidence-2026-07-26.md` | `4176fcbe82ad5e49c02b427219821a9a25b852657ba98fbffd7911c29a4cd11a` |
| W31 | `web-to-tui-m3-factor-calculate-evidence-2026-07-26.md` | `7113adf287b8bb251a861d6e3aba920bdbe20c354a35ca1be03738632fe07224` |
| W32 | `web-to-tui-m3-factor-definitions-evidence-2026-07-26.md` | `a9024a0c7673eb71d14cc5b922d2dc51cd265d3deaf9bd287d7a421b23fbd183` |
| W33 | `web-to-tui-m3-factor-portfolios-evidence-2026-07-26.md` | `30bff0d73766977fe6d2e4b3dc98c86769a39ab181308ac55231b7ffabe678ae` |
| W34 | `web-to-tui-m3-hedge-evidence-2026-07-26.md` | `b9bb4ac4f225079b52fba1a6bfd6f70c77b04dde17b49a1973a786072397ea9a` |
| W35 | `web-to-tui-m3-fund-evidence-2026-07-26.md` | `e7eaa2063a2e067751a353a1cca414df429276c3853be1adc3bdd090cee5b473` |
| W36 | `web-to-tui-m3-broker-execution-evidence-2026-07-26.md` | `d419b5f6b8f9b177789419d94592a1d4e0486bac4f7e06249515eb60cdbd85ea` |
| W37 | `web-to-tui-m3-simulated-trading-records-evidence-2026-07-26.md` | `34c84f05973884164ee9b34b33fcfbfc563ea73ab352423f08ea4778a37d7f86` |
| W38 | `web-to-tui-m3-agent-runtime-operator-evidence-2026-07-26.md` | `c6915d3bdc14071c4c43794c4f49bcc5b90c29400876f9fe7d2a8aa9c6ce796d` |
| W39 | `web-to-tui-m3-ops-hubs-evidence-2026-07-26.md` | `3fd8f79cfd0b33fcfa2537b382e2a41dd7d5b5559bc03ad8ecd0f409a49890ee` |
| W40 | `web-to-tui-m3-strategy-workbench-evidence-2026-07-26.md` | `a6a9d3410294e2cefa2c8e045271488b1b9bc74a151ddba5d26397b516ef543d` |
| W41 | `web-to-tui-m3-audit-review-evidence-2026-07-26.md` | `2d15c167879bd5fb5e9759c0f8e2beea1a16ab6f18d5cd0ecbbf491fbdaa6d18` |
| W42 | `web-to-tui-m3-data-center-governance-evidence-2026-07-26.md` | `d7311e6b1e99a157549e0f902c2fbc05239e2455f4c2d972171fc3f456a43b4e` |

## 合并正文

---

<!-- merged-from: web-to-tui-m3-task-monitor-evidence-2026-07-26.md; sha256: 21c8ad4febf12e7cda74e3901c1e5897fafe17951b7a0da4d0ace3ea1a4a07bf -->

## Web → TUI M3 Task Monitor Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-task-monitor-w21`；覆盖计划任务中心和验收监视器 2 个管理员
  route templates。
- `api-library.data-center` 新增 10 个管理员 action：任务健康概览、计划任务目录、
  执行记录/详情/统计、Celery 健康、readiness 状态、readiness 调度读取/更新和
  默认计划任务初始化。
- 新增管理员 owner API：
  `/api/system/scheduler/console/`、`/api/system/scheduler/bootstrap/`、
  `/api/system/readiness/monitor/` 和 `/api/system/readiness/schedule/`。
  接口复用 Task Monitor Application service，计划任务目录限制为 1–200 行，
  Interface 不直接访问 ORM。
- readiness 时间更新继续使用既有 Domain/Application 校验顺序；所有写动作要求
  staff 权限并在 TUI 中显式确认。任务列表的详情入口使用 IA 原生 row action。
- Classic 页面发布精确 TUI deep link，并在稳定期继续保留；原页面的刷新脚本没有
  被复制进 metadata。

### 验证与风险

- Task Monitor API 与 Classic 页面全文件：`20 passed`。
- Task Monitor metadata 与 IA 定向：`7 passed`。
- TUI Workbench 全文件：`212 passed`。首次全文件运行发现 5 个历史 IA 面板
  期望未同步，修正为当前 M2/M3 canonical IA 后全绿。
- ruff 通过；6 个变更生产文件增量 mypy 为 `0 regressions`、`0 legacy errors`。
- migration inventory 为
  `templates=195 route_pages=117 A=130 B=17 C=41 D=7`；TUI static contract
  `407 rule(s), 5 source(s)` 通过。
- 真实 live-server 计划目录→任务详情→严格 readiness→时间更新→默认任务初始化
  UAT 尚未执行；Classic 路由删除仍受 M5 稳定期、访问量和回滚门槛约束。

---

<!-- merged-from: web-to-tui-m3-sentiment-evidence-2026-07-26.md; sha256: b203bdcc096d2b0a97020bc163c4f4ffb96b8cee65677f2e3e0ae25fb8ed3c27 -->

## Web → TUI M3 Sentiment Analysis Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-sentiment-w22`；覆盖文本情绪分析 1 个认证 route template。
- `research.signals` 新增 `sentiment.analyze-text` 与 `sentiment.health` 两个 action。
  分析表单保留最多 5000 字文本和是否使用缓存选项，结果展示情绪评分、置信度、
  分类与关键词。
- 复用既有 `/api/sentiment/analyze/` 和 `/api/sentiment/health/` owner API，
  没有复制 Classic 页内 fetch、loading 和 DOM 拼装脚本。
- 分析可能写入缓存与分析日志，因此 TUI action 明确标为 execute/write 并要求确认；
  服务不可用继续以 503 明确返回，不伪装成中性情绪。
- Classic 页面保持 login-required，发布精确 TUI deep link，并在稳定期保留。

### 验证与风险

- Sentiment API、Classic page component、TUI metadata 与 IA 合计 `17 passed`。
- ruff 通过；新增 metadata 与 registry 增量 mypy 为 `0 regressions`。
- migration inventory 与 TUI static contract 在本 wave 收口命令中复核。
- 真实 live-server 文本输入→缓存开关→AI 结果/503 错误 UAT 尚未执行；Classic 路由
  删除仍受 M5 稳定期、访问量和回滚门槛约束。

---

<!-- merged-from: web-to-tui-m3-terminal-config-evidence-2026-07-26.md; sha256: 7524972576442551956ccaff700ae30cdc2a91fe42798eacc52dd0aa78059667 -->

## Web → TUI M3 Terminal Config Retirement Wave 证据（2026-07-26）

### 范围与结论

- Wave：`M3-terminal-config-w23`；覆盖旧终端命令配置 1 个 staff route template。
- 核对确认 Classic 表单调用的 `/api/terminal/commands/*` 已被 Terminal owner
  正式退役，所有操作稳定返回 410，并明确要求使用 MCP/Agents 驱动的 Terminal。
- 因此本 wave 不在 TUI 中复活终端命令 CRUD，也不把 410 API 包装成新 action。
  `/terminal/config/` 保持原 staff 权限后，精确 302 到
  `ai-ops.terminal + terminal.agent_chat`。
- 物理模板作为回滚工件保留到 M5；当前 resolver 不再渲染其中已经失效的命令表单。

### 验证与风险

- 6 个 legacy command API 410 契约与 1 个 staff redirect 契约：`7 passed`。
- ruff 通过；`apps/terminal/interface/views.py` 同步补齐类型标注，增量 mypy 为
  `0 regressions`、`0 legacy errors`。
- 非 staff 用户继续得到 403，不会借重定向绕过原管理员边界。
- 真实浏览器 staff 跳转→Agent chat UAT 尚未执行；物理模板删除仍受 M5 稳定期和
  回滚门槛约束。

---

<!-- merged-from: web-to-tui-m3-asset-analysis-evidence-2026-07-26.md; sha256: 34e861ac5bb7868ce18c11dadb12e426ee4e71ddac770a6302e5373c0f596d64 -->

## Web → TUI M3 Asset Analysis Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-asset-analysis-w24`；覆盖多维资产筛选 1 个认证 route template。
- `research.asset-lab` 新增 `asset-analysis.pool-screen`：资产类型通过 path 绑定，
  Regime、评分区间和风险等级通过 typed body fields 传递，结果用 datagrid 展示。
- 复用 `/api/asset-analysis/screen/<asset_type>/` owner API。后端当前只支持
  `equity` 和 `fund`，TUI 不发布 Classic 页中会稳定报错的 bond/wealth/commodity
  标签。
- API 默认筛选 investable/watch/candidate 资产池；返回仍保留完整 context、
  pool summary 和各评分维度。首屏列按用户优先级限制为 8 列，其余字段仍在响应中。
- Classic 手写 CSV 导出由 TUI 原生 datagrid export 替代；页面发布精确 deep link
  并在稳定期继续保留。

### 验证与风险

- Asset Analysis owner API：`6 passed`。
- TUI metadata 与 IA：`7 passed`；首次验证发现 datagrid 超过 8 列，按 schema
  门禁压缩为 8 个核心列后通过。
- ruff 通过；metadata 与 registry 增量 mypy 为 `0 regressions`。
- 真实 live-server equity/fund 筛选、空结果、错误和导出 UAT 尚未执行；Classic
  路由删除仍受 M5 稳定期、访问量和回滚门槛约束。

---

<!-- merged-from: web-to-tui-m3-risk-center-evidence-2026-07-26.md; sha256: f523df28ac70668d03fc896390fcfc5507619b23aa4ee18f72bf53beace6cfa7 -->

## Web → TUI M3 Risk Center Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-risk-center-w25`；覆盖集中风控中心 1 个 staff route template。
- 复核确认既有 Risk Center runtime bundle 的 12 个 action 已覆盖 Classic 页面：
  全局底线、风险模板、账户策略、有效策略、例外、交易前预览、投后检查、日报与历史，
  以及底线/账户策略/例外三类确认写入。
- actions 通过 canonical IA 归入 `macro-regime.strategy`；Classic 页面发布
  `risk-center.effective-policy` 精确 deep link。
- 页面原有 staff-only 边界保持不变。TUI 读任务仍由 owner API 按账户范围授权，
  全局配置写入继续由后端限制管理员并要求理由；没有复制 Classic 的手写 JSON
  渲染和导出脚本。

### 验证与风险

- Risk Center page、runtime action 与自动投顾 UI 契约：`7 passed`。
- 既有 owner API 集成契约继续作为矩阵 API 证据；本 wave 未修改 API 或 Domain。
- migration inventory 与 TUI static contract 在本 wave 收口命令中复核。
- 真实 live-server 账户选择→有效策略→交易前/投后检查→确认写入→日报导出 UAT
  尚未执行；Classic 路由删除仍受 M5 稳定期、访问量和回滚门槛约束。

---

<!-- merged-from: web-to-tui-m3-decision-workspace-evidence-2026-07-26.md; sha256: 52ea62d29ab87cf585b47a4a407a0759ac609bf5fd8397361b227d7bfcb3f85c -->

## Web → TUI M3 Decision Workspace Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-decision-workspace-w26`；覆盖每日决策工作台 1 个 route template。
- canonical screen：`command-center.decision-flow`。既有 owner JSON API 已覆盖工作台汇总、
  今日队列、推荐与冲突查询、推荐处置、调仓计划生成/更新/详情，以及执行审批的
  preview/approve/reject。
- 本 wave 补齐三个原 Classic 工作台仍依赖、但 published TUI 尚未提供的确认式任务：
  账户推荐刷新、系统证伪模板生成、AI 证伪草稿生成。字段使用普通表单、select、
  checkbox 和 textarea，不要求用户手写 raw JSON。
- Classic 页面发布准确的 TUI deep link，兼容期内继续保留。矩阵中的旧 URL 最终策略仍是
  `redirect_to_tui`，但只有满足 M5 的稳定版本、14 日、访问量、错误率和回滚演练门槛后
  才执行切换。

### HTML partial 边界

- `decision/steps/*.html` 由六个 HTMX 端点返回 HTML，不是 JSON API，不能作为 TUI action
  的完成证据。
- TUI 的主读取入口使用 `/api/decision/workspace/aggregated/` 等 owner JSON 契约。
- 六个 step partial 与一个无独立路由的 audit partial 已转入 M5 `remove_with_consumer`；
  在 Classic 工作台退出门槛满足前不删除。

### 验证与风险

- Decision owner/page 定向测试：`11 passed`，覆盖推荐刷新输入边界、系统/AI 证伪草稿、
  不可靠 Pulse 降级和 Classic 页面渲染。
- TUI metadata + IA：`7 passed`。
- 完整 `tests/unit/test_tui_workbench.py`：`214 passed`。
- `ruff` 通过；新增/修改 production metadata 文件 mypy：0 regressions、0 legacy errors。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7。
- TUI static source contract：407 rules / 5 sources。
- 真实 live-server 的“汇总→刷新推荐→采纳/忽略→生成计划→证伪草稿→审批”角色化 UAT、
  错误率与旧入口访问量观测尚未执行；这些是 M5 前的硬门槛。

---

<!-- merged-from: web-to-tui-m3-alpha-ops-evidence-2026-07-26.md; sha256: 56ba9e2f209005610293ad88bf217f864c77104367656d7b7a085c416acbc8f9 -->

## Web → TUI M3 Alpha Ops Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-alpha-ops-w27`；覆盖 Alpha 推理与 Qlib 数据运维 2 个 staff route templates。
- `research.signals` 已提供两个 staff 只读 overview，并补齐 superuser 的五种确认式异步任务：
  通用推理、单组合推理、全部启用组合批量推理、Universe 数据刷新、组合范围数据刷新。
- 字段与 owner serializers 对齐，包括日期、候选数量、Universe、组合、回看窗口和资产池口径；
  资产池选项复用 Alpha Application 真源，不在 Terminal 复制业务枚举。
- owner API 继续执行 staff/superuser 权限、输入校验、重复任务 409 和 Celery 异步投递。
  Classic 页面只增加准确 deep link，兼容期内保留。

### 验证与风险

- Alpha owner API + page contracts：`59 passed`。
- TUI metadata + IA：`8 passed`。
- `ruff` 通过；production metadata mypy：0 regressions、0 legacy errors。
- 两页共享 `_tabs.html` 不冒充独立任务，转 M5 `remove_with_consumer`。
- live-server 五种任务的 202/409、任务进度/失败回执和 Celery 实际执行 UAT 尚未完成；
  Classic 删除仍受 M5 量化退出门槛约束。

---

<!-- merged-from: web-to-tui-m3-equity-config-evidence-2026-07-26.md; sha256: c33825c9bd70af0906ca40926b1656c6e038f2c5f88540d47f4998a765ed3e39 -->

## Web → TUI M3 Equity Valuation Config Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-equity-config-w28`；覆盖估值修复配置 1 个复杂 route template。
- canonical screen：`research.asset-lab`。管理员可以查看版本列表和当前生效来源，并完成
  创建、更新、激活、回滚、删除未激活版本和清除运行时缓存。
- 创建/更新表单发布 owner serializer 支持的完整 21 个配置字段；默认值复用 Equity
  Domain 的 `DEFAULT_VALUATION_REPAIR_CONFIG`，不在 Terminal 创建第二套业务默认值。
- 所有 mutation 均标记为 admin risk、要求确认，实际 IsAdminUser、版本约束、权重与阈值
  校验、激活版本保护继续由 owner API 执行。
- Classic 页面增加当前配置的准确 deep link，兼容期内不删除。

### 验证与风险

- TUI metadata + IA：`7 passed`。
- Equity 配置 owner API：`7 passed`；canonical Equity/Fund route contract：`1 passed`。
- `ruff` 通过；production metadata mypy：0 regressions、0 legacy errors。
- live-server 创建→编辑→激活→回滚→删除保护→清缓存 UAT 尚未完成；错误率、旧入口访问量
  和回滚演练仍是 M5 硬门槛。

---

<!-- merged-from: web-to-tui-m3-equity-screen-evidence-2026-07-26.md; sha256: eb0ede55e81368c5edb27d62e1b2cb9f20aedd5182e533aba43ccc4abafe27b4 -->

## Web → TUI M3 Equity Screen Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-equity-screen-w29`；覆盖个股手动筛选 1 个复杂 route template。
- canonical screen：`research.asset-lab`；`equity.screen-stocks` 支持自动/指定 Regime、
  ROE、PE、PB、营收增长、利润增长、负债率和最多返回数量。
- TUI 不暴露 `custom_rule` raw JSON。Equity owner serializer 新增六个 write-only 扁平字段，
  在 Interface 边界合并为既有 `ScreenStocksRequest.custom_rule`，Domain/Application
  用例和筛选语义不变。
- 结果使用 8 列原生 datagrid，继续返回 owner API 的 `items`；执行动作显式确认。
- Classic 页增加准确 deep link。其系统 Alpha 推荐入口属于 Dashboard Alpha owner 的后续
  M3 wave，财务/估值同步属于数据修复支持任务，不被本 wave 虚报为已迁能力。

### 验证与风险

- serializer + TUI metadata + IA：`8 passed`。
- Classic 页面 + 实际 `/api/equity/screen/` 契约：`3 passed`。
- `ruff` 通过；Equity serializer 与 Terminal metadata mypy：0 regressions、0 legacy errors。
- live-server 条件筛选、空态、owner use-case 失败态、导出和长结果 UAT 尚未完成；Dashboard
  Alpha 自动推荐与数据同步需由对应后续 wave 提供完整 TUI 闭环。

---

<!-- merged-from: web-to-tui-m3-dashboard-alpha-evidence-2026-07-26.md; sha256: 4176fcbe82ad5e49c02b427219821a9a25b852657ba98fbffd7911c29a4cd11a -->

## Web → TUI M3 Dashboard Alpha Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-dashboard-alpha-w30`；覆盖 Alpha 完整排名与推荐历史 2 个 route templates。
- canonical screen：`research.signals`。完整排名使用 Dashboard owner 的
  `/api/dashboard/alpha/stocks/?format=json` 契约，支持 general/portfolio scope、组合、
  股票池口径和返回数量，保留原始 rank、新鲜度、阶段、来源与评分日。
- 推荐历史支持组合、交易日、证券、阶段、来源筛选，并以 run ID 查看当前用户范围内的
  快照详情。
- 没有把返回 HTML 的 Dashboard partial 当成 JSON 完成证据；排名 action 固定
  `format=json`。相关 partial 仍由 Dashboard 主页面消费，留待其消费者生命周期收口。
- 两个 Classic 页面均增加准确 TUI deep link，兼容期内保留。

### 验证与风险

- TUI metadata + IA：`7 passed`。
- Dashboard Alpha JSON、历史 list/detail 和两个 Classic 页面契约：`7 passed`。
- `ruff` 通过；production metadata mypy：0 regressions、0 legacy errors。
- live-server scope 切换、组合隔离、空历史、404 详情和大排名分页/性能 UAT 尚未完成；
  Classic 删除仍受 M5 量化退出门槛约束。

---

<!-- merged-from: web-to-tui-m3-factor-calculate-evidence-2026-07-26.md; sha256: 7113adf287b8bb251a861d6e3aba920bdbe20c354a35ca1be03738632fe07224 -->

## Web → TUI M3 Factor Calculate Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-factor-calculate-w31`；覆盖因子计算 1 个 route template。
- canonical screen：`research.asset-lab`。新增“按配置计算因子分数”和“解释个股因子分数”
  两个动作，分别接入 `/api/factor/calculate-config/` 与
  `/api/factor/explain-config/`。
- TUI 只接收 `config_id`、交易日、返回数量和证券代码等有界标量字段；旧页面允许直接
  编辑的 `factor_weights` 原始 JSON 未进入用户界面。
- 两个 owner API 在 Interface 层使用 DRF serializer 校验，再委托既有
  `calculate_scores_for_config` / `explain_stock_for_config` Application service；
  TUI 没有直接接触 ORM 或复制金融计算逻辑。
- Classic 页面增加准确的 TUI deep link，兼容期内保留；Factor 共享 layout 仍被
  manage 与 portfolios 两个页面消费，不在本 wave 提前转入 M5。

### 验证与风险

- 新增 TUI 与 Factor API 定向测试：`5 passed`。
- TUI information architecture：`6 passed`。
- Factor API edges 全量与上述 TUI/IA 组合运行显示 `27 passed`；测试进程完成后命令
  包装器超时，另以定向命令取得正常退出码。
- `ruff` 通过；production metadata / owner API mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 配置选择、计算成功/失败、个股解释、空结果和长结果 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-factor-definitions-evidence-2026-07-26.md; sha256: a9024a0c7673eb71d14cc5b922d2dc51cd265d3deaf9bd287d7a421b23fbd183 -->

## Web → TUI M3 Factor Definitions Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-factor-definitions-w32`；覆盖因子定义管理 1 个 route template。
- canonical screen：`research.asset-lab`。发布列表、详情、创建、局部更新、启停和删除
  6 个动作，复用 `/api/factor/definitions/**` owner API。
- 创建与更新表单完整覆盖代码、名称、类别、描述、数据来源、数据字段、方向、更新频率、
  启用状态、最小数据点和缺失值策略；列表保留类别、状态和关键字筛选。
- 类别与方向选项直接取 Factor Domain enum；owner serializer 同步改为 ChoiceField，并把
  `min_data_points` 下限收紧为 1，阻止 TUI 之外的 API 调用绕过相同领域边界。
- 写动作沿用既有认证用户权限，均显式确认；Classic 页面增加准确 TUI deep link，
  兼容期内保留。

### 验证与风险

- Factor definition CRUD、枚举/样本边界与 TUI metadata：`6 passed`。
- TUI information architecture：`6 passed`。
- `ruff` 通过；production serializer / metadata mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 列表筛选、创建、局部更新、启停、删除冲突和空态 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-factor-portfolios-evidence-2026-07-26.md; sha256: 30bff0d73766977fe6d2e4b3dc98c86769a39ab181308ac55231b7ffabe678ae -->

## Web → TUI M3 Factor Portfolios Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-factor-portfolios-w33`；覆盖因子组合配置 1 个 route template，并完成
  Factor 三个 route consumer 的 M3 收口。
- canonical screen：`research.asset-lab`。发布列表、详情、创建、局部更新、设置/移除
  单项因子权重、启用、停用、生成组合和删除 10 个动作。
- TUI 配置表单只发布名称、股票池、筛选条件、选股数量、调仓频率、持仓权重方式与风险
  上限等标量字段；`factor_weights` 原始 JSON 未进入创建或更新表单。
- 新增 owner `factor-weight` / `remove-factor-weight` API。Application 先验证新增权重引用的
  因子定义，Repository 再原子更新 JSON 存储中的单个键；移除动作允许清理定义已删除的
  陈旧键。
- 股票池、调仓频率和权重方式的选项抽为 Factor Application 唯一真源，页面 use case、
  serializer 和 TUI metadata 共用；serializer 同步补齐数值范围与 ChoiceField 边界。
- Classic 页面增加准确 TUI deep link；三个 route consumer 均已迁移，因此
  `factor/base.html` 转入 M5 随消费者清理，不冒充独立任务。

### 验证与风险

- 组合配置 CRUD、逐项权重、8 组非法输入、TUI metadata 与 IA：`17 passed`。
- 完整 TUI Workbench：`221 passed`。
- Django reverse 已确认三个关键 action 路径与 metadata 完全一致。
- `ruff` 通过；7 个 production owner / metadata 文件 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 配置草稿、逐项配权、绝对权重和校验、生成成功/失败、持仓长结果 UAT
  尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-hedge-evidence-2026-07-26.md; sha256: b9bb4ac4f225079b52fba1a6bfd6f70c77b04dde17b49a1973a786072397ea9a -->

## Web → TUI M3 Hedge Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-hedge-w34`；覆盖对冲对、组合快照和风险告警 3 个 route templates。
- canonical screen：`macro-regime.strategy`。发布 15 个动作：对冲对列表/详情/完整
  CRUD/启停/有效性检查，快照列表/最新/全量更新，以及告警列表/近期未解决/监控/解决。
- 普通认证用户仅能看到 7 个读或只读计算动作；管理员额外看到 8 个配置、状态和监控写
  动作。TUI 可见性与 owner `IsAdminUser` 权限双重保持，所有写入均显式确认。
- 对冲方法选项直接复用 `HedgeMethod` Domain enum；对冲对表单完整覆盖权重、调仓阈值、
  相关性窗口/范围、告警阈值、成本上限、目标 Beta 与启用状态。
- 三个 Classic 页面增加各自准确 deep link；全部 route consumer 已迁移，因此
  `hedge/base.html` 与其免责声明引用转入 M5 随消费者清理。

### 验证与风险

- Hedge owner API 与 TUI information architecture：`24 passed`。
- TUI 普通用户/管理员可见性与 15 动作完整性：`1 passed`。
- `ruff` 通过；2 个 production metadata 文件 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 对冲 CRUD、有效性计算、快照更新、监控生成与解决告警 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-fund-evidence-2026-07-26.md; sha256: e7eaa2063a2e067751a353a1cca414df429276c3853be1adc3bdd090cee5b473 -->

## Web → TUI M3 Fund Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-fund-w35`；覆盖基金研究 Dashboard 1 个 route template。
- canonical screen：`research.asset-lab`。发布多维筛选、排名、单基金评分、风格分析、
  区间业绩、基金资料、净值历史和持仓 8 个动作。
- 为 TUI 新增 `/api/fund/tui-multidim-screen/` typed owner 端点，只接收基金类型、投资
  风格、最小规模、Regime、政策档位、情绪指数和返回数量等扁平字段；Interface 组装
  owner Application service 所需上下文，不向用户暴露旧 `filters/context` 原始 JSON。
- 旧 Dashboard 的 `/api/fund/multidim-screen/` 嵌套契约保持不变，兼容页不受影响；
  新 serializer/view 独立成文件，避免把旧文件的历史类型债务带入增量基线。
- Regime 选项取 `RegimeType` Domain enum；计算型 POST 显式确认。Classic Dashboard
  增加准确 TUI deep link，兼容期内保留。

### 验证与风险

- Fund API、TUI metadata 与 information architecture：`21 passed`。
- 完整 TUI Workbench：`223 passed`。
- `ruff` 通过；5 个新增/修改 production 文件 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 多维筛选、排名、404/空态、长净值与持仓、业绩计算 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-broker-execution-evidence-2026-07-26.md; sha256: d419b5f6b8f9b177789419d94592a1d4e0486bac4f7e06249515eb60cdbd85ea -->

## Web → TUI M3 Broker Execution Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-broker-execution-w36`；覆盖 1 个共享 route template、7 个 Classic
  route pattern。
- canonical screen：`execution.accounts`，审计与对账动作仍按 metadata 归入
  `execution.audit`。共发布 33 个运行时动作，覆盖实盘就绪、订单列表/详情、连接状态、
  审批/拒绝/撤单、对账处置、操作审计、停止/恢复交易，以及管理员接入治理。
- 本 wave 补齐 15 个 Classic 管理员接入动作：投顾建议单下发、本地 Agent 绑定、
  账户授权、凭证轮换/撤销、连接同步和执行设置。除只读授权列表外，均采用
  preview/commit 双动作；commit 保留显式确认与审计要求。
- TUI 只发布有界标量或列表字段，不向用户暴露原始 JSON 对象。凭证密文结果使用
  `copyable_secret` 专用语义；普通用户看不到管理员接入动作，最终授权继续由
  Broker Execution owner Application/API 判定。
- Classic 共享工作台增加准确 TUI deep link，并继续作为 M5 前兼容和回滚工件。
  Classic 中的手工交易 CSV 属于 Audit owner，不计入本 wave 的迁移完成范围。

### 验证与风险

- Broker Execution TUI metadata 与 information architecture：`9 passed`。
- Broker Execution 全组件回归：`63 passed`。
- 完整 TUI Workbench：`224 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；runtime metadata 增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server preview→commit、一次性凭证展示、跨用户隔离、Agent/QMT 连接和失败恢复
  UAT 尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-simulated-trading-records-evidence-2026-07-26.md; sha256: 34c84f05973884164ee9b34b33fcfbfc563ea73ab352423f08ea4778a37d7f86 -->

## Web → TUI M3 Simulated Trading Records Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

- Simulated Trading TUI metadata、API 与 information architecture：`8 passed`。
- Simulated Trading API edge 全文件：`10 passed`。
- 完整 TUI Workbench：`225 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；5 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server owner/foreign/空态、交易筛选与通知读写 UAT 尚未完成；M4 图表页面不在
  本 wave。Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-agent-runtime-operator-evidence-2026-07-26.md; sha256: c6915d3bdc14071c4c43794c4f49bcc5b90c29400876f9fe7d2a8aa9c6ce796d -->

## Web → TUI M3 Agent Runtime Operator Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-agent-runtime-operator-w38`；覆盖任务列表/详情与提案列表/详情 4 个
  operator route template。
- canonical screen：`ai-ops.terminal`（兼容 alias：`ai-ops.agent-runtime`）。新增 9 个
  curated 动作：治理总览、任务列表/详情、提案列表/详情，以及提交、批准、拒绝、
  执行四个 proposal 状态机动作。
- 新增独立 typed operator API，保留 Classic 任务队列的状态/任务域/search/attention
  筛选和提案队列的状态/审批/风险/search 筛选；proposal detail 返回 guardrail、
  execution 与 task timeline 证据。任务详情复用既有 Operator Dashboard owner API。
- TUI 的 operator 动作使用 group-aware 可见性 predicate：普通认证用户不看到动作，
  staff/superuser 和 `operator` 组可见；API 仍以 `IsStaffOrOperator` 等价权限作为
  最终授权。四个 mutation 均显式确认并要求审计，状态机与 guardrail 仍由 owner
  Application use case 判定。
- 四个 Classic 页面增加准确 deep link；两个共享 partial 不冒充独立任务，转入 M5
  随消费者一起清理。

### 验证与风险

- Agent Runtime operator TUI/API/IA 定向：`8 passed`。
- Operator Dashboard 与 route compatibility：`37 passed`。
- 完整 TUI Workbench：`226 passed`；inventory/static 单元测试：`5 passed`。
- migration inventory：195 templates / 117 route pages / A130 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `black`、`ruff` 通过；6 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 提交→批准/拒绝→执行、guardrail blocked、执行失败和空队列 UAT 尚未
  完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-ops-hubs-evidence-2026-07-26.md; sha256: 3fd8f79cfd0b33fcfa2537b382e2a41dd7d5b5559bc03ad8ecd0f409a49890ee -->

## Web → TUI M3 Ops Hubs Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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

---

<!-- merged-from: web-to-tui-m3-strategy-workbench-evidence-2026-07-26.md; sha256: a6a9d3410294e2cefa2c8e045271488b1b9bc74a151ddba5d26397b516ef543d -->

## Web → TUI M3 Strategy Workbench Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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

---

<!-- merged-from: web-to-tui-m3-audit-review-evidence-2026-07-26.md; sha256: 2d15c167879bd5fb5e9759c0f8e2beea1a16ab6f18d5cd0ecbbf491fbdaa6d18 -->

## Web → TUI M3 Audit Review Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M3-audit-review-w41`；覆盖审计复盘首页、归因报告列表、本人/管理员
  操作日志、本人/管理员决策链共 6 个 route template，统一进入
  `execution.audit`。
- 新增 10 个 curated action：复盘概览、归因报告列表、报告生成预览与确认生成、
  owner/admin 操作日志列表与详情、管理员统计与 JSON 证据导出、owner/admin
  决策链列表与详情。
- 新增两个认证只读 adapter。概览只返回最新验证、最近 5 份报告和最多 5 个待复盘
  回测；报告列表按 `heuristic` / `brinson` 筛选并限制为 50 条，同时标记已生成和
  待生成回测。适配层只调用 Audit Application service，不直接访问 ORM。
- 报告生成继续复用既有 preview 与正式生成 API；TUI 正式动作要求确认和审计，
  未复制归因业务逻辑。
- 操作日志和决策链继续复用 owner API 的最终授权：普通用户仅能读取本人证据，
  审计管理员可读取全量。统计与 JSON 导出 action 只对管理员发布；CSV 由 TUI
  datagrid 的本地导出能力覆盖。
- 6 个 Classic 页面均可得到准确 deep link；`decision_traces_admin.html` 继承
  `my_decision_traces.html` 的迁移提示。所有 Classic 页面继续保留到 M5。

### 验证与风险

- Audit API edge：`9 passed`，其中新增报告筛选、候选标记与非法方法拒绝契约。
- Audit TUI 元数据定向：`1 passed`，验证普通用户/管理员 action 可见性、确认生成
  与 datagrid 语义。
- Audit Classic 页面与权限回归：`59 passed`。
- 完整 TUI Workbench：`230 passed`；inventory/static：`5 passed`。
- migration inventory：196 templates / 117 route pages / A131 / B17 / C41 / D7；
  TUI static：407 rules / 5 sources。
- `ruff` 通过；5 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 概览空态、报告 preview→generate、owner/admin 隔离、日志详情与
  JSON 导出失败态 UAT 尚未完成；Classic 删除仍受 M5 稳定发布、14 天兼容窗口和
  telemetry 门槛约束。

---

<!-- merged-from: web-to-tui-m3-data-center-governance-evidence-2026-07-26.md; sha256: d7311e6b1e99a157549e0f902c2fbc05239e2455f4c2d972171fc3f456a43b4e -->

## Web → TUI M3 Data Center Governance Wave 证据（2026-07-26）

### 范围与闭环

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

### 验证与风险

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
