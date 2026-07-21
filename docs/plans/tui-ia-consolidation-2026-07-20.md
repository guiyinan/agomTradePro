# TUI 信息架构重构计划：任务屏收敛与权限分层

> **日期**: 2026-07-20  
> **修订日期**: 2026-07-21  
> **状态**: AgomTradePro 重构与本地发布完成；AgomTUI schema 同步转配套整改
> **范围决策**: 重构信息架构；保留终端仿真 chrome、F 键、三栏布局和 CLI 风格；每日决策流优先；普通用户自助与管理员治理严格分层  
> **目标口径**: 37 个 published 屏与 11 个 runtime 注入屏，收敛为普通用户 13 个任务屏；管理员在此基础上增加 3 个治理屏，共 16 个最终可导航屏
> **配套整改**: [AgomTUI 可移植性整改方案](agomtui-portability-remediation-2026-07-21.md)，负责跨仓库 Runtime 同步、schema 兼容、宿主接入与双端发布门禁

## 一、现状诊断

有代码证据的痛点：

1. **36/37 个 published 屏本质上仍是 API 表单目录**：action 由 API 注册表编译生成，与后端接口近似一一对应。除首页 `command-center.overview` 外，没有 published 屏拥有 `dashboard_panels`；用户打开一屏先看到的是左侧任务栏中的表单集合。
2. **信息架构按模块/API 分，不按用户任务分**：例如 `macro-regime.strategy` 同屏并列“策略、策略清单、我的策略、策略规则、策略脚本配置、策略 AI 配置、策略绑定”等近义入口；`research.signals` 同时出现“信号统计、信号、待处理统一信号、统一信号摘要”。
3. **published 导航平铺 37 项，runtime 还会继续注入屏**：只统计 published 图会低估用户最终看到的目录规模；必须同时治理 `RUNTIME_METADATA_INJECTIONS`。
4. **P0 业务信息不能稳定首屏呈现**：除首页外，当前 Regime、候选、持仓、风控状态等信息通常需要手动运行 action；详情类 action 还要求手填记录 ID。
5. **每日投研流程过细**：环境判断、执行检查和复盘被拆成多个技术模块屏，用户需要频繁切换。
6. **权限拓扑不清晰**：个人 AI 服务商属于 authenticated 自助任务，系统服务商、用户配额、MCP 治理属于 admin 任务，不能简单合并到同一个 audience 屏。

根因：当前模型仍接近“屏 = API 集合”，而不是“屏 = 用户任务”。`docs/development/tui-user-facing-design-standard.md` 已明确要求每屏发布 `primary_task`、`primary_outcome`、P0 信息层级和可执行默认动作，本次重构将这些要求落实为可验证的 metadata 契约。

## 二、目标信息架构

### 2.1 最终目录口径

最终目录按角色计数：

| 用户角色 | 每日决策 | 研究与工具 | 系统治理 | 合计 |
|---|---:|---:|---:|---:|
| 普通 authenticated 用户 | 8 | 5 | 0 | 13 |
| admin 用户 | 8 | 5 | 3 | 16 |

三个一级组固定为：

- `daily`：每日决策
- `research`：研究与工具
- `system`：系统治理，仅 admin 可见

### 2.2 37 个 published 屏全量映射

#### A. 每日决策（8 屏）

| # | 最终屏 key | 标签 | 合并来源 published 屏 |
|---:|---|---|---|
| 1 | `command-center.overview` | 今日总览 | `command-center.overview`、`command-center.dashboard` |
| 2 | `macro-regime.overview` | 环境与脉搏 | `macro-regime.overview`、`macro-regime.navigator`、`macro-regime.pulse`、`api-library.market-thermometer` |
| 3 | `policy.workbench` | 政策与热点 | `policy.workbench` |
| 4 | `command-center.decision-flow` | 每日决策流 | `command-center.decision-flow` |
| 5 | `research.signals` | 信号与候选 | `research.signals`、`research.alpha`、`research.alpha-triggers`、`research.screening-sentiment` |
| 6 | `execution.accounts` | 账户与持仓 | `execution.accounts`、`execution.trading-ledger`、`execution.portfolio-performance`、`execution.account-settings` |
| 7 | `macro-regime.strategy` | 策略与风控 | `macro-regime.strategy`、`macro-regime.rotation`、`macro-regime.risk-controls`、`macro-regime.beta-gate`、`macro-regime.hedge` |
| 8 | `execution.audit` | 事件与复盘 | `execution.audit`、`execution.events`、`execution.share` |

#### B. 研究与工具（3 个 published 目标屏）

| 最终屏 key | 标签 | 合并来源 published 屏 | audience |
|---|---|---|---|
| `research.asset-lab` | 资产研究 | `research.asset-lab`、`research.factors`、`research.backtests`、`research.fund-sector` | authenticated |
| `ai-ops.terminal` | AI 助手 | `ai-ops.terminal`、`ai-ops.agent-runtime` | authenticated |
| `ai-ops.providers` | AI 工具与我的服务商 | `ai-ops.providers`、`ai-ops.capabilities`、`ai-ops.prompt-workbench` | authenticated |

另有 2 个 runtime 工具屏保留，见 2.3：`capability-router.self-service`、`cli.terminal`。

#### C. 系统治理（1 个 published 目标屏）

| 最终屏 key | 标签 | 合并来源 published 屏 | audience |
|---|---|---|---|
| `api-library.data-center` | 数据与系统健康 | `api-library.data-center`、`execution.tasks`、`api-library.runtime`、`api-library.config-center` | admin |

另有 2 个 runtime 管理屏保留为治理目标，见 2.3：`ai-ops.system-providers`、`capability-router.mcp-center`。

以上映射覆盖当前 37 个 published 屏，最终保留 12 个 published 目标屏；其余屏在 action 重路由后由 `_prune_empty_screens` 退出 published 导航。

### 2.3 11 个 runtime 注入屏全量映射

| 当前 runtime 屏 | 最终屏 | 处理方式 | audience |
|---|---|---|---|
| `cli.terminal` | `cli.terminal` | 保留独立工具屏，组改为 `research` | authenticated |
| `capability-router.self-service` | `capability-router.self-service` | 保留 MCP 自助接入屏，组改为 `research` | authenticated |
| `ai-ops.my-providers` | `ai-ops.providers` | 个人服务商、个人 quota、个人日志并入普通用户 AI 工具屏；删除注入屏实体 | authenticated |
| `command-center.auto-advisor` | `command-center.decision-flow` | 自动投顾 action 并入每日决策流；删除注入屏实体 | authenticated |
| `risk-center.overview` | `macro-regime.strategy` | 风控 action 并入策略与风控；删除注入屏实体 | authenticated |
| `realtime-monitor.alerts` | `execution.audit` | 提醒与订阅 action 并入事件与复盘；删除注入屏实体 | authenticated |
| `ai-ops.system-providers` | `ai-ops.system-providers` | 保留为“AI 系统治理”目标屏 | admin |
| `ai-ops.user-quotas` | `ai-ops.system-providers` | 用户配额 action/panel 并入 AI 系统治理；删除注入屏实体 | admin |
| `capability-router.mcp-center` | `capability-router.mcp-center` | 保留为“MCP 与能力治理”目标屏 | admin |
| `capability-router.gateway` | `capability-router.mcp-center` | gateway action/panel 并入 MCP 与能力治理；删除注入屏实体 | admin |
| `capability-router.admin-access` | `capability-router.mcp-center` | 用户 MCP 授权 action/panel 并入 MCP 与能力治理；删除注入屏实体 | admin |

runtime 归位必须修改 `tui_metadata_runtime_injection_registry.py` 及对应 injection 定义中的 `screen_key`、`target_screen`、workflow 链和 module/group；不能只依靠 screen patch 覆盖。

### 2.4 每日决策 8 步链

| 步骤 | 屏 key | 用户产出 |
|---:|---|---|
| 1/8 | `command-center.overview` | 明确今日待办和是否存在阻断 |
| 2/8 | `macro-regime.overview` | 明确 Regime、脉搏和市场温度 |
| 3/8 | `policy.workbench` | 明确政策档位、待审事件和热点 |
| 4/8 | `command-center.decision-flow` | 形成今日决策建议或执行计划 |
| 5/8 | `research.signals` | 确认有效信号和最值得推进的候选 |
| 6/8 | `execution.accounts` | 确认账户健康、持仓和组合状态 |
| 7/8 | `macro-regime.strategy` | 确认 Beta Gate、主动风控和策略约束 |
| 8/8 | `execution.audit` | 查看事件、提醒和复盘证据并完成留痕 |

## 三、面板与默认动作契约

### 3.1 通用硬约束

每个 dashboard 任务屏必须满足：

1. 首屏最多 2 个 P0 panel；首页可保留现有首页布局作为例外。
2. P0 panel 必须有稳定 `action_key`、`user_priority=p0` 和明确 `presentation_semantic`。
3. authenticated P0 自动加载 action 必须是 GET/read 且没有未解析必填字段。
4. admin P0 可使用 GET/admin，但只允许在 `screen.audience=admin` 且 action 已包含在当前 screen 响应时自动运行；后端权限校验仍是最终授权边界。
5. P0 数据为空、失败或过期时必须显示可行动的 empty/error/stale 提示，不得只显示空白卡片。
6. panel 只能引用已发布 action；runtime-only action 的 panel 留在 runtime injection 定义中，或先将 action 提升到 curated 的 `APPROVED_OPERATION_ACTIONS`。
7. datagrid 的 `columns` 必须来自真实 view model 契约；不得凭 UI 文案猜字段名。未核实字段前可省略 `columns`，由通用 renderer 使用 action view model。

### 3.2 published 目标屏 P0 清单

| 最终屏 | default action | P0 panel key / kind / action | P1/P2 方向 |
|---|---|---|---|
| `command-center.overview` | dashboard 屏不强制 default | 保留 `today-queue` / datagrid / `decision.workspace.today_queue` | Regime/Pulse 改绑本屏 `operator.home.market_context`，账户/Alpha 改绑 `operator.home.account_signal_summary`，任务改绑 `operator.home.data_task_summary`；详情通过 `target_screen` 导航；新增 `dashboard.v1_summary` 为 P1 组合摘要 |
| `macro-regime.overview` | `regime.current` | `regime-quadrant` / regime_quadrant / `regime.current`；`pulse-turning` / detail / `pulse.current` | P1 `policy.workbench_summary`、`data_center.market_thermometer`；P2 `regime.navigator_history` |
| `policy.workbench` | `policy.queue_summary` | `policy-summary` / detail / `policy.queue_summary`；`policy-items` / datagrid / `policy.workbench_items` | P1 `auto.api.get.api.policy.status`；P2 RSS/采集配置 |
| `command-center.decision-flow` | `auto.api.get.api.decision.workspace.aggregated` | `decision-summary` / detail / `auto.api.get.api.decision.workspace.aggregated`；`action-recommendation` / detail / `auto.api.get.api.dashboard.action-recommendation` | P1 六步上下文与自动投顾；写操作进入可执行操作区 |
| `research.signals` | `auto.api.get.api.alpha-triggers.candidates.actionable` | `actionable-candidates` / datagrid / `auto.api.get.api.alpha-triggers.candidates.actionable`；`active-signals` / datagrid / `signal.active` | P1 `alpha.scores`；P2 情绪与筛选健康 |
| `execution.accounts` | `auto.api.get.api.account.health` | `account-health` / detail / `auto.api.get.api.account.health`；`positions` / datagrid / `auto.api.get.api.account.positions` | P1 `auto.api.get.api.account.portfolios`、`auto.api.get.api.account.transactions`；P2 绩效和参数 |
| `macro-regime.strategy` | `auto.api.get.api.beta-gate.decisions` | `beta-gate` / detail / `auto.api.get.api.beta-gate.decisions`；`active-hedge-alerts` / datagrid / `auto.api.get.api.hedge.alerts.active` | P1 风控底线、轮动建议、策略与仓位规则；P2 对冲、节奏和详细策略配置 |
| `execution.audit` | `auto.api.get.api.audit.health` | `audit-health` / detail / `auto.api.get.api.audit.health`；`event-metrics` / detail / `auto.api.get.api.events.metrics` | P1 实时提醒、决策痕迹；P2 分享、历史和高级审计 |
| `research.asset-lab` | `auto.api.get.api.asset-analysis.pool-summary` | `asset-pool` / detail / `auto.api.get.api.asset-analysis.pool-summary`；`backtest-stats` / detail / `backtest.statistics` | P1 因子、基金排行和板块；P2 单对象详情 |
| `ai-ops.terminal` | `terminal.agent_chat` | `agent-attention` / datagrid / `agent_runtime.needs_attention` | AI 对话保持主操作；任务队列和产物作为 P1/P2 |
| `ai-ops.providers` | `auto.api.get.api.ai.me.providers` | `my-providers` / datagrid / `auto.api.get.api.ai.me.providers`；`my-ai-logs` / datagrid / `auto.api.get.api.ai.me.logs` | P1 能力清单、模型和提示词模板；个人 CRUD 由 runtime action 提供 |
| `api-library.data-center` | `auto.api.get.api.health` | `system-health` / detail / `auto.api.get.api.health`；`data-center-status` / detail / `auto.api.get.api.data-center` | P1 ready、Celery、任务监控；P2 指标/provider/config-center |

`capability-router.self-service`、`cli.terminal`、`ai-ops.system-providers`、`capability-router.mcp-center` 使用各自 runtime 定义中的 panel/default action；Phase 2/3 必须同步验证其 audience 与自动加载行为。

### 3.3 action 密度预算

合并来源屏后，预计 `execution.accounts` 原始 action 约 66 个、`macro-regime.strategy` 约 80 个、`research.signals` 约 38 个。屏数减少不能以制造更大的表单目录为代价，因此增加以下验收门槛：

- 首屏可见的 `primary + operation` 原则上不超过 10；`command-center.decision-flow` 最多 12。
- 每个 `task_group` 首屏可见 action 不超过 6。
- support/advanced 默认隐藏；带 ID/path 参数的详情优先转为 `row_actions` 或条件出现，不作为首屏 primary。
- 写操作保持独立“可执行操作”区，并保留确认、验密和审计。
- 若仅靠 task tier、row action 和 conditional provider 无法满足预算，可在 Phase 0 决策后对 `frontend/tui-workbench/src/30-actions.js` 增加组级折叠；该改动不得改变 chrome、三栏布局或快捷键。

## 四、落地机制

### 4.1 curated 与 runtime 的边界

**published 目标屏以 curated promotion 为主，runtime-only 能力在 injection registry 收口。**

原因：

- runtime patch 不能可靠删除 published screen/group/module，且会造成审核发布图与用户最终图偏离。
- 下次 generate + promote 会重新应用旧路由规则，纯 patch 收敛容易被管线回生覆盖。
- `promote_tui_business_screens.py` 已集中维护 `SCREEN_SPECS`、`ACTION_SCREEN_RULES`、`EXACT_SCREEN_RULES`、`DAILY_WORKFLOW_STEPS`、`BUSINESS_CONTEXTS`、`TASK_GROUP_RULES`、`EXACT_LABELS` 和 `SCREEN_USER_EXPERIENCE_OVERRIDES`。
- runtime 注入屏与 action 的真源是 `tui_metadata_runtime_injection_registry.py` 及各 injection 文件，必须在这些真源中完成归位。

### 4.2 curated 改动点

1. `SCREEN_SPECS` 重写为 12 个 published 目标屏，并设置 `group`、`module_key`、`audience`、`default_action_key`。
2. `ACTION_SCREEN_RULES` / `EXACT_SCREEN_RULES` 按 2.2 映射重写 372 个 published action 的归属。
3. `DAILY_WORKFLOW_STEPS` 改为 8 步链。
4. `BUSINESS_CONTEXTS`、`EXACT_LABELS`、`TASK_GROUP_RULES`、`SCREEN_USER_EXPERIENCE_OVERRIDES` 同步更新。
5. 新增 `SCREEN_DASHBOARD_PANELS` curated 结构，在 `_apply_user_facing_design_metadata` 之前注入目标屏。
6. 将首页稳定使用的 `operator.home.market_context`、`operator.home.account_signal_summary`、`operator.home.data_task_summary` 等 aggregate action 提升到 curated `APPROVED_OPERATION_ACTIONS`，确保 panel action 与 `command-center.overview` 同屏；`target_screen` 只负责打开详情，不替代数据 action 归属。
7. groups/modules 显式重建为 `daily/research/system`；不能依赖 `_prune_empty_screens` 删除空 group/module。
8. promotion 完成后断言 37 个来源屏全部有唯一目标，不允许 action 留在已删除屏。

### 4.3 runtime 改动点

1. 按 2.3 修改 11 个注入屏的保留/合并策略。
2. 被合并 runtime action 的 `screen_key`、panel `target_screen`、workflow previous/next 同步指向最终屏。
3. 删除不再需要的 runtime group/module/screen 注入，避免目录回生。
4. `RUNTIME_SCREEN_PATCHES` 只保留结果展示、runtime-only panel 等必要小补丁，不再承担 IA 主路由。
5. `USER_HIDDEN_SCREEN_ACTION_KEYS` / `USER_CONDITIONAL_SCREEN_ACTIONS` 按最终屏复核。
6. 对 admin GET panel 增加受控自动加载能力：仅当前返回屏为 `audience=admin`、action 已在该 screen payload 中、HTTP method 为 GET/HEAD/OPTIONS 时允许；不得放宽 POST/PUT/PATCH/DELETE，也不得绕过后端权限。

### 4.4 旧 screen key 兼容

新增显式 `LEGACY_SCREEN_ALIASES`，使用 2.2/2.3 的来源屏 → 最终屏映射。兼容规则：

- `/tui/?screen_key=<old>` bootstrap 深链解析到对应最终屏，不回首页。
- screen API 收到旧 key 时返回对应最终屏，并在响应中保留 `requested_screen` / `resolved_screen`。
- 分享快照、收藏和 workflow 中保存的旧 key 使用同一 alias resolver。
- 未知且不在 alias 表中的 key 才回退 `default_screen`。
- alias 至少保留两个正式版本周期，移除前必须先扫描文档和持久化引用。

### 4.5 AgomTUI 可移植性边界

本计划只收敛 AgomTradePro 产品 IA；跨仓库交付按 `agomtui-portability-remediation-2026-07-21.md` 执行：

- 通用 Runtime/Workbench 改动必须先在 AgomTradePro 上游实现，再通过既有 manifest 单向同步到 AgomTUI。
- 13/16 屏业务 metadata、published graph、runtime injection、权限和 action executor 继续由 AgomTradePro 持有，不进入 AgomTUI core/runtime。
- AgomTUI 壳通过同源 `/api/tui` 使用 AgomTradePro 的角色过滤后 catalog、screen 和 action contract。
- 本计划删除旧屏前必须同步修复 `frontend/agomtradepro-host/src/index.js` 中的 `api-library.runtime`、`capability-router.gateway` 等旧 key。
- 本地发布前必须用 AgomTradePro 与 AgomTUI 两套 validator 校验最终 published graph；AgomTUI 实际同步与集成 UAT 由配套整改方案独立收口。

## 五、分阶段实施

### Phase 0 — 真源清单与“环境与脉搏”样板

- 建分支 `dev/refactor-tui-ia-consolidation`。
- 将 2.2、2.3 映射固化为机器可断言的数据结构。
- 完成 `macro-regime.overview` 的 screen spec、action 路由、panel、UX 和旧 key alias。
- 跑通完整 generate → smoke → promote → validate 序列。
- 浏览器验证：打开即见 Regime 象限和脉搏预警，无需提交表单。
- 量化 action 密度；决定 metadata 分层是否足够，是否需要组级折叠。

**Phase 0 完成门槛**：

- P0 两个 panel 自动加载成功。
- navigator/pulse/market-thermometer 退出目录。
- 三个旧 key 均解析到 `macro-regime.overview`，不是首页。
- action 分节与密度预算通过。
- 局部单测、JS 测试和 Playwright 样板测试全绿。

### Phase 1 — 每日决策 8 屏

- 按 Phase 0 模式完成 daily 组其余 7 屏。
- `DAILY_WORKFLOW_STEPS` 切换为 8 步链。
- `command-center.auto-advisor`、`risk-center.overview`、`realtime-monitor.alerts` action 完成归位。
- 为 8 屏增加 P0、workflow、alias、action 密度断言。
- 浏览器以普通用户走完整 8 步流程。

### Phase 2 — 研究与普通用户自助

- 完成 `research.asset-lab`、`ai-ops.terminal`、`ai-ops.providers` 合并。
- 保留 `capability-router.self-service`、`cli.terminal`。
- 将 `ai-ops.my-providers` 合并到 authenticated 的 `ai-ops.providers`，不得误归 admin。
- 验证个人服务商 CRUD、个人 quota/log、MCP token/endpoint/prompt 等自助能力。

### Phase 3 — 管理员治理与 runtime 收口

- 完成 `api-library.data-center`、`ai-ops.system-providers`、`capability-router.mcp-center` 三个治理屏。
- 合并 system providers/user quotas 与 gateway/MCP/admin-access。
- groups/modules 最终切换为 3 组；删除被合并 runtime screen 注入。
- 完成 admin GET panel 受控自动加载及其前后端权限测试。
- 分别用普通用户和管理员验证最终目录数量：13 / 16。

### Phase 4 — 发布与文档收口

- 运行第六节全量验证。
- 完成 4.5 的本地可移植性门禁：双 validator 通过、host adapter 无已删除 key、上游 Runtime build/check/test 全绿。
- 按配套整改方案生成 AgomTUI 交接证据；AgomTUI 的 schema 独立提交、`--apply` 同步和同源 UAT 不与本计划的业务 metadata commit 混合。
- 人工复核 compact published graph 后，执行 `publish_tui_metadata.py --approve` 写入 DB registry。
- 更新 `tui-user-facing-design-standard.md`、`tui-metadata-promotion-guide.md`、`docs/INDEX.md`、相关 quick reference 和本文件状态。
- 交付总结按 AGENTS.md 列明：已完成项、未完成项、已验证测试、未验证风险。

每个 Phase 独立形成可验证 commit；不得把 daily 主线、runtime 权限重构和发布文档无边界堆在单个提交中。

## 六、验证与回归

### 6.1 metadata 发布序列

以下命令以当前仓库脚本参数为准；不得使用旧参数名或省略 smoke 输入/输出路径：

```powershell
agomtradepro\Scripts\python.exe manage.py export_tui_django_contracts --output tmp\tui_django_contracts.json
agomtradepro\Scripts\python.exe manage.py spectacular --file tmp\tui_openapi.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\validate_tui_metadata.py config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py --include-safe-api-actions 9999 --include-parameterized-api-actions 9999
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py --include-safe-api-actions 9999 --include-parameterized-api-actions 9999 --publish-ready --output config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\smoke_tui_actions.py --metadata-path config\tui\published\tui_operation_graph.published.json --json-output tmp_tui_smoke.json --prune-output config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\promote_tui_business_screens.py config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\smoke_tui_actions.py --metadata-path config\tui\published\tui_operation_graph.published.json --json-output tmp_tui_smoke.json --fail-on-error
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\validate_tui_metadata.py config\tui\published\tui_operation_graph.published.json
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\validate_tui_metadata.py config\tui\generated\tui_operation_graph.generated.json
agomtradepro\Scripts\python.exe manage.py check
```

### 6.2 单元与前端测试

每个 Phase 至少运行：

```powershell
agomtradepro\Scripts\python.exe -m pytest tests/unit/test_tui_workbench.py tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_runtime_optimization.py -q -p no:cacheprovider
npm run test:tui-js
npm run check:tui
```

合并前补齐 AGENTS.md 固定最小回归包：

```powershell
agomtradepro\Scripts\python.exe -m pytest tests/unit/test_tui_workbench.py tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_runtime_optimization.py tests/unit/test_terminal_agent_service.py sdk/tests/test_sdk/test_client.py tests/unit/test_internal_ssl_redirect.py -q -p no:cacheprovider
```

必须新增或更新以下自动断言：

- 37 个 published 来源屏全部映射到 12 个 published 目标屏。
- 11 个 runtime 注入屏全部按 2.3 保留或归位。
- 普通用户目录为 13 屏，管理员目录为 16 屏。
- 普通用户看不到 3 个 admin 治理屏；管理员可以看到并自动加载 P0。
- 每个 dashboard 目标屏的 P0 action 存在、角色可见、无未解析必填字段。
- 8 步 workflow 的 previous/next/total 全部一致。
- action 不引用已删除 screen；panel 不引用不存在的 action/target screen。
- action 密度预算通过。
- 所有旧 key alias 指向预期目标；未知 key 才回首页。

### 6.3 浏览器验收

新增专门的 Playwright 用例，不以现有 MCP layout guardrail 代替本次业务验收：

- 参数化打开 8 个 daily 屏，确认 P0 首屏可见且无需填写表单。
- 普通用户走完整 8 步流程，previous/next 均正确。
- 普通用户验证 AI 个人服务商与 MCP 自助；确认看不到 admin 治理屏。
- 管理员验证 3 个治理屏及 admin GET P0 自动加载。
- 逐一验证旧 key 深链、screen API 和分享快照恢复。
- 记录并断言无意外 console error、无 panel overlap、无持续 loading。

### 6.4 AgomTUI 可移植性门禁

在 AgomTradePro 本地发布前至少运行：

```powershell
npm run build:tui
npm run check:tui
npm run test:tui-js
$agomTradeProRoot = (Resolve-Path ".").Path
$agomTuiRoot = "D:\githv\AgomTUI"
Push-Location $agomTuiRoot
$env:PYTHONPATH="$agomTuiRoot\packages\agomtui-core\src;$agomTuiRoot\packages\agomtui-compiler\src;$agomTuiRoot\packages\agomtui-runtime\src"
python -m agomtui_compiler.cli validate-metadata --metadata-file "$agomTradeProRoot\config\tui\published\tui_operation_graph.published.json"
python -m agomtui_compiler.cli check-usability --metadata-file "$agomTradeProRoot\config\tui\published\tui_operation_graph.published.json"
python scripts\sync_from_agomtradepro.py --source-root $agomTradeProRoot --check
Pop-Location
```

若 Runtime 源码发生变化，`--check` 在 AgomTUI 尚未应用同步时预期报告差异；该差异必须全部属于同步白名单。实际执行 `--apply`、AgomTUI 全量回归和同源集成 UAT 按配套整改方案独立完成。

## 七、发布、回滚与完成定义

### 7.1 发布

仅在 JSON、单测、JS、Playwright 和人工目录复核全部通过后发布：

```powershell
agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\publish_tui_metadata.py config\tui\published\tui_operation_graph.published.json --approve --generation-source mixed --backend-version "local-dev" --source-evidence-path config\tui\generated\tui_operation_evidence.generated.json --review-note "Reviewed TUI IA consolidation"
```

DB registry 优先于仓库 JSON；未执行 publish 时，本地或服务器 `/tui/` 可能继续读取旧图。

VPS 发布必须调用 `scripts/publish-tui-release.sh <release-version>`，由同一入口完成幂等 publish 与 active registry 哈希校验；部署后验收再次执行 `publish_tui_metadata.py --check`。发布文件缺失、DB 行缺失或哈希漂移均阻止 release 通过。

### 7.2 回滚

- 保留重构前 reviewed baseline 的文件副本、source hash 和 registry 版本号。
- 回滚时用旧 baseline 再次执行 `publish_tui_metadata.py --approve`，不得直接修改 DB payload。
- VPS 自动回滚必须从 `previous` release 重新发布其 reviewed baseline，不能只回退镜像和软链接。
- 前端若增加 admin GET 自动加载或组级折叠，必须保持为独立 commit，可单独回滚。
- alias resolver 在回滚后仍需兼容新旧两套 key，避免回滚造成二次断链。

### 7.3 总完成定义

- 普通用户 13 屏、管理员 16 屏，数量由 catalog API 自动测试锁定。
- 8 个 daily 屏打开即见 P0，核心判断不依赖手动提交表单。
- 普通用户 AI/MCP 自助能力无回退，管理员治理不向普通用户暴露。
- 37 个 published 屏和 11 个 runtime 屏均有唯一去向。
- 旧 key 解析到对应新任务屏，而不是无差别回首页。
- action 密度、workflow、panel、权限和 console 验收全部通过。
- published JSON、DB registry、文档和测试使用同一 IA 口径。
- 最终 published graph 通过 AgomTUI validator，host adapter 不引用被删除 key，并已形成可复核的 Runtime 同步差异或 `UNCHANGED` 证据。
- AgomTUI `check-usability` error 为 0，首页 panel 使用本屏 aggregate action；存量 warning 已分类且本次不新增。

## 八、边界

- 不改终端 chrome、F1-F10 快捷键、三栏布局、主题和 CLI 视觉风格。
- 不改金融业务逻辑、后端业务 API 和数据库模型。
- 不删除普通用户的 MCP/AI 自助能力。
- 不在本主线加入导航收藏、全局搜索等独立产品增强。
- 允许为本计划完成定义做两类受控前端改动：admin GET dashboard 自动加载；Phase 0 证明必要时增加 task group 折叠。除此之外的前端增强另起主线。
- 不手工编辑生成投影或 DB payload；所有发布变更必须走 generate、smoke、promote、validate、publish 流程。
- 不把 AgomTradePro 业务 metadata、金融业务 action 或 runtime injection 加入 AgomTUI 通用 Runtime 同步白名单。

## 九、实施结果（2026-07-21）

AgomTradePro 侧已完成：

- 新增版本化 IA 真源 `config/tui/ia/tui_information_architecture.v1.json`，显式覆盖 37 个 published 来源和 11 个 runtime 来源；编译器、runtime injection、DB 旧图归一化、深链 alias 与前端 action density 均读取同一契约。
- 发布图收敛为 3 组、3 模块、12 个 published 屏；运行时追加 4 个 retained 屏。普通用户目录为 13 屏，管理员目录为 16 屏。
- 每日流程固定为 8 步；每屏的 audience、主任务、主结果、P0/P1 panel、默认动作和密度预算均进入 metadata，不再由前端按业务 key 判断。
- admin 自动加载只允许当前 admin 屏内的被动读取；写入和 AI action 必须显式触发。
- 旧屏 key 通过 registry alias 归并，未知 key 继续返回有界 404；宿主 adapter 已移除 `api-library.runtime` 和 `capability-router.gateway` 旧引用。
- 最终 compact graph 为 12 screens / 402 actions；严格 smoke 为 241 ok / 142 needs_input / 0 error；本地 DB registry 已发布为 id 3。
- VPS 部署已形成“迁移 → 幂等发布 → 哈希校验 → 启动 → 二次验收”闭环；自动回滚同步恢复上一 release 的 TUI registry。

验证结果：

- Python 固定回归包及新增 IA/权限/兼容测试：288 passed。
- 前端浏览器行为测试：15 passed；`npm run build:tui` 与 `npm run check:tui` 通过。
- published/generated 双 validator 与 `manage.py check` 通过；Ruff 通过。
- AgomTUI 单向同步检查只发现 5 个白名单 Runtime 差异；未执行 `--apply`。
- VPS 发布/验收/回滚合同测试 31 passed；本地 `--check` 已确认 DB registry id 3 与 release canonical hash 一致。
- 高风险固定回归包连同部署测试 260 passed；IA、metadata compiler 与用户面契约补充回归 54 passed；TUI JavaScript 行为测试 15 passed，`check:tui` 通过。
- dev 分支首次远端验证暴露的四类门禁问题已完成代码收口：TUI 增量 mypy 类型回归已消除；Gitleaks 仅对生成图中两个明确的相关性窗口字段键放行；governed MCP read/write 均由目录投影契约覆盖，write guard 直接识别遍历全部 manifest 与 legacy alias 的矩阵证据，不再重复硬编码能力名；Alpha 与 Dashboard 契约测试均隔离股票名称 read-through backfill，Nightly API/迁移阶段增加单测级 timeout 与 faulthandler，杜绝 AKShare 公网调用把整阶段拖到总超时且无堆栈。

配套整改剩余项：AgomTUI 当前 validator 尚未支持本项目既有的 panel `empty_message/error_message/stale_message/row_actions` 契约，跨仓库 validator/check-usability 与同源 UAT 继续由 `agomtui-portability-remediation-2026-07-21.md` 独立收口，不在本次 AgomTradePro 业务 metadata 发布中修改外部仓库。
