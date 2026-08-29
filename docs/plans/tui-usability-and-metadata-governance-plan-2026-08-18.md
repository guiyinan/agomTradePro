# TUI 可用性与 Metadata 治理整改计划

> 创建日期：2026-08-18
> 工作流：`tui-usability-governance`（category: `product_interface_and_runtime`，priority: P1，owner: `terminal`）
> 机器注册表：`governance/active_plan_registry.json`；canonical 收口单元为 `TUX-01` 至 `TUX-05`。
> 本文档只登记需求、证据来源与验收门；执行状态以注册表为准，不在本文维护第二套进度。

## 1. 背景与证据来源

2026-08-18 对 `/tui/` 做了一轮用户视角的四路审查，本计划是该审查的整改收口：

- **信息架构（IA）静态审查**：`config/tui/ia/tui_information_architecture.v1.json` 全量导航树与契约字段核查。
- **发布操作图谱批量分析**：`config/tui/published/tui_operation_graph.published.json`（12 个 screen、430 个 action）脚本化统计。
- **运行时层源码审查**：`apps/terminal/` 下 runtime injection / screen patch / action patch 与 `tui_metadata_repository.py` 的加载覆盖顺序。
- **真机浏览器走查**：本地 runserver + Playwright 截图 8 个代表性 screen，证据存于 `.codex_tmp/tui_review/`（含 catalog.json 与各屏截图）。

审查结论：每日决策主线 8 步结构清晰、published screen 的 `user_experience`/`business_context` 字段完整，是现有 IA 的强项；问题集中在 action 层自动生成文案、screen 超载、runtime screen 治理缺口和三真源腐化。

## 2. 问题清单（按主题归类，均为已核实证据）

### 2.1 阻断级：metadata 校验失败无回退

- 本地 dev DB 中 2026-07-31 已发布的 TUI metadata 无法通过当前代码校验（`Dashboard panel has unreachable collection mutation: policy.workbench...`），导致 `/api/tui/catalog/` 500、整个 `/tui/` 不可用；没有文件版 payload 回退，也没有结构化错误页。
- 校验收紧后存量已发布 payload 没有兼容路径或批量重校验手段，属生产事故级隐患。

### 2.2 用户可见文案泄露技术实现词

- published 图谱约 85% 的 action 是 `auto.api.*` / `param.api.*` 从 API 路由自动提升（`source: approved:smoke-promoted`），未经人工文案整编。
- 7 个非 dashboard screen 的 `default_action_key` 直接是路由生成 key（如 `auto.api.get.api.account.health`）；16 处 panel 的 `action_key` 同类。
- 机翻/分词截断文案实例："策略 全部ocation Policie 当前"、"提示词s 模板 Categorie"、"账户 Mcp Self"、"AI 能力 Mcp Acce Verify"、"健康 Db"、"Celery 健康"、"信号 Unified By 资产"。
- 约 85% 的 action description 只是 "screen summary + （查看）" 样板填充，无独立语义。
- 真机界面裸露：`broker order catalog display only` 占位符（账户屏）、"MustNotUseFor决策"、"GlobalHeat评分"、"SlaExceeded数量"、"QuotaCharged" 等字段名；顶栏显示 `位置: screen:command-center.overview` 内部 key。
- runtime injection 硬编码文案含 "MCP server/tool"、"Routing/Terminal"、"幂等键"、"Policy/Pulse" 等实现术语（如 `tui_metadata_runtime_injection_capability_router.py:40/55/75`、`tui_metadata_runtime_injection_broker_execution.py:607`）。

### 2.3 Screen 超载与 action 密度失控

- 11 个非 dashboard screen 全部超过 action 密度预算（>6）：`macro-regime.strategy` 88 个、`execution.accounts` 66 个、`research.signals`/`ai-ops.providers` 各 38 个。
- `execution.accounts` 混合模拟盘 CRUD、账户健康、持仓、实盘订单审批（6 个行操作）与本地 Agent 状态，模拟与实盘两个风险等级共屏。
- `research.signals` 名为"选股"实际含信号审批/拒绝/删除与观点录入，一屏三类任务。
- `command-center.overview` 8 个 panel（3 P0 + 5 P1），首屏信息密度偏高；其中 `data-task-summary` panel 标 `audience: admin` 且跳转目标为 admin 专属 screen，普通用户必碰壁。
- `execution.audit` summary 承诺"分享和复盘证据"，实际 panel 中不存在这两块内容。
- 同屏 action label 重复：`research.asset-lab`"回测统计"×2、`ai-ops.providers` 3 组 MCP label 各 ×2（`ai-capability`/`ai-capabilities` 单复数两套 key 并存，疑似重复注册）。

### 2.4 信息架构混乱

- `groups` 与 `modules` 一一对应且同名，module 层无信息增量（渲染层虽有折叠规则，注册表层仍是冗余）。
- "研究与工具"组混杂资产研究、AI 助手、CLI 终端、我的账户设置、Prompt 模板，实为杂物筐。
- 易混入口成对："账户与持仓" vs "我的账户设置"；"AI 工具与我的服务商" vs "AI 服务商治理"；"AI 助手"(`ai-ops.terminal`) vs "CLI 终端"(`cli.terminal`)；"MCP 能力治理" vs "MCP 用户接入治理"。
- 12 个 runtime screen 全部缺失 `summary`、`user_experience`、`default_action_key` 等契约字段；`prompt.workbench` 在 `action_density.screen_limits` 中被放宽到 8 个主操作却无任务定义。
- 术语不统一："提示词"/"Prompt"并存；"Regime"（英文）与"象限/环境"（中文）同页混用；"AI 助手/AI 工具/我的 AI 日志/智能任务"四种叫法；"数据日期"/"观测日期"不一致。
- `command-center.overview.default_action_key` 为空字符串而非省略，与其余 screen 形态不一致。

### 2.5 三真源架构性腐化

- 文案生效顺序为：action patch > replace_existing injection > IA JSON > published JSON/DB。12 个 runtime screen 的全部文案只存在于 Python injection，绕过 publish/review 流程。
- published JSON 中大量 action 文案是永不展示的副本，且已漂移：初始脚本比对发现 8 处与 runtime 不一致（如 `operator.home.market_context`：JSON "环境、政策、脉搏" vs Python "环境、Policy、Pulse"）。
- Python screen patch 对生产加载路径基本是死代码（`tui_metadata_repository.py:410-414` 丢弃 IA payload 的 patch），其中残留"统一操作者首页"等旧文案。

### 2.6 界面布局与接线问题（真机走查）

- 政策屏表格列宽挤压，日期断行成"202 6-07-11"，每行 5 个操作按钮竖排溢出单元格。
- 创建类 panel 的同一句提示文案重复出现两遍。
- 底部状态栏"页 -/- | 0 行"在有数据的屏恒为 0，疑似未接线。
- 观测时间落后一个月的数据标"新鲜/可靠"，与 freshness 契约观感矛盾（需先定性是 dev 数据问题还是判定缺陷）。

## 3. 目标与非目标

### 目标

- `/tui/` 在 metadata 校验失败时不再整体 500，有确定性的回退与告警路径。
- 普通用户可见文案不再出现路由 key、字段名、机翻截断词和实现层术语（Token/Endpoint/Prompt 走专门可复制语义的豁免不变）。
- 每个 screen 的 action 数量回到密度预算内，默认动作指向用户主任务而非 API 路由。
- 用户可见文案收敛为单一真源（published 流程），Python 侧不再存在与 published 图谱双写的文案。
- 导航分组按用户任务重排，易混入口消歧，runtime screen 补齐契约字段。

### 非目标

- 不改变 `web-to-tui-m5` 的候选部署、角色 UAT、14 日观察与 cleanup wave 安排；本线只做仓库内可用性与治理整改，不做生产切换。
- 不重做 TUI 视觉主题、不引入新前端框架。
- 不扩展新业务功能；`execution.accounts` 等超载 screen 的拆分只重排既有能力。
- 不动 Evidence/硬闸语义（`must_not_use_for_decision` 等决策安全契约保持不变，只改呈现文案）。

## 4. 工作包（canonical closure units）

| Unit | 波次 | 模式 | 依赖 | 范围 | 唯一退出门 |
|------|------|------|------|------|-----------|
| `TUX-01` | W5 | repository | — | metadata 加载 fail-safe：published payload 校验失败时回退文件版 payload 并结构化告警；存量 DB 记录按当前代码批量重校验，给出修复或归档路径；`/tui/` 不再整体 500 | 人为构造非法 published payload 时 `/tui/` 可降级渲染并显示治理告警；批量重校验命令覆盖存量记录；回归测试证明正常路径不受影响 |
| `TUX-02` | W5 | repository | — | 消灭三真源：删除对生产路径无效的 Python screen patch 死代码；8 处已漂移双写逐一对账并以 published 流程为准；明确 runtime screen 文案的唯一归属并迁入 publish/review 流程 | published JSON、IA 注册表与 runtime 加载结果三方文案一致性有机器校验；死 patch 删除后测试套件通过；不再有 Python 硬编码用户文案覆盖 published 内容 |
| `TUX-03` | W5 | repository | TUX-02 | action 层整改：`auto.api.*`/`param.api.*` 自动 action 与人工策划 action 分流（隐藏为调试语义或批量重写 label/description）；`default_action_key` 与 panel action_key 不再使用路由 key；每屏 action 收敛到密度预算内；消除同屏重复 label 与单复数双注册 | 430 个 action 全量文案机检（无路由 key、无机翻截断词、无样板 description）通过；11 个超标 screen 全部回到预算内；浏览器走查确认主任务首屏可达 |
| `TUX-04` | W5 | repository | — | IA 整理：重排"研究与工具"杂物筐分组；易混入口改名消歧；统一术语表（Regime/象限、提示词/Prompt、观测日期口径）；12 个 runtime screen 补齐 `summary`/`user_experience`/`default_action_key`；修复 admin audience panel 对普通用户的碰壁跳转；`execution.audit` summary 与实际 panel 对齐 | IA 注册表契约测试通过；全部 screen（含 runtime）满足 metadata schema 必填项；普通角色浏览器走查确认无无权访问跳转 |
| `TUX-05` | W5 | repository | TUX-03、TUX-04 | 界面细节收口：表格列宽/断行/行操作溢出修复；创建类 panel 重复提示去重；底部状态栏接线或移除；字段名翻译层（MustNotUseFor、QuotaCharged 等）；"broker order catalog display only" 占位符替换；顶栏内部 key 移除或折叠进调试语义；定性并修复 freshness 观感矛盾 | 8 个代表性 screen 的浏览器截图证据；字段名/内部 key 机检为零；freshness 判定结论记录在案（数据问题则修数据，判定缺陷则修判定） |

执行纪律：`TUX-01` 至 `TUX-04` 的 repository exit gate 已完成；当前唯一 repository execution focus 为依赖已满足的 `TUX-05`。本线不得自动重绑或扰动已经冻结的正式 M5 候选。每个 unit 的测试、治理清单更新与走查证据仍作为一个验收包，不拆算。

## 5. 验证与回归范围

每个 unit 完成时按范围运行：

- `pytest tests/unit/test_tui_workbench.py -q`
- `pytest tests/unit/test_terminal_agent_service.py -q`
- TUI metadata 相关契约测试与 `config/tui/schema/tui_metadata.schema.v3.json` 校验
- 生产 Python 改动：`python scripts/check_mypy_regression.py <changed-files>` 与 `python scripts/check_mypy_debt_ceiling.py`
- 涉及 IA/导航渲染时：补或更新 IA 注册表契约测试
- 文案类改动：新增或更新"用户可见文案机检"脚本（路由 key、机翻模式、样板 description、裸露字段名四类规则），并接入既有 consistency-check

涉及 TUI metadata 改动时同步遵循 `docs/development/tui-user-facing-design-standard.md`，涉及 Classic Web 模板时同步 `docs/plans/web-to-tui-migration-plan-2026-07-25.md` 的迁移矩阵。

## 6.1 2026-08-18 执行回写

- `TUX-01` 已完成仓库 exit gate：`PublishedTuiMetadataRepository` 在数据库发布记录无法通过当前 schema/runtime 校验时，回退 reviewed file payload，并向 catalog 透出 `metadata_health=degraded/file`；结构化 warning 使用 `event=tui_metadata_fallback`、`reason_code=database_payload_invalid`。
- 新增只读 `python manage.py revalidate_tui_metadata_registry --dry-run`，按主键遍历全部 registry 状态，输出稳定 JSON、状态计数、逐行校验结果与修复/归档建议；实跑结果为 `total=8, valid=1, invalid=7, errors=0, writes_performed=0, outcome=partial`。非法行仍不自动改写，需后续受控 repair/archive 决策。
- 本地回归：fallback、revalidation 与 actionability contract 合计 `14 passed`；Black/isort、`python scripts/check_mypy_regression.py` 与 `git diff --check` 通过。生产 registry 修复、外部 AgomTUI 与 M5 候选证据链仍未验收。

## 6.2 TUX-02 执行回写（2026-08-18）

- 新增只读 `scripts/check_tui_metadata_source_consistency.py`，把 published JSON、IA 注册表和真实 `PublishedTuiMetadataRepository._load_published_file()` runtime 结果放入同一个机器检查。检查内容包括：published screen key/`ia_version`、IA-owned 用户可见 screen semantic fields、12 个 published + 12 个 runtime screen 的完整集合、runtime screen `summary`/`user_experience`/`default_action_key`、action/panel/target-screen 引用闭合，以及 action key 唯一性。
- 检查输出稳定 JSON；本地实际结果为 `outcome=ok`、`12 published screens`、`24 runtime screens`、`430/889 actions`、`violations=[]`。focused contract `4 passed`；Black/isort、增量 mypy 与 `git diff --check` 通过。
- 同一报告显式记录 `RUNTIME_SCREEN_PATCHES` 的边界：对 full IA payload，已存在于 IA published screens 的 patch key 会被 loader 忽略；不在 IA registry 的 legacy patch key 仍单独列出，避免把“未生效”误写成“已删除”。guard 已接入 `.github/workflows/consistency-check.yml`。
- 在该边界证据基础上删除了 `command-center.auto-advisor` 这一只对应 IA alias 的 Python screen patch；完整 runtime 不再注册该 alias patch，alias 请求仍由 IA 映射到 `command-center.decision-flow`。新增 `test_retired_alias_screen_patch_is_not_registered_after_ia_cutover`，source-boundary focused 回归为 `4 passed`，实际检查仍为 `outcome=ok`、`12/24 screens`、`430/889 actions`、`violations=[]`。
- 随后删除了 `execution.audit` 这一已由 IA canonical screen 完整承载的 Python screen patch；`execution.events` 与 `execution.share` alias 仍解析到该 canonical screen，新增回归确认审计 panels 来自 IA/published graph，source-boundary focused 回归为 `5 passed`，实际检查仍为 `outcome=ok`、`12/24 screens`、`430/889 actions`、`violations=[]`。
- 在同一 source-boundary 内继续收窄 `research.signals` patch：删除与 IA/published graph 完全相同的 `label`、`summary` 双写，仅保留默认动作、用户体验补充、业务上下文和 dashboard panels 等运行行为；新增回归确认该 patch 不再重复 IA-owned copy。该项 focused guard 为 `6 passed`，不改变 runtime screen/action 结果。
- 基于上述 full-IA payload 证据，进一步删除已完全由 IA/published graph 承载、且不会在 canonical runtime 生效的 `research.signals` Python screen patch；研究信号的 panels、默认动作与用户可见语义继续由 IA/runtime normalization 提供。source-boundary focused `8 passed`、TUI metadata/actionability/IA 合计 `29 passed`，`npm run check:tui` 与 source guard（`outcome=ok`、`12/24 screens`、`430/889 actions`、`violations=[]`）通过。
- 继续收窄 `prompt.workbench` runtime injection：删除与 IA 完全相同的 `label`、`module_key`、`group`、`audience`、`summary`、`view_type`、`default_action_key`、`user_experience` 双写，保留 workflow、business context 与 dashboard panels 等运行行为；新增回归确认注入不再拥有 IA screen copy，normalized runtime 仍保留同一语义与 panels。IA/runtime source focused 回归 `17 passed`，actionability contract `11 passed`，source guard 仍为 `outcome=ok`（12/24 screens、430/889 actions、0 violations）。
- 基于 full-IA normalization 证据删除 `research.asset-lab` 这一已由 IA/published graph 完整承载、且在 canonical runtime 中明确被忽略的 Python screen patch；保留仍未注册于 IA 的 `research.alpha-triggers` legacy patch。新增 source-consistency 回归，normalized screen semantic fields 与 panels 仍逐项等于 IA；source consistency `9 passed`、TUI actionability/IA `21 passed`、`npm run check:tui`、TUI JS `34 passed`，source guard 仍为 `outcome=ok`（12/24 screens、430/889 actions、0 violations），增量 mypy/ruff/Black/isort 通过。
- 对 6 个 `replace_existing` runtime action 完成 copy boundary：`dashboard.allocation`、`dashboard.performance`、`data-center.providers`、`data-center.publishers`、`regime.current`、`regime.navigator_history` 的 `label`/`description` 由 published action 保持，runtime injection 仍提供 endpoint、fields、view_model、task_group 等行为契约；新增一致性回归 `8 passed`，TUI focused 回归 `29 passed`，mypy/Black/isort/diff-check 通过，source guard 仍为 `outcome=ok`（12/24 screens、430/889 actions、0 violations）。
- 基于 full-IA normalization 与 alias 回归证据删除 `execution.events`、`execution.share` 两个不再注册的 legacy screen patch；两个旧 key 仍仅通过 IA alias 解析到 `execution.audit`，canonical audit panels/summary 未改变。source-boundary/actionability/IA focused 回归 `30 passed`，source guard 为 `outcome=ok`（12/24 screens、430/889 actions、0 violations；patch 配置从 15 个收敛至 13 个）。本地只读 runtime 仍保持 24 个 screen；其余非 IA patch、publish/review 迁入、外部 portability 与 M5 生产 UAT 仍未完成，`TUX-02` 保持 `active`。
- 基于 full-IA normalized runtime 与 data-center provider 行操作回归，删除 `api-library.data-center` 旧 screen patch 及空 redundant-action 配置；该 screen 的 IA/published panels、provider columns、`data-center.provider-update`/`data-center.provider-test` row actions 与 receipt panel 均保持不变。新增 canonical source-boundary 与 synthetic legacy-payload 回归；data-center/source focused `14 passed`、TUI metadata/actionability/IA/source 合计 `35 passed`，完整 `tests/unit/test_tui_workbench.py` `255 passed`，source guard 为 `outcome=ok`（12/24 screens、430/889 actions、0 violations；patch 配置 13→12）。legacy payload 不再凭空获得已删除的 screen patch，未宣称外部壳兼容或生产 UAT。
- 基于 full-IA normalized runtime 与 alias 回归，删除 `macro-regime.beta-gate`、`macro-regime.hedge`、`macro-regime.pulse` 三个已失效 screen patch 及 redundant-action 配置；三个旧 key 继续仅经 IA alias 解析到 `macro-regime.strategy`/`macro-regime.overview`，canonical panels/actions 不变。新增 macro alias/source-boundary 与 synthetic legacy-payload 回归；focused TUI metadata/actionability/IA `38 passed`，source guard 为 `outcome=ok`（12/24 screens、430/889 actions、0 violations；patch 配置 12→9）。未宣称外部 AgomTUI portability、角色化生产 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，`TUX-02`/`TUX-04` 继续 active。
- 基于 full-IA normalized runtime 与 IA/runtime 语义对账，删除 `ai-ops.providers` 这一已由 IA/published graph 完整承载、在 canonical runtime 中明确被忽略的 legacy screen patch；AI 服务商 screen 的 label/summary/default action/UX、三块 panels 与 action 引用保持不变。新增 canonical source-boundary 与 synthetic legacy-payload 回归；source consistency `2 passed`，source guard 仍为 `outcome=ok`（12/24 screens、430/889 actions、0 violations；patch 配置 9→8）。仅收口该 dead patch，未宣称外部壳兼容、角色化生产 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，`TUX-02`/`TUX-04` 继续 active。
- 基于 full-IA normalized runtime 与 alias 回归，删除 `risk-center.overview` 这一已由 IA canonical `macro-regime.strategy` 承载、在 canonical runtime 中不再注册的 legacy screen patch；旧 alias 仍解析到 canonical screen，canonical panels/actions 保持不变。新增 IA/runtime source-boundary 与 synthetic legacy-payload 回归；TUI metadata/actionability/IA/source focused `45 passed`，source guard 为 `outcome=ok`（12/24 screens、430/889 actions、0 violations；patch 配置 8→7）。仅收口该 dead patch，未宣称外部壳兼容、角色化生产 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，`TUX-02`/`TUX-04` 继续 active。
- 基于 full-IA normalized runtime 与 alias 回归，删除 `research.alpha-triggers` 这一已由 IA canonical `research.signals` 承载、在 canonical runtime 中不再注册的 legacy screen patch；旧 alias 仍解析到 canonical screen，canonical panels/actions 保持不变。新增 IA/runtime source-boundary 与 synthetic legacy-payload 回归；未宣称外部壳兼容、角色化生产 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，`TUX-02`/`TUX-04` 继续 active。
- 基于 full-IA normalized runtime 与 alias/legacy payload 回归，删除 `execution.account-settings` 这一已由 IA canonical `execution.accounts` 承载、在 canonical runtime 中不再注册的 legacy screen patch；旧 alias 仍解析到 `execution.accounts`，canonical account panels/action references 不变，legacy payload 仍保留自身 screen contract。TUI metadata/source focused `49 passed`，source guard 为 `outcome=ok`（12/24 screens、430/889 actions、0 violations；patch 配置 6→5）。仅收口一项已证实 dead patch，未宣称外部壳兼容、角色化生产 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，`TUX-02`/`TUX-04` 继续 active。
- 四条 push CI 全部成功后，将候选 `9341789dbaf1f4e0239ee6c7aa63b42e0136286f` 以 code-only `-Upgrade` 发布为 release `20260820025103`；TUI `check:tui`/34 个 JavaScript 测试、部署内置 verifier、HTTPS health/ready/root 与未认证保护接口边界复核通过。该项仅记录不可变候选身份与短窗口只读运行；未取得角色化浏览器 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，`TUX-02`/`TUX-04` 与 M5 生产门禁继续 active/fail-closed，详见 `docs/deployment/vps-deployment-evidence-2026-08-15.md`。
- 四条 CI 全部成功后，将候选 `550e458fcab3d62e759b3be21586d6684b6543a4` 以 code-only `-Upgrade` 部署到 VPS，release `20260819175810`、镜像 `sha256:d58001e265c70348c9e26a169e73016e83a89020c995c8a11cefa46d3d96abfd`；部署报告 `dist/remote-build-reports/remote-build-report-20260819175810.json`。远端 source/image runtime match，迁移/schema、Django check、TUI registry、Qlib `pyqlib=0.9.7`/错误 `qlib` distribution absent、Caddy domain/TLS、备份、web/celery worker/beat 与 Celery ping 通过；只读健康检查为 HTTP `200`。本次仅证明候选部署身份与短时只读运行，未取得角色化浏览器 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签，TUX-02/TUX-04 与 M5 生产门禁保持原状态。
- 在四条 CI 全部成功后，将候选 `86ed6008b61c8aeab828f5b46dce90cbe6967244` 以 code-only upgrade 部署到 VPS，release `20260819103557`、镜像 `sha256:05dafc0b8bd95d4c5705edafadd2d2abc63e98ffbaf42085108a70df79d81e3b`；部署报告 `dist/remote-build-reports/remote-build-report-20260819103557.json`。远端迁移/schema、Django check、TUI registry、Qlib `pyqlib=0.9.7`/错误 `qlib` distribution absent、Celery worker/beat 与 TLS verifier 通过；独立 HTTPS `/api/health/` 8/8 为 `200`（约 `1.12–2.13s`），`/api/ready/` 3/3 为 `200`（约 `4.63–10.12s`）。ready 仍报告 `etf_net_flow` stale/degraded observation；本次仅证明候选部署身份与短时只读健康，未取得角色化浏览器 UAT、写后 receipt/refresh、14 日 telemetry、restore/rollback 或 owner/reviewer 双签。
- 本阶段仍不自动修复数据库，也未删除其余 legacy alias patch 或改写 published/IA 文案；已核实的 8 处 copy drift 已完成对账，但 runtime screen/action 文案迁入 publish/review 及 legacy patch 清理仍未完成，因此 `TUX-02` 保持 `active`；生产/外部 TUI 证据也不在本阶段宣称范围内。

## 6.3 TUX-04 执行回写（2026-08-18）

- `config/tui/ia/tui_information_architecture.v1.json` 的 12 个 `runtime_screens` 已逐项补齐 `summary`、`view_type`、`user_experience` 与 `default_action_key`；入口 key 均来自真实 `PublishedTuiMetadataRepository._normalize_runtime_payload()` 的 action 集合，不新增虚构 action，也不改变 runtime injection。
- 新增 `test_runtime_screen_registry_publishes_complete_user_experience_contract`，验证 IA runtime screen 与 normalized runtime 的 summary、UX 和 default action 完全一致；`tests/unit/terminal/test_tui_information_architecture.py` focused 回归为 `9 passed`。
- `execution.audit` 的 summary、business context 与 checkpoints 已按实际 dashboard panels 对齐为审计健康、事件指标、实盘对账和操作审计；IA 与 published graph 保持同一份用户可见语义，新增对齐回归后该 focused 套件为 `10 passed`。
- 本阶段只完成 metadata contract migration；“研究与工具”分组重排、易混入口消歧、术语统一、普通角色浏览器走查，以及外部 AgomTUI portability/M5 生产证据仍未完成，因此 `TUX-04` 保持 `active`。

## 6.3.1 TUX-04 repository closure（2026-08-28）

- IA 的 `research` group 已从 `research-tools` 杂物筐拆分为 `investment-research`、`ai-workspace`、`personal-services` 与 `personal-settings`；个人/系统 AI 服务商、个人/MCP 治理入口、AI 任务助手/命令行任务台及账户设置均以用户任务消歧。IA、published graph 与 runtime normalization 保持同一标签和模块归属。
- canonical vocabulary 固化为 `宏观象限`、`提示词`、`观测时间` 与 `数据基准日`；source guard 对 24 个 normalized runtime screen 和 890 个 runtime action 全量拒绝 `Regime`、`Prompt`、`数据日期`、`观测日期`，实际结果为 0 violations。首页动态状态同时保留原始 reason/status code，并以“未知”“当前没有可用的宏观象限数据”等用户文案呈现。
- 12 个 runtime screen 的 `summary`、`user_experience` 与 `default_action_key` 均由 IA 契约逐屏验证；`execution.audit` 继续与审计健康、事件指标、实盘对账、操作审计四块实际 panel 对齐。
- 普通角色隔离浏览器走查显示 15 个可见 screen、4 个研究/自助模块；`research.asset-lab`、`ai-ops.terminal`、`ai-ops.providers`、`account.self-service` 均可进入。直接访问 `capability-router.admin-access` 显示“当前账号不能打开这个工作区”并返回预期 403；全目录测试同时逐 screen 验证所有 panel target 都属于普通用户可见集合。
- 最终门禁：TUI JS `35 passed`，IA/source/operator focused `64 passed`，完整 Workbench `258 passed`，Terminal Agent `20 passed`；`npm run check:tui`、Black/isort/Ruff、15 个生产文件增量 mypy、full debt ceiling 与 source guard 全绿。完整 Workbench 首轮发现旧测试夹具缺少 AUD-02 新增的三项 critical audit runtime value；未放宽生产 fail-closed 校验，而是显式补齐隔离测试 profile，单例与全量复跑均通过。
- 规范化证据见 [`tux04-repository-closure-evidence-2026-08-28.json`](../testing/tux04-repository-closure-evidence-2026-08-28.json)。本次未部署、未写生产、未做外部 portability 或 M5 candidate rebind；published graph/manifest 哈希已变化，正式候选是否重绑仍归 TUI-01/TUI-02 owner 与授权流程。`TUX-04` repository exit gate 因此完成，唯一 repository focus 顺序推进到依赖已满足的 `TUX-03`；`TUX-05` 继续等待二者同时完成。

## 6.3.2 TUX-03 action copy/density machine baseline（2026-08-28）

- 新增只读 `scripts/check_tui_action_copy_and_density.py`，把 TUX-03 退出范围固定为 IA 的 12 个 `published_screens`；normalized runtime graph 只用于核对继承后的 action tier、同屏重复 label 与这 12 屏的真实密度，不把另外 12 个 runtime-only screen 扩进本 unit。
- 当前真实基线为 430 published / 890 runtime actions：370 个 route-derived action 中 61 个仍处于 `primary/operation`，355 条 description 直接复用 screen summary（其中 349 条为 `（查看）`），22 个 action 命中 10 类机翻/截断规则，published/runtime 分别有 6/8 组同屏重复 label；IA 仍有 7 个 route default 和 16 个 route panel 引用。
- 按 renderer 的同一口径计算 `primary + operation`，12 个 published screen 中 11 个超出 screen budget，另有 12 个 task group 超出组预算；唯一未超 screen budget 的是 `policy.workbench`。focused guard regression 为 `3 passed`，其中单独证明 runtime-only screen 不影响 TUX-03 exit metric。
- 本检查器在债务清零前故意返回 `outcome=blocked`，尚未接入 push CI；下一切片先在 compiler/published/runtime 边界完成 action-specific 文案、自动 action 分层和 semantic reference，再将真实图测试翻转为全绿并接入现有 Consistency Check。当前未发布 metadata、未部署、未写生产、未重绑 M5 candidate，`TUX-03` 保持唯一 active repository unit。
- action copy/semantic reference 切片已完成：compiler 为 read/write/required-input action 生成独立操作文案，route-derived action 默认下沉到 `support/advanced`，IA 的 7 个 default 与 16 个 panel route 引用全部换为稳定的 semantic action key；17 个单复数兼容或冗余注册被确定性裁剪，published/runtime action 由基线 430/890 收敛为 413/871。
- 同一机器检查现已得到 route key 暴露、样板 description、机翻/截断文案、published/runtime 重复 label、route default/panel 引用全部为 0；published validator、三源一致性、Web→TUI migration inventory 与 96 个 focused regression 均通过。validator 报告的 published graph canonical SHA-256 为 `c372a3fe645dfc89e5affd649d130dea1e5ff7de570acebd978dc16cb8add5bd`，compiler 二次生成前后文件哈希一致。
- 密度仍保持 fail-closed：12 个 published screen 中 11 个 screen、11 个 task group 超预算，来源已收窄为 runtime curated injection，而非 compiler route action。下一切片在 metadata repository 归一化边界按 IA 既有预算确定性保留 default/panel 主动作并把溢出 read/write action 分别降为 `support/advanced`；在清零、全量回归和普通角色浏览器走查前不接 CI、不关闭 `TUX-03`。

## 6.3.3 TUX-03 repository closure（2026-08-28）

- 以 430 条原始 published action 为审计基线，删除 17 条单复数兼容或冗余注册后，最终图谱为 413 published / 871 normalized runtime actions。338 条 route-derived action 继续保留必要的能力覆盖，但首层暴露 route key、样板 description、机翻/截断片段、同屏重复 label，以及 route default/panel 引用均为 0。
- `PublishedTuiMetadataRepository` 在 full-IA runtime normalization 的 injection、patch 与 redundant prune 之后执行 action density 收敛；只处理 12 个 `published_screens`，只改 `task_tier`，按 tier/sequence/group/key 确定性保留 default/panel 引用和预算内动作，并把溢出 read/write 分别降为 `support/advanced`。真实图共降级 143 条，最终 screen/group 超预算均为 0；二次归一化幂等，runtime-only screen 不受影响。若 protected 引用自身已超过预算，引用保持可见且机器 guard 继续 fail-closed，不以破坏入口方式伪造通过。
- 普通角色隔离浏览器显示 15 个可见 screen；账户与持仓、研究信号、事件与复盘、我的 AI 服务商、每日决策流、资产研究等代表入口首屏均能看到主任务。走查发现 `simulated-trading.account-create` 降为 advanced 后，P0 panel 可点击但表单曾被 tier filter 隐藏；runtime 现统一 reveal/focus panel/row-action 表单。新增浏览器回归同时证明 advanced write 与 required-read panel 都不会在表单填写前误发请求，真实账户创建 panel 已复验表单可见并聚焦。
- 最终门禁：TUI JS `37 passed`，metadata/compiler/source/density/IA/operator focused `125 passed`，完整 Workbench `258 passed`，Terminal Agent `20 passed`；action copy/density guard 为 `12 screens`、`413/871 actions`、所有 copy/reference/density 指标为 0，source guard 0 violations，static contracts `407 rules / 5 sources`，Web→TUI inventory、published validator、`npm run check:tui`、Black/isort/Ruff、增量 mypy 与 full debt ceiling 全绿。Luna 两轮只读复核提出的 protected-overflow 显式失败语义与 required-read 空参数请求风险均已补测试并关闭，最终无未处理 P0/P1。
- 规范化证据见 [`tux03-repository-closure-evidence-2026-08-28.json`](../testing/tux03-repository-closure-evidence-2026-08-28.json)。本地 SQLite 首页并发读取曾产生可追踪的 `503/database locked` 恢复态；未翻译字段与 broker-order 占位文案继续归 `TUX-05`，不在本 unit 隐藏。此次未部署、未写生产、未做外部 portability 或 M5 candidate rebind；`TUX-03` repository exit gate 完成，唯一 repository focus 推进到依赖已满足的 `TUX-05`。

## 6.3.4 TUX-05 repository closure（2026-08-28）

- Workbench 表格改为固定布局并由局部 scroll host 承担宽表溢出；日期单元格和行操作保持单行，空分页不再显示 `页 -/- | 0 行`，状态栏继续发布当前状态与刷新时间。创建类 dashboard 的重复说明在渲染边界去重，broker legacy 入口解析到 `execution.accounts`，不再显示 display-only 占位符。
- runtime/compiler/published/generated 四处字段翻译统一，19 个重点字段在两份图谱共有 34 次出现，机器 guard 实测 raw field name `0`、可见内部 locator `0`。恢复上次工作区仍保留真实内部目标，但用户只看到 catalog 标签；顶栏内部 screen 定位输入已移除。
- freshness 矛盾按 owner contract 定性：宏观象限 45 日边界内只称“阈值内”并保留降级；政策 `as_of_date` 只表达“今日/历史截面”，不伪装源新鲜度；Pulse 以 8 日边界、未来日期、源指标 stale 和 reliability 任一失败即 `must_not_use_for_decision`。首页最终显示 Pulse“源指标过期 / 不可用于决策”，缺少可验证观测/抓取时间的决策数据继续 `BLOCKED`。
- 8 个代表 screen 均在隔离 SQLite/本地认证浏览器留存截图与 SHA-256；最终 DOM 为 loading/recovery/internal-key/raw-field/technical-label `0`，空 pager 隐藏、状态栏可见、页面无横向溢出。首页曾因 SQLite 并发读取出现可追踪 lock 恢复态，顺序重试后最终证据为 clean；不把该本地现象计为生产可靠性结论。
- 最终门禁：TUI JavaScript `41 passed`，完整 Workbench `308 passed`，Terminal Agent `20 passed`，metadata/compiler/source/presentation/IA/operator focused `130 passed`，TUX-05 current-data nodeid `4 passed`；presentation guard 为 `19 fields / 34 occurrences / 0 raw / 0 internal locator`，static contracts `407 rules / 5 sources`，两份 metadata validator、Web→TUI inventory、`npm run check:tui`、Black/isort/Ruff、5 个生产文件增量 mypy、full debt ceiling、architecture、governance 与 Django check 全绿。
- Windows 完整 current-data runner 原先因 CreateProcess 命令行上限不可执行，现按 28,000 字符顺序分批并有单测。首批 242 个登记 nodeid 展开 300 项后为 `268 passed / 29 failed / 3 errors`；失败均在 AUD-02 引入严格 system-audit composition 后的既有 Equity/Account 读取链，缺少三项 critical audit runtime definition，另 55 个登记 nodeid因 fail-fast 未执行。TUX-05 新增的 4 项已独立全绿；该发现不放宽生产 fail-closed，而是证明 `AUD-02` 先前的 repository-complete 回归结论不完整，机器计划应纠正为下一唯一 repository focus。
- 规范化证据见 [`tux05-repository-closure-evidence-2026-08-28.json`](../testing/tux05-repository-closure-evidence-2026-08-28.json)。本轮未部署、未写生产、未做外部 portability 或 M5 candidate rebind；`TUX-05` repository exit gate 完成，TUI usability workstream 的 repository units 全部关闭。回滚点为恢复旧 Workbench CSS/renderer、字段映射和 operator freshness projection；任何回滚不得恢复 raw screen key、虚假 freshness 或使 stale Pulse 可用于决策。

## 6.2.1 2026-08-20 TUX-02 candidate deployment observation

- `05970a925f0b348574a1805c243d7d9140d3e243` was deployed code-only as release
  `20260820091752` with data volumes preserved. TUI preflight (34 JavaScript tests), built-in
  and expected-commit verifiers, source/image identity, migrations/schema, Caddy/TLS, Qlib,
  backup and Celery worker/beat/ping all passed. Authenticated read-only TUI/operator/policy/
  audit/metrics probes remained healthy; decision and queued runtime boundaries stayed
  fail-closed. This does not constitute role browser UAT, write receipts/refresh, external
  portability, telemetry, restore/rollback or owner/reviewer sign-off; `TUX-02`/`TUX-04` remain
  active.

## 6.2.2 2026-08-20 production role/browser acceptance

- On the active `05970a925` VPS release, dedicated operator/regular HTTPS Playwright runs passed
  the queue role boundary, strategy create/detail/update/readback, user-owned AI-provider
  create/detail/update/readback, confirmation cancel, parameterized primary reads and the
  least-privileged direct-read matrix. The provider test explicitly fills its sensitive API key
  only in the browser's `补填参数` prompt; it never puts the credential in the URL.
- Exact controlled fixtures (strategy id `2`, provider id `9`) were deleted after the run and
  verified absent. Dedicated UAT actors remain provisioned without credentials in source control.
- This is short-window production role/write/readback evidence, not an M5 candidate rebind or
  production sign-off. The formal candidate remains `f3881a04...`/`20260820043710`; 14-day
  telemetry, receipt/refresh audit, backup/restore, live rollback, capacity/chaos, external
  portability and owner/reviewer approval are still outstanding. `TUX-02`/`TUX-04` remain
  `active` and M5 remains fail-closed.

## 6.2.3 2026-08-20 deep-link form viewport fix and current-release acceptance

- The production browser pass exposed a concrete interaction defect: a deep-linked create/update
  form could be attached but remain thousands of pixels below the scrollable action panel after
  layout. `frontend/tui-workbench/src/30-actions.js` now performs a post-layout scroll/focus
  (`requestAnimationFrame` plus a follow-up frame), and the browser regression asserts that the
  requested field is inside the viewport. `npm run check:tui`, TUI JS `34 passed`, focused Python
  metadata/actionability/IA `44 passed`, source guard (`12/24`, `430/889`, `0 violations`),
  mypy debt ceiling and all four push CI workflows passed.
- Commit `28e0c2608eea1c0a4aed51c3a54eed80220db503` was deployed as release `20260820114848`
  with data volumes preserved; built-in and independent VPS verifiers passed. Final HTTPS
  Playwright acceptance with the dedicated operator/regular actors and unique suffix `R0820A01`
  passed queue role filtering, strategy create/detail/update/readback and personal AI-provider
  create/detail/update/readback (`3 passed`). Exact controlled rows were removed and verified
  absent; the sensitive API key was only entered in the browser prompt.
- This is an active-release interaction and role/write/readback result, not external AgomTUI
  portability or formal M5 candidate acceptance. The registry candidate remains
  `f3881a04...`/`20260820043710`; receipt/refresh audit, 14-day telemetry, backup/restore,
  rollback, capacity/chaos and owner/reviewer sign-off remain outside this slice, so `TUX-02`,
  `TUX-04` and M5 remain active/fail-closed.

## 6.2.4 2026-08-20 current candidate deployment and read-only acceptance

- After all four push CI workflows passed for `7cf7e984373af71b6f96b234cefb78b5f319d770`,
  the branch was deployed code-only as release `20260820145119` with remote data volumes
  preserved. The deployment report is
  `dist/remote-build-reports/remote-build-report-20260820145119.json`; source/image
  identity matched (`sha256:6af515cee168cb4a406c158078f73eeab7e7931f331fbbff98b892f9ff701dca`).
  Built-in and independent verifiers passed migrations/schema, Django checks, TUI metadata
  registry, Qlib (`pyqlib=0.9.7`, wrong `qlib` distribution absent), PostgreSQL backup,
  Caddy/TLS, web health, Celery worker/beat and Celery ping.
- Independent HTTPS probes returned `/api/health/` `200`, `/api/ready/` `200`, `/api/` `200`,
  `/api/audit/health/` `200`, and `/api/audit/metrics/` `200`; unauthenticated
  `/api/terminal/runs/` and `/api/tui/` screen probes returned the expected `403`, while
  `/api/regime/current/` remained `503 decision_runtime_blocked` with
  `must_not_use_for_decision=true`. No business write or database restore was performed.
- This is an immutable-candidate, short-window read-only deployment observation. It does not
  provide role browser UAT, write receipts/refresh, 14-day telemetry, backup/restore, live
  rollback, capacity/chaos, external portability or owner/reviewer sign-off; `TUX-02`/`TUX-04`
  and the related production gates remain active/fail-closed.

## 6.2.5 2026-08-20 execution screen patch cleanup

- Removed the `execution.accounts` legacy screen patch from
  `apps/terminal/infrastructure/tui_metadata_runtime_screen_patch_execution.py`. The
  canonical IA/runtime payload already owns this screen, so the patch was ignored on the
  full-IA path. The redundant action-key map remains unchanged because it still serves the
  action deduplication boundary.
- Added source-boundary assertions that the patch is no longer registered, the
  `execution.account-settings` alias still resolves to `execution.accounts`, canonical screen
  semantics/panels/action keys remain unchanged, and a synthetic legacy payload remains
  loadable without receiving the removed patch. Source guard remains `outcome=ok` with
  `12/24` screens, `430/889` actions, `0` violations and configured patches reduced `5→4`.
- Focused metadata/actionability/IA tests passed (`46` combined in the scoped TAR/TUI
  regression set); Ruff, Black, isort, incremental mypy and diff-check passed. This is a
  repository-only dead-patch cleanup; it does not claim external AgomTUI portability,
  production role UAT, write receipt/refresh, telemetry or M5 sign-off. `TUX-02`/`TUX-04`
  remain active/fail-closed.

## 6.2.6 2026-08-20 command-center screen patch cleanup

- Removed the `command-center.overview` legacy screen patch from
  `apps/terminal/infrastructure/tui_metadata_runtime_screen_patch_command_center.py`.
  The IA/published graph already owns the canonical home screen copy, default action and
  dashboard panels; runtime injection continues to supply the canonical operator actions.
- Added source-boundary checks for IA/runtime semantic and panel/action-key equality,
  `command-center.dashboard` alias resolution, and a synthetic non-IA legacy payload that
  remains valid without receiving the removed patch. The source guard remains `outcome=ok`
  with `12/24` screens, `430/889` actions and `0` violations; configured patches reduced
  `4→3`. Focused source/actionability/IA regression passed `48` tests and the complete
  `tests/unit/test_tui_workbench.py` passed `255` tests; `npm run build:tui` refreshed the
  runtime manifest and local quality gates passed.
- This is a repository-only dead-patch cleanup. The three non-IA operator deep-link patches
  (`ai-ops.agent-runtime`, `api-library.runtime`, `api-library.config-center`) remain in
  place pending dedicated deep-link/canonicalization coverage. This does not claim external
  AgomTUI portability, production role UAT, write receipt/refresh, telemetry, restore/rollback
  or M5 sign-off; `TUX-02`/`TUX-04` remain active/fail-closed.

## 6.2.7 2026-08-20 command-center cleanup candidate deployment observation

- After the four push workflows were green for `2f4554b5192191970a3ccbc98420388881725079`,
  the same commit was deployed code-only in `-Upgrade` mode as release `20260820211526`.
  PostgreSQL/Redis volumes were preserved and Celery remained enabled. The first remote Docker
  attempt stopped during image unpack before switching the active service; a same-commit retry
  succeeded, so this is recorded as a transient deployment attempt rather than hidden.
- The built-in and independent verifier both passed: source/image identity
  (`sha256:74d094b6e606ee79a6e73ffd49364a3787c611511432d5194dc9902b2ec17696`), migrations/schema,
  Django checks, TUI registry, Qlib (`pyqlib=0.9.7`, wrong distribution absent), Caddy/TLS,
  healthy web, Celery worker/beat and one-node ping. The structured observation is
  `docs/deployment/tui-command-center-cleanup-2026-08-20-2f4554b5.json`.
- Independent HTTPS probes returned `200` for health/readiness/API root/audit health/metrics;
  readiness exposed stale decision quotes with `must_not_use_for_decision=true`; unauthenticated
  TUI and terminal routes returned `403`; regime returned `503 decision_runtime_blocked` with
  `must_not_use_for_decision=true`. No business write, role browser UAT, receipt/refresh,
  telemetry, restore/rollback or external portability test was run.
- This is an immutable-candidate short-window deployment observation only. It does not rebind a
  formal M5 candidate or unlock TUX-02/TUX-04/TAR/AUD/EVID production gates; all remain
  fail-closed where their independent evidence is still missing.

## 6.2.8 2026-08-22 operations deep-link screen patch cleanup

- Removed the three remaining non-IA operations screen patch dictionaries,
  `ai-ops.agent-runtime`, `api-library.runtime` and `api-library.config-center`, from
  `apps/terminal/infrastructure/tui_metadata_runtime_screen_patch_ops.py`. The redundant
  action-key map remains unchanged. These deep links continue to resolve through the IA
  aliases to `ai-ops.terminal` or `api-library.data-center`; the canonical runtime screen,
  panel and action data remain IA/runtime-owned.
- Added alias/source-boundary regression coverage for all three aliases. The focused metadata,
  actionability and IA suite passed (`52 passed`), the complete Workbench suite passed
  (`257 passed`), and the source guard remained `outcome=ok` (`12/24` screens, `430/890`
  actions, `0` violations, configured screen patches `3→0`). Ruff, Black, isort and
  `git diff --check` passed; the generated TUI runtime manifest was refreshed and
  `npm run check:tui` passed; no production VPS deployment was performed.
- This is a local canonicalization cleanup only. It does not claim external AgomTUI portability,
  role-browser production UAT, write receipts/refresh, 14-day telemetry, restore/rollback,
  capacity/chaos or owner/reviewer sign-off. The B/S CLI boundary remains server-side AI:
  users submit through the thin client and do not install or run a provider-backed Agent
  locally. `TUX-02`/`TUX-04` remain active/fail-closed.

## 6.2.9 2026-08-22 server-side CLI metadata boundary

- `RUNTIME_CLI_SCREEN` now supplies only CLI behavior context; IA remains the sole source for
  the `cli.terminal` label, module/group/audience, summary, view type, default action and user
  experience. This removes a second Python copy without changing the normalized runtime screen.
- `cli.agent_chat`, `cli.agent_stream` and `cli.agent_queue` are explicitly documented and
  tested as POST submissions to `/api/terminal/*`. They submit prompts/task selectors to the
  server-owned Agent Runtime and consume server results/events; the client does not install,
  load provider credentials, or run an Agent locally.
- The focused metadata/actionability/IA regression passed (`53 passed`). This is a local
  source-boundary and UX contract only; no VPS deployment or production provider/MCP/queue
  enablement was performed. TAR-04/TUX-02/TUX-04 and their external UAT, capacity/chaos,
  telemetry, restore/rollback and owner/reviewer gates remain independently fail-closed.

## 6.2.10 2026-08-23 TUX-02/TUX-04 current source-boundary audit

- A fresh local `check_tui_metadata_source_consistency.py` run reports `outcome=ok` with
  `12 published` / `24 runtime` screens, `430` published actions / `890` normalized runtime
  actions, no configured or ignored screen patches, and `0` violations. Older `430/889`
  figures in historical entries remain historical evidence and are not the current baseline.
- The machine registry remains authoritative: `TUX-02` and `TUX-04` are `planned` while the
  repository execution lock is held by `EVID-01`. This audit records current source-boundary
  evidence only; it does not create a second active repository unit or change any gate.
  Publish/review migration, IA group and terminology changes, external AgomTUI portability,
  and ordinary-role browser UAT remain outstanding.
- No VPS deployment, production write, role sign-off, receipt/refresh observation, telemetry,
  rollback/restore or external portability evidence was created. The B/S boundary is unchanged:
  browser/TUI/CLI clients submit to server-side AI Runtime; users do not install or run a
  provider-backed Agent locally.

## 6.2.11 2026-08-23 Web-to-TUI readiness collector observation

- The read-only `check_web_to_tui_cutover_readiness.py --json` collector returned `decision=DENY`
  for `as_of=2026-08-23`. Source consistency and dependency ordering passed, while the immutable
  candidate/version binding, `108` route-page UAT, cleanup/readiness scopes, `101` task telemetry,
  rollback drill, production registry backup and owner/reviewer attestations were all absent.
- This is a current machine-derived denial, not a test failure and not a request to enable the
  gate. It confirms that the repository/runtime contracts are ahead of production evidence; no
  deployment, production write, registry-backup creation, rollback or role UAT was performed.
  `TUI-01` remains `awaiting_production`, `TUX-02`/`TUX-04` remain `planned` in the machine
  registry, and the M5/TAR production gates remain fail-closed.

## 6.2.12 2026-08-23 candidate-guard and full Workbench acceptance recheck

- Commit `e73930f66cc480b9bcac1fe20bb59e42845575a9` separates the EVID-01 authority-inventory
  contract from the Web→TUI M5 candidate contract. The focused EVID-01, candidate-consistency and
  readiness regression passed (`36 passed`); the full `tests/unit/test_tui_workbench.py` suite also
  passed (`257 passed`).
- The local source guard remains `outcome=ok` (`12/24` screens, `430/890` actions, no configured,
  ignored or unregistered patches, `0` violations). Active-plan and governance consistency checks
  both report `0` violations, and all four push CI workflows for this commit are green.
- This is repository/test acceptance only. No VPS deployment or production write was performed;
  the Web→TUI readiness collector remains `DENY`, EVID-01 remains zero-seed/fail-closed, and
  role-based production UAT, write receipts/refresh, telemetry, backup/restore, rollback and
  owner/reviewer attestations remain outstanding. The B/S boundary is unchanged: clients submit
  to server-side AI Runtime and users do not install or run a provider-backed Agent locally.

## 6.2.13 2026-08-23 focused source/actionability recheck

- The current local source guard still reports `outcome=ok`: `12` published / `24` runtime
  screens, `430` published / `890` normalized runtime actions, no configured/ignored/unregistered
  patches and `0` violations. The TUI actionability contract regression passed `12` tests;
  the focused Evidence composition/provider regression passed `24` tests and the candidate
  consistency guard passed `1` test.
- These are repository-only regression facts. No metadata publish, VPS deployment, production
  write, role browser UAT, write receipt/refresh, portability check, telemetry, restore/rollback
  or owner/reviewer sign-off was performed. The machine registry remains authoritative: `TUX-02`
  and `TUX-04` stay `planned` while EVID-01 holds the repository execution focus, and M5/TAR
  production gates remain fail-closed.

## 6.2.14 2026-08-24 TUX-02 runtime screen copy ownership closure

- 对 IA registry 的全部 12 个 runtime screen 逐一核对后，移除 10 个 Python runtime injection
  fragment 中重复的 IA-owned 顶层字段（`label`、`module_key`、`group`、`audience`、`summary`、
  `view_type`、`default_action_key`、`user_experience`）。`cli.terminal` 与 `prompt.workbench`
  已在此前切片中完成同一边界；本次只保留 `key`、workflow/business context、布局、dashboard
  panels 与运行行为，未删除嵌套 workflow 文案或 action/panel 定义。
- `tui_metadata_runtime_injection_registry.py` 的 canonical merge 仍以 IA `public_screen_spec`
  回填语义字段、以 runtime fragment 保留行为字段。新增参数化 source-boundary 回归覆盖
  `account.self-service`、`ai-ops.user-quotas`、`ai-ops.system-providers`、`capability-router.*`、
  `system.*`、`identity-access.user-governance` 与 `broker-execution.qmt-setup`，确认注入不再含
  IA-owned copy，normalized runtime 仍与 IA 语义一致且 panels/target aliases 不漂移。
- 代码改动后重建 `config/tui/agomtui-runtime.manifest.json`；`npm run check:tui` 通过。机器 source
  guard 为 `outcome=ok`（12 published / 24 runtime screens、430 / 890 actions、configured/ignored/
  unregistered patches 均为 0、violations=0）。metadata/source/actionability/IA focused 回归
  `63 passed`，完整 `tests/unit/test_tui_workbench.py` `257 passed`，TUI JS `35 passed`；Ruff、
  Black、isort、增量 mypy regression 与 debt ceiling 均通过。
- 因此 TUX-02 的 repository exit gate（死 patch、8 处 copy drift、runtime screen copy 迁入
  publish/review、三源机器一致性）达到本地验收条件，注册表状态更新为 `completed`；这不是 VPS
  部署、外部 AgomTUI portability、普通角色生产浏览器 UAT、写后 receipt/refresh、14 日 telemetry、
  restore/rollback 或 owner/reviewer 签署证据。EVID-01 的 zero-seed/生产权限门禁、M5/TUI-01 与
  后续 TUX-03/TUX-04 仍保持 fail-closed。
- 首次 push 的 CI 反馈发现两项生成物维护问题：Data Center deterministic inventory 尚未反映本次
  删除的 source lines，且 gitleaks 将 manifest 的公开 SHA-256 内容哈希误报为 generic API key。
  已用 `data_center_architecture_inventory.py --write` 刷新 inventory（`current_surface_references`
  `4345→4335`），并对 `config/tui/agomtui-runtime.manifest.json` 的 64 位内容哈希增加精确 allowlist。
  修复提交 `162255e5e` 的 Architecture Layer Guard、Security Scan、Consistency Check 与 CI Fast
  Feedback 四条 push workflow 全部成功；这只证明仓库门禁，不改变任何生产候选或部署状态。

## 6. 风险与回滚

## 6.3.5 TUX-05 corrective reopen（2026-08-29）

- release `20260829163806` 的候选绑定生产 UAT 已通过 `108/108` route-page 解析、角色最小权限读取、operator/regular 边界与 `9/9` 参数化读取，并形成两条唯一受控写入的 readback/cleanup receipt；但账户 create/cancel 深链连续两次出现表单存在而“创建”按钮不可点击，策略 confirmed update 的数据库写回成功后页面仍超过固定断言窗口停留在“读取数据”。证据为 `config/tui/migration/evidence/web_to_tui_production_uat_checkpoint_20260829163806.v1.json`。
- 经用户精确授权，`TUX-05` corrective reopen 为唯一 repository focus。最小实现范围固定为：修复 action panel 布局后的可见/滚动/聚焦/点击契约；把 confirmed mutation 的完成态绑定真实 action/refresh 收敛而非任意延长超时；为上述两项补 JavaScript/Workbench/Playwright 回归；把 TUI-01 production-safe role/write/cleanup suite 与 AI-01/TAR-05 的外部 AI/queued runtime 验收分离。
- production-safe recorder 不得放宽 gate：仍须从矩阵重算 `108` route results，校验 regular/operator/admin 权限，要求唯一 run ID、entity/PK/actor/owner、confirmation、写后 readback、exact cleanup 与零残留。active RSS、共享 quota、authority/approval、factor/backtest/provider 外部工作、queued runtime、load/fault、maintenance/live rollback 必须 fail-closed 排除，不能以 skip 冒充通过。
- 本 corrective exit 要求：focused TUI JavaScript、完整 Workbench、固定 UAT/recorder contract、metadata/source/actionability/IA、`npm run check:tui`、Web→TUI inventory、mypy/debt/architecture/governance 全绿，并保留真实本地浏览器截图/trace。只有达到该 repository exit 后才允许 coherent commit、CI/review/merge；随后必须从新提交的独立 clean worktree 部署新候选并重跑生产 UAT，旧 release 的 UAT 不继承。
- 回滚点限于本次 Workbench action reveal/settlement、Playwright suite 与 recorder profile 改动；回滚不得恢复不可点击的深链 action、把未完成状态伪装成成功、启用外部 AI/queued runtime，或删除 108-route、角色、receipt/cleanup 门禁。
- corrective 实现已完成：F9 显式展开 support/advanced task 后聚焦搜索框，账户 create/cancel 的 form 与 submit 均由真实 Chromium 断言可见；confirmed mutation 仅在确认请求真实返回后发布“操作完成”。真实 lifecycle 同时暴露 strategy/provider delete 的未渲染 `TemplateResponse`，Infrastructure adapter 现在只在读取无 `data` 的模板响应前显式 render，并由失败先行的组件测试覆盖。
- 完整 production-safe 本地首轮为 `9/10`：`research.signals / signal.list` 与同屏被动 dashboard reads 竞争未修改的 6-slot internal action gate，显式请求收到 `503`。修复没有放大并发、重试或延长超时，而是让可自动执行的非沉浸式 dashboard 深链先于被动 panel 读取；新增 Workbench 回归证明同一 action 从两次请求收敛为一次，沉浸式 dashboard 与普通被动加载契约保持全绿。
- 最终隔离 Chromium production-safe profile 为 `10/10`、`0 skipped`、`162.75s`，覆盖 `108/108` route-page、regular/operator/admin、`9/9` 参数化读取与两条同 run ID 的普通用户自有写回执；strategy/provider create/update 均在 60 秒 SLO 内收敛，随后经 TUI confirmed delete、列表 readback 得到 exact cleanup 与 `residual_count=0`。外部 AI、queued runtime、authority/approval、active RSS/shared quota、load/fault、maintenance/live rollback 均未执行。
- repository exit gate 全绿：TUI JavaScript `44 passed`，Workbench/Terminal Agent `328 passed`，recorder `7 passed`，adapter `3 passed`，presentation/source/density/static/metadata validators、Web→TUI inventory、Black/isort/Ruff、增量 mypy/full debt、architecture、governance、Django 与 active-plan registry 均通过。Sol 完整 diff 审核后另收紧 full external-AI profile，确保它不会继承 production-safe receipt sink。规范化证据见 [`tux05-corrective-repository-closure-evidence-2026-08-29.json`](../testing/tux05-corrective-repository-closure-evidence-2026-08-29.json)。
- `TUX-05` corrective repository exit 因此完成；当前没有 dependency-ready repository unit，execution focus 回到 `null`。远端 CI/review/merge、新 main clean-worktree 候选冻结/部署及 candidate-bound production-safe UAT 仍是 TUI-01 的生产 gate，不由本地证据继承；真实 role owner 确认继续独立 fail-closed。

- **文案批量重写风险**：430 个 action 的 label/description 重写可能误伤已被人工序列化的文案；分流时以 `source` 字段与人工策划 key 前缀白名单为界，重写前后做全量 diff 评审。
- **死代码删除风险**：Python screen patch 对非 IA 的遗留/测试 payload 仍可能有效；删除前先固化"生产只加载 IA payload"的契约测试，再删 patch。
- **runtime screen 迁入 publish 流程的风险**：12 个 runtime screen 迁入后发布校验会收紧；`TUX-01` 的回退机制必须先就位，避免迁移期发布失败导致 `/tui/` 不可用。
- **回滚点**：每个 unit 独立提交；published 图谱与 IA 注册表改动均可通过 `publish_tui_metadata.py` 重新发布旧版 payload 回滚（DB 中旧记录自动归档）。

## 7. 与其他工作流的关系

- `web-to-tui-m5`（W3）：本线不触碰其候选证据链；若 `TUX-03/TUX-04` 改动 published 图谱 SHA，需在提交说明中标注对 M5 观察窗口的影响，由 `TUI-01/TUI-02` owner 决定是否重绑候选。
- `evidence-hard-gate`（W1）：本线只改呈现层文案，不改 Evidence 语义；TUI Evidence Strip 相关文案如涉 `must_not_use_for_decision` 等字段，仅以 `EvidenceSummaryDTO` 既有语义为准做翻译层。
- 用户视角审查的原始证据（截图、catalog、走查日志）保存在 `.codex_tmp/tui_review/`，作为本计划的需求来源，不作为正式 UAT 证据。
