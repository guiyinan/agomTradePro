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
- published JSON 中大量 action 文案是永不展示的副本，且已漂移：脚本比对发现 8 处与 runtime 不一致（如 `operator.home.market_context`：JSON "环境、政策、脉搏" vs Python "环境、Policy、Pulse"）。
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

执行纪律：本线为仓库内小收口线，不与 `evidence-hard-gate` 大主线同时扩边；`TUX-01` 先行因为它是唯一阻断级缺陷。每个 unit 的测试、治理清单更新与走查证据是一个验收包，不拆算。

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
- 本阶段只证明三真源边界和运行时引用闭合，不改变 published/IA 文案，不自动修复数据库，不删除 Python patch。8 处漂移双写、runtime screen 文案迁入 publish/review、legacy patch 清理仍未完成，因此 `TUX-02` 保持 `active`；生产/外部 TUI 证据也不在本阶段宣称范围内。

## 6. 风险与回滚

- **文案批量重写风险**：430 个 action 的 label/description 重写可能误伤已被人工序列化的文案；分流时以 `source` 字段与人工策划 key 前缀白名单为界，重写前后做全量 diff 评审。
- **死代码删除风险**：Python screen patch 对非 IA 的遗留/测试 payload 仍可能有效；删除前先固化"生产只加载 IA payload"的契约测试，再删 patch。
- **runtime screen 迁入 publish 流程的风险**：12 个 runtime screen 迁入后发布校验会收紧；`TUX-01` 的回退机制必须先就位，避免迁移期发布失败导致 `/tui/` 不可用。
- **回滚点**：每个 unit 独立提交；published 图谱与 IA 注册表改动均可通过 `publish_tui_metadata.py` 重新发布旧版 payload 回滚（DB 中旧记录自动归档）。

## 7. 与其他工作流的关系

- `web-to-tui-m5`（W3）：本线不触碰其候选证据链；若 `TUX-03/TUX-04` 改动 published 图谱 SHA，需在提交说明中标注对 M5 观察窗口的影响，由 `TUI-01/TUI-02` owner 决定是否重绑候选。
- `evidence-hard-gate`（W1）：本线只改呈现层文案，不改 Evidence 语义；TUI Evidence Strip 相关文案如涉 `must_not_use_for_decision` 等字段，仅以 `EvidenceSummaryDTO` 既有语义为准做翻译层。
- 用户视角审查的原始证据（截图、catalog、走查日志）保存在 `.codex_tmp/tui_review/`，作为本计划的需求来源，不作为正式 UAT 证据。
