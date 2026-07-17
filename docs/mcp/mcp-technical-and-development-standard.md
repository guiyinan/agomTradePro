# AgomTradePro MCP 技术与开发标准

> 生效日期：2026-07-09
> 治理口径修订：2026-07-13
> 适用范围：`sdk/agomtradepro_mcp/`、`apps/ai_capability/` 中与 MCP 同步/治理有关的代码、SDK/MCP 测试与外部 Agent 接入文档
> 目标：把 MCP 收口为外部 Agent 的统一能力调用协议，而不是内部 API 的等效替代或大规模工具平铺目录。
> 动态治理数据机器唯一真源：`governance/governance_baseline.json`；本标准不得维护 live 数字副本。

---

## 1. 定位

### 1.1 MCP 是什么

MCP 是 AgomTradePro 面向外部 AI Agent 的操作协议层，用于让外部 Agent 在明确身份、权限、风险确认和审计约束下调用系统能力。

MCP 的职责是：

1. 对外暴露少量稳定的 Agent 入口工具。
2. 通过统一能力注册表发现、解释和调用系统能力。
3. 对每次调用执行身份、RBAC、风险、确认、幂等、审计和错误归一化。
4. 向 Agent 提供必要上下文、资源、提示词和能力 schema。

### 1.2 MCP 不是什么

MCP 不得承担以下职责：

1. 不得作为站内 API 的等效替代。
2. 不得把每个 Django API endpoint 一比一包装成 MCP tool。
3. 不得把页面、Dashboard JSON、TUI metadata 或内部调试接口包装成外部 Agent 契约。
4. 不得在 MCP tool 内实现业务逻辑。
5. 不得绕过 Application / API / SDK 中已经存在的权限、校验、风控和审计。
6. 不得作为普通站内 Web/TUI/页面控件的数据访问默认内部调用通道。
7. `terminal agent` 属于例外：它当前是明确的 MCP-backed Agent surface，但必须收口到统一 core tools，而不是继续暴露 legacy 散装工具。

### 1.3 分层边界

| 层级 | 角色 | 是否面向 MCP 直接暴露 |
| --- | --- | --- |
| Domain | 纯业务规则和实体 | 否 |
| Application | 用例、服务、Facade、任务编排 | 可作为能力实现 owner |
| Interface/API | HTTP/DRF 契约 | 可作为外部进程访问后端的 transport，不是 MCP 契约本身 |
| SDK | Python 客户端封装 | 可作为 stdio MCP 的后端访问适配器 |
| MCP | 外部 Agent 协议层 | 是，但只暴露统一入口和任务级能力 |
| AI Capability Catalog | 能力目录与治理投影 | 是 MCP/站内 AI 共用目录，但必须区分 entrypoint |
| Terminal Agent | 站内 Agent 交互面 | 是，可通过受控 MCP 能力调用系统功能 |

### 1.4 关键原则

1. **能力契约优先**：MCP 对外暴露的是 `capability_key + schema + risk + result envelope`，不是 URL、HTTP method 或 Django view 名。
2. **工具数量受控**：MCP 顶层 tool 列表必须保持小而稳定，系统功能通过统一调用工具进入能力注册表。
3. **站内与站外分流**：普通站内 AI、Web Chat、TUI 默认调用 Application Facade 或 canonical API；`terminal agent` 作为受控 Agent surface 可继续通过 MCP，但必须使用统一 core tools 和 capability registry。
4. **所有写操作服务端确认**：前端模式、Agent 提示词和客户端声明不能替代服务端风险确认。
5. **审计不可选**：任何 MCP 调用必须有 `request_id`、真实用户身份、能力键、风险等级、确认状态和结果摘要。

### 1.5 治理数据唯一真源

1. 动态治理数据的机器唯一真源固定为 `governance/governance_baseline.json`。
2. `README.md`、`README_EN.md`、`docs/SYSTEM_SPECIFICATION.md`、现行架构文档、SDK 文档、MCP 指南、技术标准、整改计划、生成型 Module Ledger 和 `docs/governance/SYSTEM_BASELINE.md` 只承担说明、索引、历史证据和验证入口职责，不得复制“当前工具数、能力数、模块数、测试函数数”等 live 数字。
3. MCP 收口统计统一存放在 `mcp_governance`；仓库级静态 `@server.tool()` 定义数继续使用根字段 `mcp_tool_count`。两种口径不得混写或互相替代。
4. 带明确日期的 inventory、classification、验收报告和测试输出可以保留当时快照，但必须标明它们是历史证据，不是当前治理基线。
5. 数量发生变化时，必须先由代码、manifest、catalog 和守卫脚本得出实际结果，再更新机器基线；禁止通过修改文档数字或放宽 baseline 推动验收。
6. `scripts/check_governance_consistency.py` 必须持续校验机器基线结构、代码事实和治理文档引用，并覆盖 README、系统规格、系统拓扑、模块依赖、MCP/SDK 指南及治理计划中的常见中英文数量写法，阻止动态治理数字重新散落到文档。
7. 计划、标准和交接文档可以列出 capability key 与完成证据，但不得使用“第 N 个”“已有 N 个”“累计 N 个”等序号或汇总数量表达实时治理进度；需要数量时只能引用 `mcp_governance` 对应字段及其验证命令。
8. 动态治理数据的更新顺序固定为“代码事实 -> 专项守卫 -> `governance/governance_baseline.json` -> 一致性检查”；README、计划、标准、索引和 `SYSTEM_BASELINE.md` 不得作为更新入口。
9. `docs/governance/SYSTEM_BASELINE.md` 仅在叙事结构、字段来源映射或部署口径变化时更新；单纯数量变化不得触发该文档同步。
10. 只有 `governance/governance_baseline.json` 可以提交动态治理字段的当前值。测试报告、命令输出、PR 描述和交接摘要只能记录带时间戳的执行证据，不得充当第二真源、fallback 或 baseline 更新依据。
11. 文档中的完成状态、冻结结论、优先级和 capability key 清单只用于执行导航，不得通过条目数、连续编号或人工汇总推导 governed、legacy、replacement、unsupported 等当前数量。
12. “已治理”必须由机器证据判定：registry manifest、canonical contract、catalog replacement、专项守卫与机器基线缺一不可；计划或标准中的文字结论不能覆盖机器检查结果。
13. 架构图、拓扑图、流程图和代码块同样属于文档治理范围；只能写固定契约名称或机器字段引用，不得嵌入当前工具数、能力数、模块数、测试数或治理债务值。

---

## 2. 目标形态

### 2.1 MCP 顶层工具

目标 MCP server 默认只注册以下稳定工具族：

| Tool | 用途 |
| --- | --- |
| `agom_bootstrap` | 返回欢迎信息、身份、权限、入口说明、推荐资源和安全规则 |
| `agom_get_agent_contract` | 返回版本化 Agent 运行契约、校验值和结构化决策摘要 Schema |
| `agom_get_workflow_playbook` | 返回任务 Playbook 目录或指定 Playbook |
| `agom_capability_search` | 按自然语言、标签、模块、风险等级检索能力 |
| `agom_capability_schema` | 返回指定 `capability_key` 的输入 schema、输出 schema、风险和示例 |
| `agom_capability_call` | 调用指定能力，执行统一校验、确认、调度和审计 |
| `agom_confirmation_resume` | 对需要二次确认的能力提交确认 token 后继续执行 |
| `agom_workflow_start` | 启动系统认可的多步任务工作流 |
| `agom_workflow_status` | 查询工作流执行状态、证据和下一步 |

### 2.2 分层发现与 Token 预算

1. 默认 MCP surface 只发布固定 core tools；完整 capability manifest 不得通过 `tools/list` 平铺给模型。
2. `agom_bootstrap` 只返回 owner-domain 索引、发现步骤和固定限制，不得返回按字母排序的 capability 样本清单。
3. `agom_capability_search` 默认返回 10 项，服务端硬上限固定为 20；调用方传入更大值时必须在 dispatcher 前后双层收敛，禁止一次输出完整 registry。
4. search 只发布 `capability_key/title/summary/owner_app/risk_level/tags/requires_confirmation/required_roles` 等发现字段。`legacy_tool_names`、`audit_tags`、幂等参数名和完整输入输出 schema 只能由 `agom_capability_schema` 按单项返回。
5. discovery 必须支持中英文任务词路由；中文别名只属于协议检索 metadata，不得复制或改变 Domain 业务规则。
6. Terminal Agent 使用 governed capability 时，只能在 instructions 中发布领域索引与 auto/gated 数量，不得枚举全部 capability key；实际能力选择必须走 `search -> schema -> call`。
7. Terminal Agent composition root 必须显式设置 core tools 为 enabled、legacy tools 为 disabled，不能继承父进程中用于兼容测试的 legacy-on 环境变量。
8. initialize instructions 不得要求无条件预载资源。Regime/Policy 只在研究、信号、配置建议、风险或执行类问题中作为前置上下文；运维、配置和账户查询按用户问题读取相关资源。
9. `scripts/check_mcp_tool_budget.py` 除顶层工具数量外，还必须校验默认 tool definitions 的序列化 UTF-8 字节预算；固定上限为 12,000 bytes。
10. Agent 契约、工作流 Playbook 和 Prompt 正文必须来自版本化配置，不得继续散落在 `server.py` 或各工具函数中；生产可通过 `AGOMTRADEPRO_MCP_AGENT_CONTRACT_PATH` 切换独立配置。
11. 配置必须发布 `contract_id/version/status`，运行时返回内容 SHA-256；Prompt 不得承担权限、确认、幂等或状态机职责。
12. 不得要求、记录或返回隐藏思维链。路由与执行解释统一使用包含意图、能力、假设、缺失参数、风险、证据和下一步的 `decision_summary`。
13. 配置加载失败只能降级到最小安全启动说明，不得关闭 RBAC、Schema 白名单、确认、模拟交易边界或审计。

实现备注（2026-07-10）：

1. 上述固定 core tool 集已在 `sdk/agomtradepro_mcp/tools/core_tools.py` 落地；实时数量读取 `governance/governance_baseline.json` 的 `mcp_governance.default_top_level_tool_count`。
2. 当前仓库已完成默认 MCP 顶层 surface 收口：core tools 默认上线，legacy tools 改为显式兼容模式。
3. `apps/ai_capability` 已开始把 registry manifest 同步为 governed MCP capability 记录，执行目标不再是 raw tool，而是 `agom_capability_call`。
4. `terminal agent` 已开始优先消费 governed capability + core tools；只有在 governed capability 尚未同步时才回退到 raw tool 路径。
5. 普通站内 `web/chat` 路由已增加 source preference：只要存在 builtin / terminal command / API 候选，就不再默认让 `mcp_tool` wrapper 参与竞争。
6. server 默认即处于 `core-only` surface；如需兼容验证 raw tools，必须显式设置 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=true`。
7. `apps/ai_capability` 已引入显式 `semantic_key`，用于表达“同一业务语义”的 API/MCP/terminal capability 映射关系。
8. 路由层已开始按 `semantic_key` 做去重：`web/chat` 优先非 MCP，`terminal/agent` 可优先 governed MCP capability。
9. 当前 governed capability、replacement、legacy 和 unsupported contract 的 live 数量统一读取 `governance/governance_baseline.json`；已迁移清单与默认续做入口以 [MCP 收口整改计划](../plans/mcp-consolidation-remediation-plan-2026-07-09.md) 的 `0.2.2 唯一机器真源字段与验证入口` 与 `0.2.3 当前默认续做顺序` 为准。
10. 当前 write-like governed capability 全部按 preview-first confirmation 收口：首次调用先返回预览，确认后才进入真实写入。
11. 当前 write-like governed capability 全部要求 `idempotency_key`，dispatcher 会拒绝缺失幂等键的请求，并对同键重复请求执行 pending/completed replay 抑制。
12. seed governed capability 在 `core-only` 模式下已具备内部 executor fallback，不要求把 raw tool 再暴露给模型侧顶层 surface。
13. legacy raw tool 在同步进 catalog 时，如已存在 governed replacement，现会写入 `replacement_capability_key`，并在同一语义下以较低优先级参与兼容路径。
14. dispatcher 当前已对 governed write 生命周期输出统一审计事件，覆盖 `preview_staged`、`confirmation_cancelled`、`confirmation_completed`、`idempotent_replay`、`idempotency_conflict`。
15. `apps/ai_capability` 当前已把 governed MCP manifest 的 `audit_tags`、`idempotency`、`replacement_for` 同步进 catalog execution target，保证治理元数据不会只停留在 registry。
16. `scripts/check_mcp_catalog_dedup.py` 当前也会校验 governed write-like MCP capability 在 catalog 投影中仍保留 `audit_tags`，避免 registry 与 catalog 治理面再次漂移。
17. 已核验 `realtime` price alert CRUD 属于错误遗留契约：当前 server build 没有 `/api/realtime/alerts/` canonical API，也没有 `PriceAlert` 实现；price subscription 同样没有 WebSocket consumer 或 polling delivery chain。上述 SDK/raw MCP 入口必须显式 fail fast，禁止创建只保存列表但不交付事件的伪 API。
18. unsupported legacy contract 已进入显式治理面：`sdk/agomtradepro/unsupported_legacy_contracts.py` 维护机器可读清单，`scripts/generate_mcp_tool_inventory.py` 负责把这些 raw tools 与普通 governed 候选分流。
19. `scripts/check_mcp_write_evidence.py` 已把 write 候选证据门禁落为硬校验；具体 live 数量统一读取 `governance/governance_baseline.json`。
20. 对于只具备 SDK/API、缺少 raw tool 或受控 `internal_handler` 证据的候选，不得为了推进统计数字而直接进入 governed replacement。
21. 对于 read-like governed capability，完成口径也必须显式证明：raw tool 或受控 `internal_handler`、SDK 或 canonical API、focused success contract，以及 core-only fallback / catalog replacement 回归全部成立；不能只补 manifest 就算迁移完成。
22. 因此，“默认只暴露小而稳定的顶层工具面”这一标准已在当前代码里达成；后续继续执行计划中的 Phase 2 / Phase 3 / Phase 4 / Phase 6，把 `semantic_key` 扩展为完整治理面，并把更多系统能力迁移为 governed capability。
23. 同一业务语义存在多个 legacy raw tool 时，允许由一个 canonical capability 统一替换，但必须指定唯一 owner、唯一输入输出契约，并在 `legacy_tool_names/replacement_for` 中完整登记所有旧入口。
24. 历史价格读取的 canonical owner 固定为 `data_center.read.price_history`；Realtime legacy history 入口不得把不存在的 `period` 路由固化进新契约。
25. 名义上的 read 如果通过 POST、刷新、轮询或任务触发改变运行状态，不得注册为 read capability；必须改用无副作用的 cached GET，或按 workflow/write 重新执行确认、幂等和审计治理。
26. SDK 方法或 raw tool 指向不存在的 canonical endpoint 时必须冻结并显式记录，不得通过猜测 path、伪造 fallback 或只补 manifest 的方式迁移。
27. legacy/raw/SDK 参数与 canonical API 参数不等价时必须冻结。典型样板是资金流读取的 `period` 与 `start/end` 漂移：在定义唯一转换规则或统一契约前，不得发布 governed input schema。
28. 使用 POST transport 的纯计算能力只有在服务端实现可证明不写数据库、不触发任务、不刷新缓存或外部状态，且输入输出契约稳定时，才允许按低风险无副作用能力治理；`account.calculate.trading_cost` 是当前样板。
29. legacy raw tool 接受任意 `payload` 不代表 governed capability 可以照搬该输入。Sentiment read family 的标准样板是只发布 canonical `date`、`days` 和无参数健康检查，并分别固定单条指数、`indices + total` 与健康状态输出契约。
30. 同一模块中的 read 与 side-effect 能力必须拆分治理。Events 的 query/metrics/status 可以按只读能力发布；publish/replay 会改变事件总线或触发处理器，必须进入 write/workflow 的确认、幂等和审计链。
31. SDK 的动态默认值必须在 governed capability 中显式化。Audit summary 的无参数模式固定解释为 rolling 30-day query，并返回解析后的日期；互斥查询模式和成对参数必须在 fallback 层拒绝歧义输入。
32. list 输出默认使用命名对象 envelope，不得把裸数组作为新的 governed 顶层结果；Account 持仓、组合目录、交易记录、资金流水和交易费率配置分别使用 `positions + total_count`、`portfolios + total_count`、`transactions + total_count`、`capital_flows + total_count`、`configs + total_count`。
33. raw tool、SDK dataclass 与 canonical serializer 对同一字段存在输出语义漂移时必须先冻结，定义唯一 owner 和稳定 schema 后才能解除。Account legacy Portfolio 已按任务语义拆为 `portfolio_catalog`、`portfolio_detail`、`position_records`、`transaction_records` 与 `capital_flow_records`，不得再把目录、详情、记录导出或 Unified Account 语义强行合并为单一 capability。
34. 健康检查、配置目录和状态详情可以跨域按小批次迁移，但仍必须逐条满足 raw tool、正式 SDK、canonical GET、focused API contract、core-only fallback 和 catalog replacement；同批次只表示验证节奏一致，不表示共享业务 owner。
35. HTTP method 不能单独证明 read purity。Sector rotation 虽使用 GET，但空数据路径会调用更新用例，因此所有依赖该路径的 sector list/recommendation/hot-sector/score/detail 能力必须冻结，直到拆出可证明无副作用的 cached read，或按 workflow/write 重新治理。
36. 同一模块只允许迁移证据闭合的子集。Fund 已完成 persisted-only ranking、detail、NAV history、holdings、score 与 pure-compute screen；NAV governed schema 不发布 canonical API 未执行的 legacy `limit`，holdings 不发布兼容别名 `as_of_date`。`fund.read.score` 只允许通过 authenticated strict GET 从持久化 ranking projection 精确匹配标准化基金代码，不得同步基金、构建或保存缺失 performance。Compatibility list/recommendation 与其他 analysis 路径仍须分别补齐唯一契约和副作用分类；POST performance calculation 已确认会持久化快照，必须按本标准的 workflow/write 规则治理。
37. Backtest 首批只读能力固定为 `backtest.read.detail` 与 `backtest.read.list`。list governed schema 只发布 canonical API 实际处理的 `status`、`limit`，不得发布当前 ViewSet 忽略的 legacy `strategy_name`；list 顶层输出固定使用 `backtests + total_count` envelope。
38. Backtest equity-curve 路径已按规则 120 补齐 canonical staff-only DRF action 并解除冻结；run、delete、rerun、decision replay 等会创建、删除或触发任务的路径不得混入 read 批次，必须分别按 write/workflow 的 confirmation、idempotency、preview 和 audit 标准治理。
39. Alpha 的 provider status、universe catalog 与 health 可以作为零参数直接 GET 子集独立迁移，分别固定为 `alpha.read.provider_status`、`alpha.read.universe_catalog`、`alpha.read.health`。两条 staff-only 运维读取固定为 `alpha.read.inference_ops_overview` 与 `alpha.read.qlib_data_ops_overview`，均只发布零参数契约并解包 canonical `success + data`；manifest 必须声明 `required_roles=("staff",)`，服务端仍执行真实 staff 权限校验。Inference overview 不得在读取时清理 stale/completed cache lock，runtime Qlib 配置在 singleton 缺失时必须使用未持久化默认对象；Qlib data overview 只检查本地 calendar 文件和持久化任务结果，不得刷新文件或投递任务。trigger/refresh 继续属于 workflow/write；factor exposure 已改走 authenticated canonical HTTP，但在 Qlib/simple/ETF provider 的外部访问、缓存和持久化边界形成 focused contract 前仍不得发布 governed read。
40. Alpha Trigger 首批只读能力固定为 `alpha_trigger.read.trigger_list`、`alpha_trigger.read.candidate_list` 与 `alpha_trigger.read.candidate_detail`。trigger list 和 candidate list 只发布 legacy raw tool/SDK 已证明的零参数契约，分别返回 `triggers + total_count` 与 `candidates + total_count`；candidate detail 将 canonical `success + result` envelope 归一化为候选对象。SDK-only trigger detail 在补齐 raw tool 或受控 internal handler 证据前不得迁移；create/evaluate/invalidation/generate 必须按实际副作用进入 write/workflow 审计；performance 必须先补 focused success contract 并固定 payload/output 语义。
41. Decision Rhythm 首批只读能力固定为 `decision_rhythm.read.quota_list`、`decision_rhythm.read.request_list`、`decision_rhythm.read.request_detail` 与 `decision_rhythm.read.summary`。quota/request list 只发布 legacy raw tool/SDK 已证明的零参数模式，并分别返回 `quotas + total_count`、`requests + total_count`；request detail 和 summary 将 canonical `success + result` 归一化为业务对象。summary 的 legacy `payload` 不得进入 governed schema，因为 canonical API 当前不读取该参数。cooldown、trend、request statistics、quota by-period 等缺 raw tool 的读取继续留在证据缺口池；submit/reset/execute/cancel 等状态变更路径必须保持 write/workflow 分流。
42. Regime Navigator 的 canonical governed read 固定为 `regime.read.navigator`。该能力只发布 raw tool 和 SDK 已证明的零参数模式，调用 `/api/regime/navigator/` 后将 canonical `success + data` envelope 归一化为 Navigator 业务对象。`BuildRegimeNavigatorUseCase` 及其 `CalculateRegimeV2UseCase` 下游只读取宏观序列、阈值和资产指引配置并执行纯计算，没有落库、刷新、缓存写入或任务触发，因此允许按 read capability 治理。
43. `get_action_recommendation` 不得并入 Navigator read。历史 canonical GET 的 Pulse 刷新与 `ActionRecommendationLog` 写入已按规则 119 拆除，现由独立 `regime.read.action_recommendation` 承担纯读合同；任何恢复 write-on-read 的改动都必须被拒绝。
44. `explain_pulse_dimensions` 继续冻结。当前解释文本只存在于 raw MCP tool 内，没有正式 SDK、canonical API 和 focused success contract，不能把 MCP 内部硬编码文本提升为系统级 governed read。
45. Regime 分布统计的 canonical governed read 固定为 `regime.read.distribution`。能力允许可选 `start_date/end_date`，通过正式 SDK 调用 `/api/regime/distribution/`，并统一返回 `distribution + total_count` 对象 envelope。Canonical 第四象限名称固定为 `Deflation`；SDK 必须把历史 `Repression` 记录兼容归一化为 `Deflation`，不得继续让过时标签进入新契约。
46. POST transport 的 Regime 纯计算样板固定为 `regime.compute.calculate`。迁移前必须证明 canonical action 只读取已持久化宏观事实与阈值配置，不保存 `RegimeLog`、不触发 provider sync、任务或业务 cache 写入，并以严格 serializer 拒绝未知字段；SDK 和 governed schema 只能发布后端真实执行的 `as_of_date/use_pit/growth_indicator/inflation_indicator/data_source`，不得保留后端从未实现的 legacy `use_kalman`。`get_recommended_assets` 继续冻结，因为当前推荐表只硬编码在 raw MCP tool 内，没有正式 SDK/canonical API/focused contract。
47. Decision Workspace 首批纯读能力固定为 `decision.read.recommendation_list` 与 `decision.read.transition_plan_detail`。推荐列表只发布 canonical API 实际校验的账户、状态、用户动作、证券、推荐 ID、忽略项和分页参数，并将 `success + data` 归一化为 `recommendations + total_count + page + page_size`；调仓计划详情按 `plan_id` 读取已持久化计划并归一化为计划对象。两条路径只执行仓储与展示信息查询，不创建计划、不刷新推荐、不更新状态。
48. `decision_workflow_get_funnel_context` 不得按 read-hint 迁移。该 GET 会调用 `GetActionRecommendationUseCase(prefer_cached=True)`；当缓存不存在时会重新计算并写入 `ActionRecommendationLog`，因此不能以 HTTP GET 或 `refresh_pulse_if_stale=False` 作为纯读证据。必须先拆出严格 cached-only context，或按 workflow/write 完成确认、幂等、preview 和审计后再治理。
49. Config Center 直接读取能力必须按 staff-only 子集治理。当前允许发布能力目录、Qlib runtime、训练模板、Alpha universe 目录与成员、训练任务列表与详情；manifest 必须声明 `required_roles=("staff",)`，canonical API 必须继续使用服务端权限类校验真实身份，不能把 manifest 角色声明当作权限执行替代。
50. 配置读取不得通过 singleton 初始化产生隐式写入。Qlib runtime 的 read repository 必须先读取现有 `SystemSettingsModel`；记录不存在时只能使用未持久化默认对象构造响应。任何 `get_or_create`、默认值回填 `save()` 或冷启动初始化都属于写入，不得藏在 governed read 链路。
51. Config Center list 能力统一使用命名对象 envelope：能力目录、训练模板、Alpha universe 与训练任务分别返回 `capabilities/profiles/universes/runs + total_count`。`get_config_center_snapshot` 属于跨模块 composite 聚合，在每个 summary builder 的刷新、缓存、外部状态探测和持久化证据闭合前必须冻结，不得因 HTTP method 为 GET 或子能力已完成迁移而整体认定为 pure read。
52. Rotation 直接读取能力只允许复用静态定义或持久化 ORM 查询。象限、模板、账户配置、资产主数据和 latest persisted signal 可以独立发布；list 输出分别使用 `regimes/templates/configs/assets/signals + total_count`，不得把裸数组作为新的 governed 顶层结果。全局策略配置按名称读取固定为 `rotation.read.config_detail`：只接受 `config_name`，通过 authenticated canonical config catalog 读取持久化配置，并统一返回 `success + config + available_configs + error`，不得继续沿用 legacy raw tool 找到时返回裸配置、找不到时返回另一种错误对象的漂移契约。
53. Rotation 账户配置必须保留 canonical API 的用户范围隔离。detail 能力可兼容按 `config_id` 或 `account_id` 查询，但必须严格要求二选一，禁止同时缺失、同时提供或通过 raw tool 的异常吞并返回伪成功 payload。
54. Rotation recommendation 不属于纯读：当没有可用信号时会进入 signal generation 并持久化结果。配置 activate/deactivate 会更新持久化状态，generate_signal 会进入信号生成链；三者不得借 `rotation.read.config_detail` 的纯读证据迁移。带价格资产和 asset info 会进入行情 integration service；compare/correlation 使用 POST 计算。上述路径必须分别证明无写入、无缓存刷新、无外部状态变更后才能按低风险计算/read 治理，否则按 workflow/write 分流。
55. Unified Account / Simulated Trading 读取必须以 canonical account ownership check 为安全边界。账户目录只发布 canonical API 实际执行的 `active_only/account_type`；账户详情、持仓、绩效和巡检历史必须继续由服务端校验真实用户范围。多个 legacy alias 可聚合到一个 governed capability，但 `executor_ref` 必须使用独立受控名称，避免 legacy-on 模式直接返回未归一化 raw payload。
56. Strategy read family 必须逐路径证明 canonical owner/staff scope。仅有 `IsAuthenticated` 不能替代对象范围授权；strategy、AI config、position rule 等读取必须由服务端 queryset 执行对象范围隔离。基础 strategy catalog/detail 已按第 68 条完成收口，AI config catalog/detail 已按第 69 条完成收口，position rule catalog/detail 已按第 70 条完成收口。`strategy.read.performance`、`strategy.read.signals` 与 `strategy.read.positions` 已完成 owner-scoped canonical route、persisted-only projection、严格 query、正式 SDK、controlled fallback、core-only、catalog replacement 和 read evidence；performance 只表达 execution metrics，不得伪造组合收益。Script config、rule condition、assignment 与 trades 在 raw/internal-handler 证据和同等范围校验闭合前继续冻结。
57. Hedge 直接读取只能复用持久化 pair catalog、active alert 和 latest snapshot，不得在 read fallback 中触发 effectiveness 计算、correlation 计算、portfolio update 或 alert monitoring。POST 计算路径必须先证明 pure calculation；只存在于 raw MCP 的方法解释和资产推荐表不得提升为 governed capability，必须先确定 canonical owner 和可配置真源。
58. Asset Analysis 直接读取只允许发布权重配置目录、当前生效权重和持久化资产池摘要。权重读取在无数据库配置时必须返回未持久化默认值，不得通过 `get_or_create` 或初始化写入补齐；资产池摘要只允许 canonical `asset_type` 参数，不得继承 legacy 任意 `payload`。多维筛选、资产池筛选和其他跨模块评分链必须先按 pure calculation、workflow 或 write 证明副作用边界，不能借同域 GET 的纯读证据直接迁移。
59. Equity 持久化只读子集包含 `equity.read.valuation_repair_list`、`equity.read.valuation_freshness`、`equity.read.valuation_quality_latest`、`equity.read.valuation_analysis` 与 `equity.read.financial_history`。Repair list 只读取持久化修复快照，并归一化为 `repairs + total_count + query`；freshness 和 latest quality 不得触发 provider sync、repair scan、validation 或快照创建。Financial history 必须使用 authenticated strict GET、固定 `hydrate=False` 并执行 annual/quarterly/all 过滤；valuation analysis 只接受 canonical `lookback_days`，不得继续发布旧 `as_of_date` 伪参数。上述能力均必须保持 owner fallback、core-only、catalog replacement 和 read evidence。Score/detail/recommendation/composite analysis、scan/sync/validate 和配置 mutation 仍须按缺 canonical owner、pure calculation 或 workflow/write 分流。
60. Dashboard Auto Advisor 外部只读能力允许发布 `decision.read.advisor_sheet`、`dashboard.read.auto_advisor_console`、`dashboard.query.auto_advisor`、`dashboard.read.auto_advisor_weekly_report`、`dashboard.read.auto_advisor_weekly_report_history` 与 `dashboard.read.auto_advisor_notifications`。动态 advisor-sheet 链必须保持严格纯读：资产名称 cache miss 不得写缓存，手工组合读取不得自动创建统一账户、持仓或 ledger mapping，风险 floor/template 缺失时只能返回未持久化默认对象。所有能力必须继续依赖 canonical API 的 authenticated user scope，并将 `success + data` envelope 归一化为稳定业务对象。weekly report GET 只能生成响应，不得保存周报、投资日记、通知或审计记录；weekly report POST 明确属于持久化 workflow/write。除规则 118 的权益曲线、规则 121 的资产配置和规则 122 的用户持仓目录外，Dashboard v1 页面聚合和内部 Alpha 视图继续保持 internal-only，不得仅因存在 raw tool 就提升为外部 governed capability。
61. Factor 能力必须按路径拆分治理。`factor.read.definition_catalog` 与 `factor.read.config_catalog` 分别只调用 authenticated canonical GET，并返回 `factors + by_category + total_count`、`configs + total_count`。`factor.read.portfolio` 已移除 SDK Infrastructure 直连，只通过严格 `config_name` canonical GET 读取最新持久化 holdings，并由 controlled fallback 归一化为 `config_name + exists + portfolio`；不得生成组合、重算分数或写持仓。`factor.compute.top_stocks` 允许使用 canonical POST，但必须只读取 active factor definitions、持久化股票主数据以及 Data Center 中已有的估值、财务和价格事实；价格链必须以 `cache_price_results=False` 禁止成功读取回写进程缓存，不得保存 exposure、holding、portfolio config 或其他业务记录。因子偏好固定为 `high/medium/low` 的相对重要度，默认 `medium` 必须形成有效正权重，因子正负方向继续由 Domain scoring engine 处理。`factor.compute.stock_explanation` 的额外契约见第 67 条。Create portfolio 和其他 POST/composite 路径须分别完成 workflow/write 副作用分类。
62. Equity 当前股票池目录固定为 `equity.read.pool_catalog`。该能力复用 authenticated `GET /api/equity/pool/`，只发布 raw tool 与 SDK 共同支持的 `sector/min_score/limit`，过滤由正式 SDK 在 canonical 响应上执行；SDK-only `max_score` 不进入 governed schema。输出必须使用 `success + regime + update_time + avg_roe + avg_pe + stocks + total_count + query` 命名 envelope，不得继续发布裸数组。默认读取链只允许读取持久化股票池、宏观事实与阈值、股票主数据、最近估值和最新财务数据；股票池 cache miss 不得回填缓存，估值/财务不得开启 hydrate，Regime 计算不得保存快照。`get_stock_detail` 当前只是对同一池快照的客户端查找，不另建重复 governed capability；screen/recommendation/refresh 继续按 pure calculation、workflow 或 write 分流。
63. `get_alpha_stock_scores` 不得按 read-hint 迁移。Canonical GET 会进入 Alpha provider 自动降级链：Qlib cache miss 可能投递推理任务并写 throttle cache，provider 降级或全部失败可能创建、更新持久化 Alpha 告警，指标记录也属于运行状态副作用。该能力必须拆出严格 cached-only 查询后再定义 read，或按 workflow 完成 preview、confirmation、idempotency、audit 与异步状态查询；不得直接用现有 GET 作为低风险 governed read replacement。
64. 多资产相关性矩阵的唯一 governed owner 固定为 `hedge.compute.correlation_matrix`。Hedge raw `get_hedge_correlation_matrix` 与 Rotation raw `get_correlation_matrix` 输入语义相同，必须作为同一 capability 的 legacy aliases 收口，不得分别发布重复能力。统一能力可使用 POST transport，但必须保持纯计算：只读取持久化 price bars 或现有价格缓存，并以 `cache_result=False` 禁止成功价格读取回写 cache，不得保存 `CorrelationHistoryModel`、生成告警或更新组合快照。输入固定为 `asset_codes/window_days`，输出固定为 canonical `asset_codes + window_days + matrix`。Rotation 兼容 API 同样必须禁止价格缓存回写，但 governed fallback 统一走已验收的 canonical owner。单对 `calculate_correlation` 会保存相关性历史，不能借矩阵能力的纯计算证据迁移；effectiveness、monitoring 和 portfolio update 也必须分别按实际副作用治理。
65. Fund performance 计算不得按 read 或 pure compute 迁移。当前 canonical `POST /api/fund/performance/calculate/` 在读取基金信息和 NAV、计算收益率与风险指标后会调用 `save_fund_performance()` 持久化 `FundPerformanceModel` 快照；legacy `get_fund_performance` 与正式 SDK 均进入该写路径。除非另行拆出严格不保存的 preview/calculate-only endpoint，否则该能力必须按 workflow/write 完成 preview、confirmation、idempotency、audit 与结果状态治理。
66. Rotation 多资产动量比较的 canonical governed owner 固定为 `rotation.compute.asset_comparison`。该能力允许复用 POST transport，但只发布实际参与计算的 `asset_codes`；legacy `lookback_days` 当前只作为兼容回显参数，不得进入 governed schema。计算固定输出 1 月、3 月、6 月动量、均线信号和趋势强度，只读取 Data Center 已有价格事实，必须以 `cache_result=False` 禁止成功读取回写进程缓存，不得解析当前 Regime、保存 MomentumScore、RotationSignal、RotationPortfolio 或其他 Rotation 业务记录。资产代码必须是有界非空字符串列表；带价格资产目录、推荐和信号生成路径不得借用本纯计算证据迁移。
67. Factor 单股解释的 canonical governed owner 固定为 `factor.compute.stock_explanation`。外部契约只发布 `stock_code` 与 `focus`，其中 focus 必须限定为 `value/growth/quality/balanced`，权重映射由正式 SDK 统一维护，raw MCP 和 governed fallback 不得各自复制一套。Canonical POST 可以接受底层 `factor_weights`，但必须校验有界非空因子代码、有限数值、单项范围和至少一个非零权重。计算只读取 active factor definitions、持久化股票主数据及已有估值、财务、价格事实，价格链必须禁止 cache write，不得保存 FactorExposure、FactorPortfolioHolding、FactorPortfolioConfig 或其他业务记录。股票主数据读取不得引用不存在的 repository 并吞掉异常；找不到股票时必须显式返回失败，而不是把真实成功路径退化为固定 500。
68. Strategy 基础读取固定收口为 `strategy.read.catalog` 与 `strategy.read.detail`。Canonical `StrategyViewSet.get_queryset()` 必须让普通用户只看到 `created_by` 指向本人 account profile 的策略，staff/superuser 才可读取全量；列表、详情和对象不存在行为均由同一 scoped queryset 执行，禁止只在列表层过滤后让 detail 绕过。Catalog 只发布真实 API 字段 `strategy_type/is_active` 与 SDK 客户端有界 `limit`，legacy `status` 仅兼容映射 `active/inactive`，不得继续发送 API 不执行的伪查询参数或接受不存在的 `archived` 状态。输出固定为 `strategies + total_count` 和 `strategy` envelope。读取不得执行策略、改变激活状态或写入 Strategy 业务表；script config、rule condition、assignment 继续完成 scope，新增 performance、signals、positions、trades actions 继续完成各自 MCP evidence，不得因 route 已存在就合并语义。
69. Strategy AI 配置读取固定收口为 `strategy.read.ai_config_catalog` 与 `strategy.read.ai_config_detail`。`AIStrategyConfigViewSet` 必须通过关联 `strategy.created_by` 执行 owner/staff scope，普通用户不得通过 list、filter 或 detail 读取其他用户策略配置。Catalog 只发布 canonical `strategy/approval_mode/ai_provider` 对应的 `strategy_id/approval_mode/ai_provider_id` 和 SDK 本地有界 `limit`，不得把服务端不执行的 limit 伪装为 API 过滤。Detail 以 `strategy_id` 查询并显式返回 `exists + config`，配置不存在时不得创建默认记录。两条能力只能读取持久化配置，不得修改 temperature、approval mode、provider、prompt 或 chain 绑定。
70. Strategy 仓位规则读取固定收口为 `strategy.read.position_rule_catalog` 与 `strategy.read.position_rule_detail`。独立 `PositionManagementRuleViewSet` 必须通过关联 `strategy.created_by` 执行 owner/staff scope；按策略 detail 必须复用 scoped `StrategyViewSet`，不得以另一条未隔离 query 绕过。Catalog 只发布 canonical `strategy/is_active` 对应的 `strategy_id/is_active` 与 SDK 本地有界 `limit`，输出固定为 `rules + total_count`；detail 以 `strategy_id` 返回 `strategy_id + rule`。两条能力只读取持久化表达式和 metadata，不得执行 evaluate、创建、更新、启停规则或写入执行结果。
71. Strategy 仓位计算固定收口为 `strategy.compute.position_rule` 与 `strategy.compute.position_management`。前者通过 owner/staff scoped `PositionManagementRuleViewSet.get_object()` 按 `rule_id` 读取活动规则，后者通过 scoped `StrategyViewSet.get_object()` 按 `strategy_id` 读取策略及其绑定规则；普通用户跨 owner 调用必须返回 404，staff/superuser 才可跨 owner 计算。两条能力虽然使用 canonical POST transport，但只能调用 `PositionManagementService.evaluate()` 解析已持久化表达式并返回 `should_buy/should_sell`、价格、仓位和风险收益比，不得创建或更新持仓、订单、执行日志、规则、缓存或异步任务。输入仅允许 ID 与对象型 `context`；缺失规则、未启用规则、非法表达式或缺少变量必须由 canonical API 显式失败，不得在 MCP fallback 中吞并为伪成功。
72. Equity 估值修复实时计算与配置读取固定收口为 `equity.compute.valuation_repair_status`、`equity.compute.valuation_repair_history`、`equity.read.valuation_repair_config` 与 `equity.read.valuation_repair_config_catalog`。status/history 允许使用 canonical GET transport 执行基于持久化股票与估值事实的纯计算，但必须以 `get_valuation_repair_config(use_cache=False)` 读取运行时配置，禁止 cache miss 回写；不得保存 repair tracking、质量快照、行情、配置或任务。History governed 输出必须保留 canonical `stock_code + points + data_quality_flag + data_source_provider + data_as_of_date` provenance，不得沿用 legacy 裸数组丢失数据质量上下文。配置 active/catalog 必须保持 `IsAdminUser` 服务端权限并在 manifest 声明 staff role；无活动配置时只返回 settings/default 的未持久化投影，不得创建默认行。Catalog 的 `limit` 只能由正式 SDK 本地截断，禁止继续向当前 API 发送不执行的伪过滤参数。
73. Dashboard Alpha 历史读取固定收口为 `dashboard.read.alpha_history` 与 `dashboard.read.alpha_history_detail`。列表只允许读取当前认证用户拥有的持久化 recommendation runs，并可按 `portfolio_id/trade_date/stock_code/stage/source` 过滤；详情必须以 `user_id + run_id` 联合范围读取 run 和 snapshots，跨用户访问返回 404。两条能力不得触发 Alpha provider、推理任务、refresh、历史快照创建或其他推荐计算。详情补充历史股票名称时只能读取现有 Data Center asset、legacy holding 和 quote facts；必须跳过 Equity stock-context 的 read-through asset backfill，并禁止把 legacy holding 名称 `update_or_create` 到 `AssetMasterModel`。正式 SDK 对列表输出 `runs + total_count + query`，详情输出 `run` envelope；legacy raw payload 保持兼容。
74. Decision Rhythm 配额重置固定收口为 `decision.reset.quota`。canonical `POST /api/decision-rhythm/reset-quota/` 必须使用 `IsAdminUser`，禁止普通认证用户提交任意 `account_id` 重置其他账户配额；成功响应必须返回 `account_id` 与实际 `reset_periods`。governed schema 只发布非空 `account_id`、可选 `period`（`daily/weekly/monthly`）和治理层 `idempotency_key`，不得继承 legacy 任意 `payload`。preview 必须通过正式 SDK 按账户和周期读取当前持久化配额，返回使用量、执行量和目标周期摘要且不得写库；目标不存在时必须在确认前失败。commit 只能调用正式 SDK reset endpoint，并同时满足 staff-only、显式确认、required idempotency 和 write lifecycle audit。
75. Account 宏观仓位配置更新固定收口为 `account.update.macro_sizing_config`。能力必须声明 staff role、显式 confirmation、required idempotency 和 audit tags；preview 阶段只能通过正式 Account SDK 读取当前 active 配置，返回当前版本、请求变更字段和预期下一版本，不得调用 PATCH/PUT、停用旧版本或创建新记录。确认后固定使用 canonical partial PATCH 创建并激活新版本，真实 staff/superuser 权限继续由服务端 `IsAdminUser` 执行。Governed schema 只发布 `MacroSizingConfigUpdateSerializer` 实际接受的配置字段，不发布 legacy `partial` transport 开关；空变更必须在 internal handler 层拒绝，避免生成无意义的相同配置版本。Terminal Agent 消费该能力时仍通过 MCP core tools 与 registry，Agent Runtime 不得为能力筛选直接依赖 AI Capability Domain 或 Infrastructure，应由 composition root 注入 Application Facade。
76. Prompt 模板创建固定收口为 `prompt.create.template`。Canonical template list 保持 authenticated read，create/update/partial update/delete 必须由服务端 `IsAdminUser` 执行真实 staff 权限；模板名称在 active 与 inactive 记录间全局保留，Application facade 必须通过 Infrastructure repository 查询，数据库唯一约束继续作为并发兜底。Governed schema 只发布 canonical serializer 接受的模板字段；preview 必须通过正式 Prompt SDK 按名称精确查询并包含 inactive 记录，同名时在确认前失败，且只能返回 category、version、占位符数量、内容长度等摘要。commit 只能调用正式 SDK create endpoint，并满足 confirmation、required idempotency、staff role、audit 和 legacy replacement。
77. Policy Event 创建固定收口为 `policy.create.event`。Canonical event GET 保持 `IsAuthenticated`，POST/PUT/DELETE 必须使用 `IsAdminUser`，禁止普通认证用户修改系统政策事实。Governed schema 直接发布 canonical `event_date/level/title/description/evidence_url`，不得继承 legacy `event_type/gear` 漂移；P2/P3 描述长度和 evidence URL 必须在 preview 前完成与 serializer 一致的校验。preview 只能通过正式 Policy SDK 读取目标日期的现有事件，展示同日事件数量及 P2/P3 可能触发告警服务的副作用，不得创建事件或发送告警。commit 只能调用正式 SDK create endpoint，并满足 confirmation、required idempotency、staff role、audit 和 legacy replacement。
78. Equity 估值修复配置草稿创建固定收口为 `equity.create.valuation_repair_config`。Canonical config list、active 与 create 必须保持 `IsAdminUser` 服务端权限；governed schema 只能发布 `ValuationRepairConfigCreateSerializer` 与正式 Equity SDK 共同支持的配置字段及治理层 `idempotency_key`。preview 必须只通过正式 SDK 读取持久化 config catalog 和 active config，计算 latest persisted version、expected next version、请求字段差异和 `is_active_after_create=false`，不得创建草稿、清理运行时配置缓存、修改 active 状态或调用任何 mutation endpoint。权重和、百分位范围及阈值顺序必须在确认前按 canonical serializer 规则校验。commit 只能调用正式 Equity SDK create 方法，禁止下传 `preview_only/idempotency_key`，并保持 canonical 自动递增版本、inactive draft 与 `created_by` 审计语义；activate/update/delete 必须继续作为独立 write 候选治理。
79. Equity 估值修复配置激活固定收口为 `equity.activate.valuation_repair_config`。正式 Equity SDK 必须提供按正整数 `config_id` 调用 canonical detail GET 的精确读取，禁止依赖有界 catalog 截断猜测目标对象。preview 必须读取目标配置和当前 active 配置，展示目标/当前版本，并明确披露旧配置停用、目标激活、`effective_from` 更新和 runtime config cache 清理；目标不存在由 canonical detail 显式失败，目标已经 active 时必须在确认前拒绝无意义 mutation。commit 只能调用正式 SDK activate action，禁止下传治理参数，并满足 staff role、confirmation、required idempotency、audit。Canonical rollback action 与 activate 行为完全等价，因此 legacy `activate_valuation_repair_config` 和 `rollback_valuation_repair_config` 必须共用该 capability，不得为 rollback 创建重复 governed 语义；update/delete 仍须独立治理。
80. Equity 估值修复配置 update、delete 与独立 clear-cache mutation 在正式 SDK 和 raw MCP 证据补齐前必须冻结。存在 canonical endpoint 不能替代完整 write evidence；禁止为满足统计或守卫临时新增 raw `@server.tool()`，也禁止用 create/activate 的证据覆盖不同 mutation。解冻前必须分别具备正式 SDK 方法、raw tool 或既有受控 internal-handler 证据、纯读 preview、staff 权限、confirmation、required idempotency、audit 和 focused contract。
81. Sentiment 全局缓存清理固定收口为 `sentiment.clear.cache`。Canonical cache-clear endpoint 必须使用 `IsAdminUser`，普通认证用户不得删除系统级缓存；manifest 同时声明 staff role，但不得把该声明当作服务端授权替代。preview 只能调用正式 Sentiment SDK `health()` 并读取非负整数 `cache_count`，返回将删除全部持久化缓存的明确摘要，不得调用 clear endpoint。commit 只能调用正式 SDK `clear_cache()`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、audit 和 legacy `clear_sentiment_cache` replacement。`clear` 必须由各 MCP 写守卫通过统一 write-like 分类器识别，禁止 read/write 守卫各自维护漂移动作词表。
82. Risk Center 风险例外创建固定收口为 `risk_center.create.exception`。Canonical mutation 必须继续由 `CreateRiskExceptionUseCase._require_staff()` 执行真实 staff 权限校验，manifest 的 `required_roles=("staff",)` 只承担协议治理，不得替代服务端授权。Governed schema 必须要求非空 `field_name/allowed_value/reason` 和 timezone-aware ISO 8601 `expires_at`；`field_name` 只能取 canonical `PARAMETER_FIELDS`，可选 `account_id` 必须为正整数。preview 只能调用正式 Risk Center SDK `list_exceptions(account_id=...)`，读取目标范围内现有例外并返回 scoped count、same-field count 与同字段摘要，不得调用 create endpoint。commit 只能调用正式 SDK `create_exception(payload)`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、audit 和 legacy `create_risk_exception` replacement。
83. Risk Center 全局风险底线更新固定收口为 `risk_center.update.floor`。Canonical mutation 必须继续由 `UpdateRiskFloorUseCase` 执行真实 staff 权限校验，并由 Risk Center repository 写入业务审计；manifest role 与 MCP lifecycle audit 不得替代服务端权限和业务审计。Governed schema 必须要求非空 `reason`，只允许名称、比例约束、强制止损和 hard exclusions 等 canonical floor 字段，禁止发布可将全局底线失活的 `is_active`。所有比例必须限制在 `[0, 1]`，名称和 exclusions 必须满足 canonical 长度边界。preview 只能调用正式 Risk Center SDK `get_floor()`，返回当前 floor、字段差异、变更字段摘要和默认 floor 首次持久化提示；无实际差异必须在确认前拒绝。commit 只能调用正式 SDK `update_floor(payload)`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、audit 和 legacy `update_risk_floor` replacement。
84. Risk Center 账户级风险策略 upsert 固定收口为 `risk_center.update.account_policy`。Canonical mutation 必须继续由 `UpsertAccountRiskPolicyUseCase` 执行账户 owner/staff scope，manifest 不得错误声明为 staff-only，也不得替代跨账户 403 校验；repository 必须继续按账户唯一键执行 create/update 并分别写入业务审计。Governed schema 必须要求正整数 `account_id`、非空 `reason` 和至少一个策略字段，比例、风险画像、布尔值及 exclusions 必须满足 canonical 边界。preview 只能通过正式 Risk Center SDK `list_account_policies()` 读取调用方可见策略，明确 operation、当前 policy、字段差异和目标 activation；提供 `template_id` 时必须额外调用 `list_templates()` 验证持久化模板存在。Canonical UseCase 必须在真实 mutation 前再次验证模板存在，禁止只依赖 preview，也禁止 repository 对无效模板 ID 静默置空。已存在策略且无实际差异时必须在确认前拒绝。commit 只能调用正式 SDK `upsert_account_policy(payload)`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、MCP lifecycle audit、canonical business audit 和 legacy `upsert_account_risk_policy` replacement。
85. Risk Center 日报生成固定收口为 `risk_center.generate.daily_report`。Canonical POST 必须继续通过有效策略查询执行账户 owner/staff scope，repository 必须按 `account_id + report_date` 唯一键 upsert，并记录真实 `generated_by`。Governed schema 必须要求正整数 `account_id`、显式 ISO 日期 `report_date` 和非负 `account_equity`；不得继承 legacy 可选日期的“运行时当天”默认，因为 confirmation 可能跨午夜改变写入目标。preview 只能调用正式 Risk Center SDK `check_post_investment(payload)` 生成无持久化风险评估，并使用 `list_daily_reports(account_id, start_date=report_date, end_date=report_date, limit=1)` 判断目标槽位是 create 还是 overwrite；必须披露现有 report、预计状态、违规数和持仓数，不得调用 generate endpoint。commit 只能调用正式 SDK `generate_daily_report(payload)`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、MCP lifecycle audit、canonical generated-by attribution 和 legacy `generate_risk_center_daily_report` replacement。`generate` 必须由 read、confirmation、preview、audit 和 evidence 守卫通过统一 write-like 分类器识别，禁止被误判为 read。
86. Dashboard Auto Advisor 周报持久化固定收口为 `dashboard.create.auto_advisor_weekly_report`。Governed schema 必须要求非空 `account_id`、显式 ISO 日期 `as_of` 和治理层 `idempotency_key`；不得继承 SDK 的可选日期默认，因为 confirmation 期间日期变化会改变持久化目标。preview 只能通过正式 Dashboard SDK 调用 `auto_advisor_weekly_report(account_id, as_of)` 与 `auto_advisor_weekly_report_history(account_id, limit)`，并以目标日期判断 create/overwrite；preview 必须保持 authenticated user scope，禁止调用 POST、保存周报或投资日记、创建通知、写 operation audit 或执行交易。preview 摘要必须披露 report snapshot upsert、investment diary snapshot、Dashboard notification、operation audit 和 no-trade 边界。commit 只能调用正式 SDK `create_auto_advisor_weekly_report(account_id, as_of)`，禁止下传 `preview_only/idempotency_key`。Canonical POST 可按用户、账户和日期持久化或覆盖周报输出，并创建对应通知与审计，因此该能力必须满足 confirmation、required idempotency、MCP lifecycle audit、legacy `create_auto_advisor_weekly_report` replacement、focused SDK/API contract 与 core registry create/overwrite 回归。
87. 统一账户创建固定收口为 `account.create.unified_account`。该能力与 `trading.create.simulated_account` 属于不同业务语义，不得因底层复用同一账户模型而合并：前者通过 `/api/account/accounts/` 和正式 Account SDK 创建 authenticated owner 的 real/simulated 统一账户，后者只创建模拟交易账户并保留模拟交易专用契约。Governed schema 必须要求非空且不超过 canonical 长度的 `account_name`、显式 `account_type=real|simulated`、满足 canonical 最小值的 `initial_capital`，并允许 serializer 与 SDK 共同支持的 `max_position_pct/stop_loss_pct/commission_rate/slippage_rate`。preview 只能调用正式 Account SDK `list_accounts(account_type, active_only=False)` 检查当前用户同名账户，不得调用 POST；同一 owner 同名必须在确认前失败，不同 owner 同名不得互相阻塞。Canonical UseCase 必须在真实 mutation 前重复 owner-scoped 名称校验，repository 禁止继续使用跨用户全局 `.get(account_name=...)`。real 账户默认关闭 auto trading，simulated 账户默认启用，preview 必须披露该状态、账户记录创建和 no-trade 边界。commit 只能调用正式 Account SDK `create_account()`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、MCP lifecycle audit、legacy `create_account` replacement、focused canonical API owner-scope contract 与 registry/catalog regression。
88. Rotation 全局资产主数据创建固定收口为 `rotation.create.asset`。`AssetClassViewSet` 的 list/detail/with-prices/export 保持 authenticated read，但 create/update/partial update/delete/import-defaults 必须由 canonical API 使用 `IsAdminUser` 执行真实 staff 权限，manifest 的 `required_roles=("staff",)` 不得替代服务端授权。Governed schema 只能发布 `AssetClassSerializer` 接受的 `code/name/category/description/underlying_index/currency/is_active`，并在 preview 前执行与模型一致的长度、类别和布尔边界校验。preview 只能通过正式 Rotation SDK `get_asset(code)` 精确读取全局代码，不得调用 create、导入默认资产、读取价格、生成信号或写入 Rotation 记录；active 或 inactive 重码都必须在确认前失败，禁止把恢复停用资产伪装成 create。commit 只能调用正式 SDK `create_asset(payload)`，禁止下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、staff role、MCP lifecycle audit、legacy `create_rotation_asset` replacement、focused canonical API 权限/创建合同与 registry/catalog regression。update、delete 和 import-defaults 必须继续作为独立 write 候选治理，不得复用 create 的 preview 或确认 token。
89. Rotation 全局资产主数据更新固定收口为 `rotation.update.asset`。Governed schema 必须要求 `asset_code`，只允许可选 `name/category/description/underlying_index/currency/is_active` 字段，不发布 legacy 任意 payload、`partial` transport 开关或 code 主键修改。preview 必须通过正式 Rotation SDK `get_asset(asset_code)` 精确读取当前全局记录，按规范化目标值计算 changed fields；空更新和无实际变化必须在确认前拒绝。preview 必须披露当前/目标 active 状态以及是否会停用或恢复资产，但不得读取价格、生成信号、导入默认资产或写入记录。commit 固定调用正式 SDK `update_asset(asset_code, updates, partial=True)`，禁止下传 `preview_only/idempotency_key`，并满足 canonical `IsAdminUser`、manifest staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `update_rotation_asset` replacement、focused PATCH/reactivation API contract 与 registry/catalog regression。delete 和 import-defaults 继续独立治理，不得复用 update 的确认 token 或差异预览。
90. Rotation 全局资产主数据删除固定收口为 `rotation.delete.asset`，语义严格限定为软删除。Governed schema 只能要求 `asset_code` 和治理层 `idempotency_key`，不得发布 `hard`、物理删除或任意 query 参数。preview 必须通过正式 Rotation SDK `get_asset(asset_code)` 精确读取当前记录，只有 active 资产可进入确认态；inactive 资产必须在确认前拒绝。摘要必须披露 active-to-inactive、记录仍保留、不会物理删除、不会读取价格、不会生成信号和不会执行交易。commit 只能调用正式 SDK `delete_asset(asset_code)` 的默认软删除路径，禁止下传 `preview_only/idempotency_key`，并满足 canonical `IsAdminUser`、manifest staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `delete_rotation_asset` replacement、focused soft-delete API contract 与 registry/catalog regression。Canonical staff-only `?hard=true` 仅保留为内部管理接口，不得经本 capability 暴露；import-defaults 继续独立治理。
91. Rotation 服务端默认资产导入固定收口为 `rotation.import.default_assets`。默认资产定义只能读取 `apps/rotation/infrastructure/default_assets.py` 的服务端清单，MCP manifest、handler、preview 和 Agent 输入不得复制、覆盖或接受另一份默认资产列表。Canonical `GET /api/rotation/assets/import-defaults-preview/` 与 `POST /api/rotation/assets/import-defaults/` 必须同时使用 `IsAdminUser`；preview GET 通过 Application facade 调用 repository 的纯读分类逻辑，逐项返回 `created/reactivated/updated/unchanged`、真实 changed fields 和目标记录，且不得创建、恢复或更新任何资产。Governed preview 只能调用正式 Rotation SDK `preview_default_asset_import()`，必须校验非负分类计数和 items 数组，不得通过逐项 create/update 模拟预览。确认后 commit 只能调用正式 SDK `import_default_assets()`，不得下传默认清单、`preview_only` 或 `idempotency_key`。实际导入结果必须保留 `existing` 兼容字段，同时明确返回 `updated` 与 `unchanged`，并与 preview 分类一致。该能力必须满足 staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `import_default_rotation_assets` replacement、focused API 无写预览/权限/分类合同、SDK endpoint contract 与 registry/catalog regression；导入只维护全局 Rotation 资产主数据，不读取价格、不生成信号且不执行交易。
92. Account 持仓创建或加仓固定收口为 `account.create.position`。该能力是 authenticated owner 的统一账本写入，不是券商委托或外部成交接口；canonical `POST /api/account/positions/` 必须继续通过 portfolio owner scope 拒绝 observer 和跨用户 mutation。Governed schema 只发布正整数 `portfolio_id`、非空且不超过模型边界的 `asset_code`、有限正数 `quantity/price` 与治理层 `idempotency_key`，不发布 `source/category/currency/asset_class/region/cross_border` 等可绕过任务语义的任意字段。preview 只能调用正式 Account SDK `get_positions(portfolio_id, asset_code)`，不得调用 POST；必须区分 create/increase，计算现有数量、增加数量、结果数量、按现有成本与本次价格加权后的平均成本及执行价下市值，并披露真实 mutation 会合并统一账本持仓和记录 buy ledger entry，但不会发送外部 broker order。确认后 commit 只能调用正式 SDK `create_position(portfolio_id, asset_code, quantity, price)`，不得调用 raw tool 或下传 `preview_only/idempotency_key`。实际 canonical service 必须保持同账户同资产合并、买入流水记录和 legacy projection 同步；该能力必须满足 confirmation、required idempotency、MCP lifecycle audit、legacy `create_position` replacement、SDK GET/POST endpoint contract、owner/observer API 权限合同、API 加仓合并/买入流水合同与 registry/catalog regression。
93. 同一导入任务的 CSV/JSON 仅属于 transport alias，不得按文件格式拆成重复 capability。`account.import.positions` 必须同时替代 `import_positions_json` 与 `import_positions_csv`，`account.import.transactions` 必须同时替代 `import_transactions_json` 与 `import_transactions_csv`，`account.import.capital_flows` 必须同时替代 `import_capital_flows_json` 与 `import_capital_flows_csv`；统一 governed schema 只接收已解析的结构化 rows，CSV legacy tool 只提供迁移提示，不得把 `csv_text` 暴露为第二套核心任务契约。只有当 raw CSV 工具在解析后直接委托同一 JSON importer，并保持相同 `mode/dry_run`、validation、preview 与 commit 路径时，才允许共享 replacement。Broker trades 导入不满足该条件：它会执行专用成交去重并同步交易、持仓和推荐匹配，必须独立审计和治理，不得并入普通 transaction import。Catalog regression 必须证明每个 JSON/CSV legacy alias 的 `replacement_capability_key` 和 `semantic_key` 都指向同一 governed capability，且 legacy 默认不对 Terminal 启用。
94. Broker 成交导入固定收口为 `account.import.broker_trades`，不得并入普通 `account.import.transactions`。Governed schema 只发布结构化 `trades`，每行固定为 `traded_at/action/asset_code/shares/price` 必填及费用、外部成交号、备注可选字段；CSV 与 JSON 只作为 legacy transport alias，`preview_broker_trades_csv`、`import_broker_trades_csv`、`preview_broker_trades_json`、`import_broker_trades_json` 必须共同 replacement 到该能力，不得形成第二套 `csv_text` capability。正式 Account SDK 必须负责将结构化 rows 序列化后调用 canonical multipart preview/import endpoint。Canonical preview 必须保持 authenticated owner scope，只解析、规范化并查询 `broker_trade_key` 是否存在，不得创建账户映射、导入批次、交易、持仓、统一成交或 recommendation execution link；observer 和跨用户调用必须明确返回 403。Preview 摘要必须披露确认后可能创建 portfolio 到 real-account 的 ledger mapping、写入或更新 import batch、按有效非重复行更新统一持仓和 legacy projection、记录 Account transaction 与 unified buy/sell trade、匹配推荐并写 execution link，以及逐行失败可能造成部分成功；同时明确不会发送外部券商委托。Commit 只能调用正式 SDK `import_broker_trades()`，不得调用 raw tool 或下传 `preview_only/idempotency_key`。`broker_trade_key` 和数据库唯一约束只负责成交级重复抑制，不能替代 MCP confirmation 生命周期、参数冲突检测和 import-batch 重放治理，因此 capability 仍必须要求独立 `idempotency_key`、MCP lifecycle audit 和 high-risk confirmation。
95. Beta Gate 配置创建固定收口为 `beta_gate.create.config`。Canonical config list/detail 必须保持 authenticated read，create 与 rollback mutation 必须由服务端 `IsAdminUser` 执行真实 staff 授权，manifest role 不得替代服务端权限。Governed create schema 只允许可选非空 `config_id`、`risk_profile`、`allowed_regimes`、`min_confidence`、`max_policy_level`、`veto_on_p3`、`max_total_position`、`max_single_position` 与治理层 `idempotency_key`；枚举、数值边界和单仓不高于总仓规则必须在 preview 前与 canonical serializer 对齐。Preview 只能调用正式 Beta Gate SDK `list_configs(active_only=False)`，读取完整持久化目录并拒绝 active 或 inactive 重复 config ID；必须返回预期全局下一版本、同风险档位当前 active 配置、将创建并激活新配置、将停用旧 active 配置、不会改变既有决策和不会执行交易。Commit 只能调用正式 SDK `create_config(payload)`，不得下传 `preview_only/idempotency_key`；repository 必须在事务内分配全局递增版本并保持同风险档位单一 active。该能力必须满足 staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `create_beta_gate_config` replacement、SDK endpoint、focused API 权限/版本/纯读目录合同及 registry/catalog regression。Rollback 是激活既有配置的独立 mutation，必须另行治理，禁止与 create 共用 capability、preview 或 confirmation token。
96. Beta Gate 历史配置回滚固定收口为 `beta_gate.rollback.config`，不得并入 create。Canonical route 的路径 `config_id` 是唯一目标标识，不得允许请求体 version 覆盖路径语义；服务端必须使用 `IsAdminUser`，并在 mutation 前拒绝不存在、已 active 或已过期目标。成功 rollback 只能激活既有记录、停用同风险档位当前 active 并更新目标 `effective_date`；不得创建新配置或新版本，不得改变其他风险档位 active 状态、既有 Gate decisions 或交易状态。Config detail 必须返回 preview 所需的 `config_id/risk_profile/version/is_active/is_expired/effective_date/expires_at`。Governed preview 只能通过正式 Beta Gate SDK `get_config(config_id)` 精确读取目标，并通过默认 active `list_configs()` 找出同风险档位当前配置；必须披露目标与当前版本、active 切换、无新版本、无既有决策修改和 no-trade 边界。Commit 只能调用正式 SDK `rollback_config(config_id)`，不得下传 `preview_only/idempotency_key`。该能力必须满足 staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `rollback_beta_gate_config` replacement、SDK endpoint、focused API 精确目标/过期拒绝/同档位切换合同及 registry/catalog regression。
97. Beta Gate 持久化配置版本对比固定收口为 `beta_gate.compute.config_comparison`。Canonical endpoint 必须使用 authenticated GET；正式 SDK 不得继续向只实现 GET 的 route 发送 POST，并应把 legacy `from/to`、`version_a/version_b` 归一化为 `version1/version2` query。Governed schema 必须同时要求两个非空、有界的配置标识，只允许比较两条明确持久化配置，不发布无参数 recent-version catalog 分支。Canonical Application service 只能读取配置、解析 constraints 并执行内存字段比较，不得保存配置、切换 active、写 Gate decisions、发布事件或触发其他工作流。Controlled fallback 只能调用正式 SDK `version_compare()`，并固定返回 `config1/config2/differences`。该能力必须满足 authenticated API、focused 配置表零变化合同、SDK method/path/params contract、legacy `compare_beta_gate_version` replacement、core-only capability-call、catalog metadata 与 read-evidence regression。`test_beta_gate` 属于另一项批量评估语义，必须独立证明输入契约、默认配置降级和事件/持久化边界，不得借版本对比的纯读证据迁移。
98. Beta Gate 批量资产评估固定收口为 `beta_gate.compute.batch_evaluation`。Canonical `/api/beta-gate/test/` 必须使用 `IsAuthenticated` 和严格 serializer，只发布有界去重资产代码、非空资产类别、四象限 Regime、有限置信度、`P0-P3` policy level 与 canonical 小写风险档位；未知字段必须拒绝。旧 test API 未实际传入的 `current_portfolio_value` 不得进入 governed schema，因为当前领域方法缺少新仓位和总资产输入，无法形成完整仓位计算语义。配置选择必须调用 repository 的 `get_by_risk_profile()`，不得取第一条 active 配置；无持久化配置时只能返回请求风险档位对应的稳定内存默认配置，不得创建配置行。输出固定为 `config/query/results/summary`，其中 config 必须披露实际 `config_id/risk_profile/version`。Canonical 执行只能在内存中构造 Gate decisions；Interface 不得注入 event bus，不得调用 decision repository、任务或交易链。Focused API contract 必须同时证明配置、决策和持久化事件零变化。Controlled fallback 只能规范化同一合同并调用正式 SDK `test_gate(payload)`；legacy `test_beta_gate` 必须 replacement 到该 capability，并具备 SDK、core-only、catalog 与 read-evidence 回归。
99. Data Center 持久化资金流读取固定收口为 `data_center.read.capital_flows`。读取契约只允许 `asset_code`、可选 ISO 日期 `start/end` 和有界 `limit`；legacy/SDK 原有 `period` 只属于 provider 同步语义，不得进入 persisted read schema，未知参数和反向日期区间必须返回 400。Canonical GET 必须使用 `IsAuthenticated` 和严格 serializer，响应固定为 `asset_code/query/total/data`。Repository 可以解析资产别名，但必须按 `flow_date` 倒序并在数据库查询层执行 limit；Application UseCase 不得触发 provider fetch、sync、upsert、缓存回写、任务或审计写入。Focused API contract 必须覆盖缺失资产、非法日期、反向区间、legacy `period` 拒绝、limit、alias 解析以及 `CapitalFlowFactModel` 记录和 `fetched_at` 零变化。正式 SDK 与 legacy compatibility tool 必须统一使用 `start/end/limit`；controlled fallback 只能调用正式 SDK `get_capital_flows()`。Legacy `data_center_get_capital_flows` 必须 replacement 到该 capability，并具备 core-only、catalog、manifest 与 read-evidence 回归。
100. Alpha Trigger 绩效聚合读取固定收口为 `alpha_trigger.read.performance`。Governed 输入只允许 `days` 和可选 `trigger_id`，其中 `days` 必须限制在 `1..365`，`trigger_id` 必须非空且不超过模型边界；不得继续发布任意 `payload` 或旧式 `window_days`。Canonical GET 必须使用 `IsAuthenticated` 和严格 query serializer，未知参数必须返回 400，响应固定为 `success/data/summary`，summary 必须包含实际 `days`、`trigger_id` 和 `total_triggers`。Application 查询链只能读取 active triggers 与关联 candidates 后执行内存聚合，不得创建或更新 trigger/candidate、发布事件、触发任务、调用 provider 或执行交易。Focused API contract 必须证明 `AlphaTriggerModel` 与 `AlphaCandidateModel` 的记录数、创建时间和更新时间零变化。正式 SDK、legacy compatibility tool 与 controlled fallback 必须统一使用显式 `days/trigger_id`，fallback 只能调用正式 SDK `performance()`。Legacy `alpha_trigger_performance` 必须 replacement 到该 capability，并具备 manifest、core-only、catalog、SDK、raw compatibility 与 read-evidence 回归。
101. 通用领域事件发布固定收口为 `events.publish.event`，必须按高风险跨模块 workflow 治理。Canonical `POST /api/events/publish/` 必须使用 `IsAdminUser` 和严格 serializer，拒绝未知字段并限制事件、关联和因果标识长度；普通认证用户不得直接构造可触发系统订阅者的领域事件。Application 和 Celery 发布链必须先确认 `StoredEventModel` 持久化成功，再同步通知 event bus；持久化失败或重复 `event_id` 时不得调用任何订阅者。Governed schema 必须要求受支持的明确 `event_type`、对象 `payload`、带时区的显式 `occurred_at` 和治理层 `idempotency_key`，不得发布运行时当前时间默认或独立 `event_id`。Internal-handler preview 只能执行本地规范化，必须披露事件标识、payload/metadata key 摘要、持久化写入、同步通知以及 subscriber-defined 跨模块副作用，不得调用 SDK、POST、数据库或 event bus。Commit 只能调用正式 Events SDK `publish_event()`，并把 `idempotency_key` 固定映射为 canonical `event_id`，使 dispatcher replay 和数据库唯一约束共同阻止重复副作用；不得下传 `preview_only`。该能力必须满足 staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `publish_event` replacement、focused API 持久化/重复/权限/未知字段合同、SDK endpoint、core registry preview/commit/replay 和 catalog metadata 回归。
102. `replay_events` 继续冻结，不得仅因 raw MCP、正式 SDK 和 canonical route 同时存在就迁移。当前 `EventReplayView` 强制构造 `target_handler=None`，而 `EventReplayHandler.replay_to()` 需要实际 subscriber 并调用 `can_handle()/handle()`；现状会逐条捕获空订阅者异常并可能返回成功 envelope 和零重放数，不能证明真实重放语义。解冻前必须先确定允许重放的持久化 subscriber/handler 身份、服务端 staff 权限、目标白名单、纯读 preview、逐事件副作用摘要、失败与部分成功合同、required idempotency、audit 和 focused handler invocation evidence；禁止把当前 no-op/吞异常路径包装成 governed workflow。
101. Equity 持久化估值分析固定收口为 `equity.read.valuation_analysis`。Governed 输入只允许必填 `stock_code` 和 `30..1260` 的可选 `lookback_days`；旧 SDK/raw 的 `as_of_date` 与 canonical API 实际语义不一致，必须移除，不得作为兼容别名继续发布。Canonical GET 必须显式使用 `IsAuthenticated`，通过严格 serializer 拒绝未知 query，并固定返回股票身份、PE/PB 当前值与分位、低估判断、latest valuation、financial context 和可选 error。`AnalyzeValuationUseCase` 必须始终以 `hydrate=False` 读取持久化估值、财务和价格数据，cache miss 不得调用 provider、Data Center on-demand sync、AssetMaster backfill 或 legacy mirror 写入。Focused API contract 必须证明 Data Center asset/alias/price/valuation/financial facts 与 Equity stock/price/valuation/financial mirrors 的记录和时间戳零变化，并以 fail-fast fake 证明所有 on-demand ensure 方法未调用。正式 SDK、legacy compatibility tool 与 controlled fallback 必须统一使用 `lookback_days`，fallback 只能调用正式 SDK `get_valuation()`。Legacy `get_stock_valuation` 必须 replacement 到该 capability，并具备 manifest、core-only、catalog、SDK、raw compatibility 与 read-evidence 回归。
102. Sector 持久化轮动排名固定收口为 `sector.read.rotation_ranking`。Governed 输入只允许可选 `regime`、`5..120` 的 `lookback_days`、`SW1|SW2|SW3` 的 `level` 和 `1..50` 的 `top_n`；canonical GET 必须显式使用 `IsAuthenticated` 和严格 query serializer，未知参数必须返回 400。未提供 `regime` 时只能读取最新持久化 Regime 快照，不得触发实时 Regime 计算、宏观 provider 或快照保存。Sector GET 与 POST analyze 都不得因本地数据缺失调用 `UpdateSectorDataUseCase`；数据初始化和 provider sync 只能通过 staff-only 显式入口执行。沪深 300 基准收益读取必须固定 `hydrate=False`，本地不足时只能使用无基准降级值。Focused API contract 必须证明 Sector 相关记录和时间戳零变化，并以 fail-fast patch 证明 provider sync 与远端 hydration 未调用。正式 SDK 统一发布 `get_rotation_ranking()`；legacy list/recommendation/hot-sector aliases 共同 replacement 到该 capability。`get_sector_score` 已通过独立 strict canonical action 收口为 `sector.read.score`，只发布 `sector_name` 并复用相同 persisted-only ranking boundary；`analyze_sector` 与 detail/performance 派生语义仍不得借排名或 score 证据迁移。
103. Fund 持久化筛选固定收口为 `fund.compute.screen`，并要求既有 `fund.read.ranking` 使用同一 persisted-only 数据边界。Canonical screen POST 与 ranking GET 必须显式使用 `IsAuthenticated` 和严格 serializer，只接受四象限 Regime、有界返回数量及 screen 的可选类型、风格和非负规模；未知参数必须返回 400。未提供 Regime 时只能读取最新持久化 Regime 快照，不得调用实时 Regime 计算。Application 只能调用 `get_persisted_funds_with_performance()` 读取 active `FundInfoModel`、已有 `FundPerformanceModel` 和最新 `FundSectorAllocationModel`，再执行纯 Domain 筛选或排名；不得调用 `ensure_fund_universe_seeded()`、`get_or_build_fund_performance()`、`build_and_store_fund_performance()`、Tushare sync、NAV sync、任务或其他写入路径。缺少基金主数据或业绩快照时只能返回空结果，缺少 persisted Regime 且调用方未显式提供时必须返回明确错误。Focused API contract 必须证明 Fund 主数据、业绩、行业配置、偏好和 Regime 快照记录及时间戳零变化，并以 fail-fast patch 证明播种、业绩持久化和 provider sync 未调用。正式 SDK `screen_funds()`、legacy raw `screen_funds` 与 controlled fallback 必须统一同一参数合同；fallback 只能调用正式 SDK。`get_fund_performance` 仍会保存计算快照，继续按第 65 条冻结为 workflow/write；`list_funds`、recommendation、hot-fund、score 和其他 analysis 不得借 screen/ranking 证据迁移。
104. Sector 成分股票兼容工具 `get_sector_stocks` 不得创建重复 Sector capability。代码事实表明该 SDK 方法只委托 Equity `list_stocks(sector=sector_name, limit=limit)`，因此其 canonical owner 固定为 `equity.read.pool_catalog`，并与 `list_stocks` 共享 semantic key、controlled fallback、纯读证据和 catalog replacement。Governed schema 继续只发布真实生效的 `sector/min_score/limit`；legacy `order_by=market_cap|change` 在当前 canonical API 中没有实现，不得作为伪参数进入新契约，也不得在 MCP fallback 中本地猜测排序。该 alias 收口不新增 manifest、raw tool 或顶层工具，只增加 replacement link；`sector.read.score` 保持独立 canonical owner，Sector detail/analyze/performance 仍需独立语义证据。
105. Account legacy Portfolio 读取固定收口为 `account.read.portfolio_catalog`、`account.read.portfolio_detail`、`account.read.positions`、`account.read.position_records`、`account.read.transaction_records` 与 `account.read.capital_flow_records`。Raw tools 必须调用正式 Account SDK，不得继续直接使用通用 HTTP client 或各自复制分页循环。所有 governed position read 必须调用 canonical `/api/account/positions/read-only/`，该 endpoint 只能读取 persisted legacy projection，不得调用 `_ensure_portfolio_ledger_synced()`、创建 unified real account、同步 unified position、写 `LedgerMigrationMapModel` 或触发交易。`account.read.positions` 只返回归一化摘要；`account.read.position_records` 保留 record identity、分类、来源和 lifecycle 字段，两者不得因资源相同而错误合并。`export_positions_json`、`export_transactions_json`、`export_capital_flows_json` 只是对应 records 的对象包装，必须作为 legacy aliases 指向现有 capability，不得新增 export capability；CSV 文本导出属于 local formatting compatibility，跨 portfolio/statistics/records 的 bundle 属于 composite，均不得借单项 read 证据直接提升。Portfolio catalog/detail 允许 owner 和有效 observer grant，transaction/capital-flow 继续按 canonical owner scope；focused API contract 必须证明读取前后统一账户、统一持仓和 ledger mapping 零变化，并配套正式 SDK endpoint、core-only fallback、catalog replacement 与 read-evidence 回归。
106. Policy RSS 同步抓取固定收口为 `policy.start.rss_fetch`，属于 staff-only 高风险 workflow，不得因 transport 为同步 POST 而当作普通工具调用。Canonical `/api/policy/workbench/fetch/` 必须使用 `IsAdminUser`，严格拒绝未知字段，并只接受可选正整数 `source_id` 与布尔 `force_refetch`；指定停用源必须在访问网络、AI 或写入前失败。Preview 只能通过正式 Policy SDK 读取 persisted RSS source catalog/detail，展示 single/all 目标、active 状态、强制重抓标记、外部网络与 AI 风险、raw policy log/event/fetch log/source status 写入、可能告警和逐源/逐条部分成功语义，不得抓取 RSS、调用 AI、写日志或事件、更新源状态、发送告警或提交任务。Commit 只能调用正式 `PolicyModule.trigger_fetch()` 的同步 canonical endpoint，不得下传 `preview_only` 或 `idempotency_key`；能力必须满足 staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `trigger_rss_fetch` replacement、focused API/SDK/registry/catalog 与 write guards 证据。
107. MCP 整改引起生产 Python 文件超过 large-file ratchet 时，必须按 owner 和职责拆出 repository、runtime gateway、catalog projection 或 metadata bundle，不得提高 `allowed_large_python_files` 额度掩盖增长。本批已将 Account read projection、AI Capability MCP runtime/catalog projection 与 Terminal AI quota metadata 拆入独立模块，并清除相关增长违规；实际阈值和检查结果仍只以 `governance/governance_baseline.json` 与一致性脚本为准。
108. Audit 阈值验证固定收口为 `audit.start.threshold_validation`，属于 staff-only 全局写 workflow。Governed 输入必须显式要求 `start_date/end_date`，拒绝未知字段、反向日期和超长区间，不得继承 raw tool 的动态日期默认或任意 payload。Canonical preview 固定为 `POST /api/audit/run-validation/preview/`，只能通过 Application service 读取 active threshold 配置并返回日期范围、指标代码、目标数量以及 `validation_summary/indicator_performance_reports` 写入说明；不得调用 `ValidateThresholdsUseCase`、读取宏观/Regime 历史、执行指标分析或写 Audit 业务表。Canonical commit `POST /api/audit/run-validation/` 必须使用 `IsAdminUser` 与同一严格 serializer，确认后才同步执行验证，创建并更新 validation summary，并按成功指标持久化 performance reports；逐指标无数据或分析失败可能形成部分结果。Internal handler preview/commit 必须分别只调用正式 Audit SDK 的 `preview_validation()` 与 `run_validation()`，禁止下传 `preview_only/idempotency_key`。该能力必须满足 staff role、confirmation、required idempotency、MCP lifecycle audit、legacy `run_audit_validation` replacement、focused API 零写预览/权限/输入合同、SDK endpoint、registry preview/commit/replay、catalog metadata 和全部 write guards。Legacy `validate_all_indicators` 是带动态日期默认的重复入口，不得创建第二个 capability；它必须作为同一 capability 的 alias，旧 `/api/audit/validate-all-indicators/` route 也必须复用 `RunValidationView`，确保 legacy-on 模式不能绕过 staff 权限和严格日期合同。
109. Audit 指标阈值更新固定收口为 `audit.update.threshold_levels`，属于 staff-only 高风险配置写入。Canonical 输入只允许 `indicator_code/level_low/level_high`，必须拒绝未知字段、空指标、非有限数值及 `level_low >= level_high`。`POST /api/audit/update-threshold/preview/` 只能精确读取 active threshold config，返回 current、target、changed fields 与目标表，不得更新配置；不存在和 no-op 必须在确认前失败。Commit `POST /api/audit/update-threshold/` 必须复用相同严格合同和 `IsAdminUser`，只更新 `level_low/level_high`。Internal handler preview/commit 必须分别只调用正式 Audit SDK 的 `preview_threshold_update()` 与 `update_threshold()`，不得向 canonical API 下传 `preview_only/idempotency_key`。能力必须声明 staff role、confirmation、required idempotency、`audit:threshold_levels` lifecycle audit 和 legacy `update_audit_threshold` replacement，并具备 API、SDK、registry replay、catalog 与全部 write guards 证据。为落实大文件治理，Audit validation/update handlers 与 manifests 必须保留在 owner 分片，新增测试写入 focused shard；write-evidence guard 必须扫描受控 internal-handler 和 focused-test 目录，不得要求实现重新堆回 `server.py` 或单一巨型测试文件。
110. Audit 归因报告生成固定收口为 `audit.create.attribution_report`，属于 staff-only 高风险同步 workflow。Canonical 输入只允许正整数 `backtest_id`，必须严格拒绝未知字段、缺失或非法 ID，并在任何行情访问、分析和写入前拒绝不存在或未完成的回测。`POST /api/audit/reports/generate/preview/` 只能读取精确回测元数据与既有报告数量，必须披露历史资产价格外部读取、report/loss-analysis/experience-summary 写入、允许同回测多报告及子记录失败可能造成部分写入；不得初始化价格适配器、访问 provider、执行归因或写 Audit 业务表。Commit `POST /api/audit/reports/generate/` 必须复用 `IsAdminUser` 与同一严格合同，确认后才调用正式 Audit SDK 同步生成报告。Internal handler 不得向 canonical API 下传 `preview_only/idempotency_key`。能力必须满足 staff role、confirmation、required idempotency、`audit:attribution_report` lifecycle audit、legacy `generate_audit_report` replacement、API 零写预览/权限/完成状态合同、SDK endpoint、registry preview/commit/replay、catalog metadata 与全部 write guards。视图、handler、manifest 和 focused tests 必须继续保留在 Audit owner 分片，不得回填总视图、总 handler 或巨型 registry test。
111. 配置中心聚合摘要固定收口为 `config_center.read.snapshot`，属于 staff-only medium-risk read。Canonical `GET /api/system/config-center/` 必须继续使用 `IsAdminUser`，只返回脱敏 section/status/summary 元数据，不得输出 Token、API key、密码或密钥正文。所有 summary repository 在缺少 singleton 配置时必须返回 unsaved in-memory defaults，不得通过 `get_or_create()`、`load()` 或修复性 save 在读取中创建或更新 system settings、provider settings 或其他配置；focused API contract 必须捕获整次请求 SQL 并证明无 INSERT/UPDATE/DELETE。Qlib summary 必须显式传入 actor 执行权限校验，不得因漏传 actor 静默降级为 attention。Controlled fallback 只能调用正式 Config Center SDK `get_snapshot()`，legacy `get_config_center_snapshot` 必须 replacement 到该 capability，并满足 staff role、`config_center:snapshot/mcp:read` audit tags、SDK、core-only、catalog 与 read-evidence 回归。Read handlers、manifests 和 focused registry/catalog tests 必须按 owner 分片；read-evidence guard 必须扫描受控 shard，不得要求回填 `server.py`、总 registry test 或总 catalog test。`risk_level` 表达敏感度，不等于副作用类型；write confirmation/preview/audit guards 必须依据 capability action/write 语义分类，不能强迫 medium/high read 伪装成 write，也不能通过把敏感 read 降为 low 绕过审计。
112. Raw-tool gap 审计不得把 SDK 本地拼装、动态 fallback 或 raw 硬编码误当 canonical capability。`get_alpha_stock_scores` 当前进入 Qlib/Cache/Simple/ETF 混合 provider 链，可能访问远端行情、任务与运行时指标，在拆分 persisted snapshot 与 explicit compute workflow 前冻结；`get_stock_detail` 只是 SDK 拉取大 pool 后本地扫描，没有精确 detail endpoint；`list_rotation_assets/get_asset_info` 分别调用动态 `with_prices` 与价格/表现 detail，不得 alias 到 persisted asset master；`get_recommended_assets` 仅存在 raw tool 硬编码且没有正式 SDK/API owner。这些入口不得新增 manifest、fallback 或 replacement；解冻前必须补真实 canonical endpoint、参数一致性、权限、无副作用或 workflow 证据，并把业务硬编码迁入数据库配置。历史 `get_sector_score` 缺口已由 `sector.read.score` 的 strict persisted-only owner 链关闭，不再属于本冻结清单。
113. Alpha 批量评分缓存导入固定收口为 `alpha.import.score_cache`，属于 staff-only 高风险持久化写入。Governed 输入必须要求有界非空 `scores`，严格拒绝未知字段、重复股票代码、重复排名、非有限 score/confidence/factor、反向日期和超长批次，并规范化股票代码。Canonical preview 只能精确读取 `user + universe_id + intended_trade_date + provider_source=qlib + model_artifact_hash` 目标，返回 create/update、现有记录摘要及目标表，不得创建、更新或删除 cache row；system scope preview/commit 必须继续由服务端 staff 权限控制。Commit 只能调用正式 Alpha SDK `upload_scores()`，preview 只能调用 `preview_score_upload()`，两条路径均不得接收治理层 `preview_only/idempotency_key`。能力必须满足 confirmation、required idempotency、`alpha:score_cache_import/mcp:write` audit、legacy `upload_alpha_scores` replacement、API 零写 preview、SDK、registry preview/commit/replay、catalog 与全部 write guards。实现必须保留在 Alpha owner handler、manifest、API view 和 focused test 分片，不得回填历史巨型聚合文件。
114. MCP 大文件治理必须覆盖 `sdk/agomtradepro_mcp`，不能只依赖当前 `apps/core/shared` 的 large-file 扫描结果。`server.py` 必须最终退化为 composition root，只保留 server 构造、core/legacy 开关、owner handler registry 装配和启动入口；业务 fallback、preview/commit handler、schema 或 owner 映射必须拆入 owner 模块。`basic_read_capabilities.py` 与 `write_capabilities.py` 必须按 owner/action 拆成独立 manifest shard，loader 只装配受控模块清单；新增能力不得再写入这两个历史聚合文件。巨型 registry、catalog 和 SDK endpoint 测试必须拆成 focused shard，证据守卫必须扫描分片目录，禁止为满足静态字符串扫描把实现堆回总文件。整改不得提高 `allowed_large_python_files`、新增 MCP 专属豁免或利用扫描根目录盲区；阈值、债务清单和完成状态只能写入 `governance/governance_baseline.json` 并由 CI 生成，不得在 Markdown 复制动态行数或文件数。
115. MCP runtime handler registry 必须由显式 owner module tuple 装配并在合并时拒绝重复 executor key，不得使用 filesystem wildcard 自动发现。Owner handler 如需调用 legacy-on tool manager，必须通过 composition root 注入受控 caller，不得反向 import `server.py`；server 必须在 dispatcher 构造前完成注入。Evidence guard 必须递归扫描受控 runtime/internal/read handler roots，并同时识别 owner map 与 server 外部 adapter，禁止继续用“函数文本位于 server.py”作为迁移证据。正式 `sdk/agomtradepro` 与 `sdk/agomtradepro_mcp` 必须和 `apps/core/shared` 使用同一 machine large-file ratchet，测试目录继续由 focused-shard 结构标准约束，不得混入生产文件 allowance。
116. MCP focused tests 的大文件门禁固定覆盖 `sdk/tests/test_mcp`、`sdk/tests/test_sdk` 与 `tests/unit/test_ai_capability`，并复用机器唯一真源中的 Python 文件阈值和 allowance 规则。巨型参数化 case 不得仅移动到另一测试文件；必须按 owner 拆分 case matrix 或提取有界 owner fixture data。共享 fixture/helper 可以进入非 `test_` support 模块，但测试分片必须保持原收集数量、参数化语义和 evidence guard 可见性。超时只表示未验证，不得当作通过；可按 owner 分批运行，但进入合并前必须保留完整收集验证和至少一轮覆盖所有分片的回归证据。
117. Hedge 单对有效性计算固定收口为 `hedge.compute.effectiveness`。Governed 输入只允许非空有界 `pair_name`；正式 SDK 必须先从 authenticated canonical pair catalog 精确解析 pair ID，再调用 canonical effectiveness action，不得让 MCP fallback 直接访问 ORM 或内部 service。Canonical action 只能读取持久化 hedge pair 和既有价格事实/缓存并执行内存相关性、Beta、hedge ratio、rating 与 recommendation 计算，必须传 `cache_price_reads=False`，不得写价格缓存、CorrelationHistory、HedgePortfolioSnapshot、HedgeAlert、HedgePerformance 或触发 monitoring/update workflow。输出统一增加由 effectiveness 阈值派生的 `is_effective`，legacy `check_hedge_effectiveness` 与 `is_my_hedge_still_working` 必须共享该 capability，不得保留两套语义。能力必须具备 authenticated API 零写合同、formal SDK pair/action contract、core-only `agom_capability_call`、catalog replacement、audit tags 与 read-evidence 回归。
118. Dashboard 权益曲线固定收口为 `dashboard.read.equity_curve`，只替代 raw `get_dashboard_equity_curve_v1`。该能力不接受 legacy 未声明的筛选参数，只通过正式 Dashboard SDK 调用 authenticated canonical `GET /api/dashboard/v1/equity-curve/`，返回 `range/has_history/series` 稳定 envelope。Canonical endpoint 不得增加 cache decorator、行情刷新、ledger 同步、策略执行或任何数据库写入；focused API 合同必须以捕获 SQL 的方式拒绝 INSERT/UPDATE/DELETE 等 mutation。`summary/regime/signal` 等带缓存或尚未完成独立纯读证明的 Dashboard v1 raw tools 不得借本条规则顺带迁移；历史 HTMX positions/SDK JSON 契约分裂已按规则 122 解决。能力必须具备 formal SDK endpoint、真实 owner fallback、core-only `agom_capability_call`、catalog replacement 与 read-evidence 回归。
119. Regime 与 Pulse 联合行动建议固定收口为 `regime.read.action_recommendation`，只替代 raw `get_action_recommendation`，不得并入 Navigator 或 Pulse snapshot。`GetActionRecommendationUseCase` 必须保留显式 `refresh_pulse_if_stale` 与 `persist_result` 控制；authenticated canonical `GET /api/regime/action/` 必须固定传 `False/False`，只读取持久化输入并执行内存映射，不得刷新 Pulse、写 `ActionRecommendationLog` 或触发其他同步。需要刷新或持久化建议时必须另建显式 workflow/write 合同，不能复用 GET。Governed 输出必须保留 `must_not_use_for_decision/blocked_reason/blocked_code/pulse_is_reliable/stale_indicator_codes/contract`，Agent 在阻断合同为真时不得生成可执行配置。能力必须具备 API 参数与 SQL 零写证明、use-case no-refresh/no-persist 测试、正式 SDK endpoint、owner fallback、core-only `agom_capability_call`、catalog replacement、decision-read audit tags 与 read-evidence 回归。
120. Backtest 持久化权益曲线固定收口为 `backtest.read.equity_curve`，只替代 raw `get_backtest_equity_curve`。Canonical `GET /api/backtest/backtests/{id}/equity-curve/` 在历史记录 owner scope 完成前必须保持 `IsAdminUser`，不得向普通用户泄露全局或 `user=NULL` 的系统回测；manifest 同步声明 staff role 与 medium risk。Application read service 只能读取既有 `BacktestResultModel.equity_curve` JSON 并返回 `backtest_id/status/curve/point_count`，不得重跑回测、加载行情、计算指标、生成审计报告、刷新缓存或写数据库。正式 SDK 必须提供 canonical envelope 方法，旧 list-only 方法只能作为兼容包装；owner fallback 必须调用 envelope 方法并验证 curve array。能力必须具备 API staff/403 与 SQL 零写合同、SDK endpoint、真实 core-only `agom_capability_call`、catalog replacement、research-read audit tags 与 read-evidence 回归。Backtest detail/list 的历史 owner scope 债务不得因本能力完成而视为解决。
121. Dashboard 用户资产配置固定收口为 `dashboard.read.asset_allocation`，只替代 raw `get_dashboard_allocation`。Governed 输入保持零参数，表示聚合 authenticated user 的全部可访问模拟账户，不发布 canonical endpoint 可选但 legacy 未声明的 `account_id`。Canonical `GET /api/dashboard/allocation/` 只能通过 Application/Repository 读取当前用户账户及持仓，并在内存中按 asset class 汇总；不得创建默认账户、同步 legacy/unified ledger、刷新价格、写 allocation snapshot 或缓存。Owner fallback 只调用正式 Dashboard SDK `allocation()`，解包 `success + data` 后返回 `allocation/total_market_value`，并拒绝 boolean 或非数值分配项。能力必须具备 API user-scope 参数与 SQL 零写证明、SDK endpoint、真实 core-only `agom_capability_call`、catalog replacement 与 read-evidence 回归。用户持仓目录必须按规则 122 保持独立 capability，不得把 allocation 与逐持仓明细合并成不稳定复合输出。
122. Dashboard 用户持仓目录固定收口为 `dashboard.read.position_catalog`，只替代 raw `get_dashboard_positions`。原 `/api/dashboard/positions/` 必须继续服务 HTMX 页面，不得为 SDK 改成 JSON；新增 authenticated canonical `/api/dashboard/positions/data/` 专供 API/SDK，返回 `success + data.positions/total_count`。正式 SDK `positions()` 必须只调用新 JSON route。Governed 输入保持零参数，表示聚合当前用户全部可访问模拟账户；每条 position 应保留 `account_id/account_name` 元数据，不发布 legacy 未声明的 account filter。读取链只能调用 Application/Repository 的 user-scoped persisted position query，不得创建默认账户、同步 ledger、刷新价格、调用 `_ensure_dashboard_positions` 或渲染 HTMX。Owner fallback 必须解包 canonical envelope、验证 positions array，并返回稳定 `positions/total_count`。能力必须具备 API route discovery、user-scope 与 SQL 零写证明、正式 SDK endpoint、真实 core-only `agom_capability_call`、catalog replacement 与 read-evidence 回归。
123. Data Center Provider 连通性测试固定收口为 `data_center.run.provider_connection_test`，属于 staff-only medium-risk workflow/write，不得因名称包含 test 或响应只返回状态而按 read 治理。Canonical `POST /api/data-center/providers/{provider_id}/test/` 会执行真实外部 provider 调用和解析路径，并把 probe 时间、状态、错误及 capability health metrics 写回 provider 配置；普通认证用户必须返回 403。Provider create/detail/update/list 响应不得输出 `api_key/api_secret` 正文，只能返回明确的 credential presence flags；连接探测异常、summary、logs 及持久化 health error 必须在 Application 边界按当前 provider credential 精确替换为 `[REDACTED]`。Governed preview 只能通过正式 Data Center SDK `get_provider(provider_id)` 读取安全的 `id/name/source_type/is_active/priority/has_api_key/has_api_secret`，必须披露外部访问、parser 执行和 provider health metadata 写入，并明确不执行 market fact sync；preview 不得调用 connection-test endpoint、访问 provider 或写 health metadata。Commit 只能调用正式 SDK `test_provider_connection(provider_id)`，不得下传 `preview_only/idempotency_key`，返回 payload 还必须删除 credential-named 字段。能力必须要求正整数 provider ID、staff role、confirmation、required idempotency、`data_center:provider_connection_test/mcp:write` lifecycle audit、legacy `test_data_center_provider_connection` replacement、API persistence/permission/redaction、SDK endpoint、registry preview/commit/replay、catalog metadata 和全部 write guards。实现和测试必须保留在 owner/focused 分片；不得把 workflow 回填 `server.py`、历史总 manifest、历史巨型 test 或继续扩大 `data_center/application/use_cases.py`。
124. Dashboard V1 summary、regime quadrant 与 signal status raw tools 在 strict read projection 拆分前必须冻结。`get_dashboard_summary_v1`、`get_dashboard_regime_quadrant_v1` 与 `get_dashboard_signal_status_v1` 对应 canonical view 当前都调用完整 `GetDashboardDataUseCase.execute()`；该聚合用例会在账户 profile 缺失时创建默认 profile，通过 `get_or_create_default_portfolio()` 创建或修复默认 portfolio，并执行 AI insight 生成。Summary 和 regime view 还使用 `cached_api`，cache miss 后会写 response cache；signal view 即使没有 decorator，也不能借此忽略共享聚合链的数据库和外部 AI 副作用。不得仅删除 cache decorator、mock 掉写路径或用已有用户数据的 happy-path SQL 结果将三条能力认定为 pure read。解冻前必须新增 user-scoped strict read Application projection，只读取已持久化 profile、账户、组合、Regime 和 signal 数据；缺失对象只能返回明确空态，不得创建默认记录；不得调用 AI、外部 provider、cache set、任务、ledger sync 或刷新链。三条 capability 还必须按各自输出语义分别建立正式 SDK、controlled fallback、API SQL 零写及 no-external-call 证据，不得把完整 Dashboard composite 作为一个不稳定 read capability 发布。
125. 正式 SDK route guard 必须同时扫描继承 `BaseModule` 的相对 endpoint 调用和非继承模块的 `self._client.get/post/put/patch/delete` 绝对 API 调用。对分页、跨 owner 等 transport helper，守卫必须从静态 call site 展开真实 endpoint；无法展开的动态 path 必须失败，不得静默跳过。守卫通过只证明 Django route 与 HTTP method 存在，不证明 query 参数被执行、响应 schema 稳定或读链无副作用；每条 MCP 迁移仍须完成 focused contract。SDK 不得把 query string 拼进 endpoint 字符串绕过参数审计；跨 owner 兼容方法应委托正式 owner SDK，例如 Realtime 历史价格委托 Data Center，而不是复制第二条 route。
126. `governance/governance_baseline.json` 必须显式保存 `mcp_governance.legacy_without_replacement_count`，并满足 `replacement_link_count + legacy_without_replacement_count = legacy_capability_count`。`scripts/check_mcp_catalog_dedup.py` 必须从实时 manifest、catalog、unsupported registry、core surface 和 raw tool 文件实测全部 MCP governance 字段并与机器基线逐项比较；Markdown 不得手工维护第二份数值。
127. SDK/API 契约不得用“路由可 resolve”代替运行态调用证据。DRF lookup 必须支持正式资产代码格式；自定义 action 名不得与 ViewSet 内部 `detail` 等实例属性冲突；至少一个 focused API test 必须实际调用带点资产代码和 action handler。此类修复只关闭 SDK/API 缺口，不自动授权 raw MCP replacement。
128. Realtime 板块表现固定收口为 `realtime.read.sector_performance`。Canonical GET 必须是 authenticated、零参数、strict persisted-only read，只读取 active Sector 与各自最新 index，不触发 polling、provider、价格刷新、快照写入或任务；controlled fallback 只能调用正式 Realtime SDK。`get_top_movers` 仍会触发状态刷新，必须继续按 workflow/write 分流。
129. SDK-aligned governed read 必须保持三层契约一致：manifest `additionalProperties=false`、正式 SDK 参数、canonical serializer 接受的字段必须相同；API 不得静默接收 SDK/MCP 未发布参数。`fund.read.score`、`sector.read.score`、`realtime.read.sector_performance`、`factor.read.portfolio`、`strategy.read.performance`、`strategy.read.signals`、`strategy.read.positions` 与 `equity.read.financial_history` 均须保留 focused API、SDK、core-only registry、catalog replacement 和 read-evidence 回归。

兼容期内可保留 legacy tools，但必须满足：

1. 默认不作为推荐入口。
2. 可通过环境变量或配置关闭。
3. 在能力目录中标记 `legacy=true`、`replacement_capability_key` 和退役日期。
4. 不允许新增新的 legacy-style `@server.tool()`。

### 2.2 统一能力键

能力键使用稳定、可读、非 HTTP 的命名：

```text
<domain>.<action>.<object>[.<variant>]
```

示例：

```text
system.read.regime.current
portfolio.read.snapshot
decision.create.proposal
backtest.run.strategy
data_center.read.macro_series
task_monitor.read.celery_health
config_center.update.runtime_setting
```

禁止：

```text
GET_api_regime_current
post_signal_create
dashboard_alpha_tab_json
call_viewset_action
```

### 2.3 能力粒度

MCP 能力应当是 Agent 能理解的任务级动作，而不是技术端点。

允许：

1. 查询当前宏观环境。
2. 读取账户组合快照。
3. 生成决策建议草案。
4. 执行带参数和证据的回测。
5. 启动数据刷新任务。
6. 更新已批准的低风险配置。

不允许：

1. 暴露一个页面局部 JSON。
2. 暴露 serializer 原始 CRUD。
3. 暴露仅供前端控件使用的选项接口。
4. 暴露内部 cache、metadata patch、debug endpoint。
5. 暴露没有业务语义的泛型 HTTP 请求工具。

---

## 3. 统一注册标准

### 3.1 注册源

MCP 能力注册必须从统一 manifest 进入，不再由散落的 `@server.tool()` 决定外部契约。

目标结构：

```text
sdk/agomtradepro_mcp/
├── server.py
├── registry/
│   ├── __init__.py
│   ├── manifest.py
│   ├── loader.py
│   ├── dispatcher.py
│   ├── validators.py
│   └── modules/
│       ├── regime.py
│       ├── portfolio.py
│       ├── decision.py
│       ├── data_center.py
│       └── ...
└── tools/
    └── core_tools.py
```

`server.py` 只能注册核心工具：

```python
register_core_tools(server, registry, dispatcher)
```

各模块只贡献 `CapabilityManifest`，不得直接注册 MCP tool。

### 3.2 CapabilityManifest 必填字段

每个能力必须声明以下字段：

| 字段 | 说明 |
| --- | --- |
| `capability_key` | 全局唯一能力键 |
| `title` | 给 Agent 和管理员看的短名称 |
| `summary` | 一句话说明 |
| `domain` | 业务域，例如 `regime`、`portfolio`、`data_center` |
| `owner_app` | Django app owner |
| `operation_type` | `read`、`write`、`workflow`、`admin` |
| `risk_level` | `read`、`write_low`、`write_high`、`admin` |
| `requires_confirmation` | 是否需要二次确认 |
| `requires_mcp_enabled` | 是否要求用户开启 MCP |
| `required_roles` | 可调用角色 |
| `input_schema` | JSON Schema |
| `output_schema` | JSON Schema 或 envelope schema |
| `idempotency` | `none`、`required`、`recommended` |
| `executor` | 具体执行适配器 |
| `examples` | 至少一个成功调用示例 |
| `failure_modes` | 主要失败场景和错误码 |
| `audit_tags` | 审计标签 |

### 3.3 推荐数据结构

```python
@dataclass(frozen=True)
class CapabilityManifest:
    capability_key: str
    title: str
    summary: str
    domain: str
    owner_app: str
    operation_type: Literal["read", "write", "workflow", "admin"]
    risk_level: Literal["read", "write_low", "write_high", "admin"]
    requires_confirmation: bool
    requires_mcp_enabled: bool
    required_roles: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    executor: CapabilityExecutorRef
    idempotency: Literal["none", "recommended", "required"] = "none"
    audit_tags: tuple[str, ...] = ()
    legacy_tool_names: tuple[str, ...] = ()
    replacement_for: tuple[str, ...] = ()
    enabled: bool = True
```

### 3.4 注册校验

注册表加载时必须校验：

1. `capability_key` 全局唯一。
2. `title`、`summary` 非空。
3. `input_schema` 是合法 JSON Schema。
4. 写操作必须声明 `requires_confirmation` 或给出豁免理由。
5. `admin` 能力必须声明 `required_roles`。
6. `legacy_tool_names` 不得与新核心工具重名。
7. 每个能力必须能映射到 owner app。
8. 同一业务语义不得同时出现 API 能力和 MCP 能力两个候选。
9. 多个 legacy tool 聚合到同一 capability 时，`legacy_tool_names` 必须完整，catalog 中每个旧入口都必须指向同一 `replacement_capability_key`。
10. read capability 的 executor 必须证明无写入、无刷新、无轮询触发和无隐式任务副作用。
11. canonical endpoint 不存在或与 SDK 参数不一致时，注册校验必须失败或保持冻结状态。

---

## 4. 统一调用标准

### 4.1 调用入口

所有外部 Agent 调用系统功能都应走：

```text
agom_capability_call(capability_key, arguments, context)
```

请求：

```json
{
  "capability_key": "system.read.regime.current",
  "arguments": {
  },
  "context": {
    "reason": "Need current regime before evaluating portfolio exposure",
    "idempotency_key": "optional-key",
    "dry_run": false
  }
}
```

响应必须使用统一 envelope：

```json
{
  "success": true,
  "request_id": "req_...",
  "capability_key": "system.read.regime.current",
  "risk_level": "safe",
  "confirmation_required": false,
  "data": {},
  "message": "Current regime loaded.",
  "warnings": [],
  "next_actions": [],
  "audit": {
    "user_id": 1,
    "role": "analyst",
    "timestamp": "2026-07-09T10:00:00Z"
  },
  "provenance": {
    "source": "application",
    "owner_app": "regime"
  }
}
```

失败响应：

```json
{
  "success": false,
  "request_id": "req_...",
  "capability_key": "decision.create.proposal",
  "error": {
    "code": "missing_required_argument",
    "message": "account_id is required.",
    "retryable": true,
    "operator_action": "Provide account_id and retry.",
    "details": {}
  },
  "warnings": []
}
```

### 4.2 调用流程

统一 dispatcher 必须按以下顺序执行：

1. 解析 `capability_key`。
2. 加载 manifest。
3. 校验用户身份和 `mcp_enabled`。
4. 校验 RBAC 和 capability visibility。
5. 校验 JSON Schema。
6. 执行风险策略。
7. 对写操作生成 dry-run 预览。
8. 如果需要确认，返回 `confirmation_required=true` 和确认 token。
9. 校验幂等键。
10. 调用 executor。
11. 归一化结果 envelope。
12. 写入审计日志。
13. 返回结果。

MCP/SDK 审计写入使用内部 HMAC 签名鉴权，不得继承面向未认证公网请求的通用 anonymous throttle。否则多个合法 Agent 会共享匿名限流桶，造成业务调用成功但审计持续返回 `429`。如需限制内部审计流量，必须使用独立的内部限流 scope，并保持 HMAC 校验、调用方身份和请求 ID 审计完整。调用方身份必须从已认证 Profile 契约中的 `user_id/username` 读取，禁止把 Profile 主键 `id` 当作用户 ID，也不得在 Token 已认证时静默写入 `anonymous`。

### 4.3 Executor 类型

允许的 executor：

| 类型 | 使用场景 |
| --- | --- |
| `application_facade` | MCP 与 Django 同进程或可信同仓运行 |
| `canonical_api` | stdio MCP 独立进程访问 Django 后端 |
| `workflow` | 多步任务、异步任务、需要状态跟踪 |
| `internal_handler` | 受控的 MCP 内部 preview/commit bridge，用于把 proposal、approval 等治理生命周期封装为稳定 capability |
| `read_resource` | 只读资源类上下文 |

禁止的 executor：

1. `raw_http`：任意 URL 调用。
2. `raw_sql`：绕过 Repository / Application。
3. `django_model`：MCP 直接访问 ORM。
4. `shell`：除明确 admin 运维能力外禁止。
5. `page_scrape`：解析页面 HTML 或 Dashboard 模板。

### 4.4 API 的正确位置

MCP 可以在 stdio 独立进程形态下使用 canonical API 作为后端 transport，但 MCP 的公共契约不得等同于 API。

正确：

```text
Agent -> agom_capability_call("portfolio.read.snapshot") -> dispatcher -> canonical API /api/account/portfolio-snapshot/
```

错误：

```text
Agent -> tool get_account_portfolio_snapshot_api_wrapper -> SDK -> GET /api/account/portfolio-snapshot/
```

普通站内 AI、Web Chat、TUI 不应为了调用系统功能再走 MCP。它们应直接调用 Application Facade 或 canonical API。

`terminal agent` 是当前例外。它已经通过 `agent_runtime` 启动 `MCPServerStdio` 并连接 `agomtradepro_mcp.server`，因此整改目标不是强行把 terminal 从 MCP 切走，而是把 terminal 所消费的 MCP 面从散装 raw tools 收口为统一 core tools。

---

## 5. 风险、权限和确认标准

### 5.1 风险等级

| 风险等级 | 含义 | 默认策略 |
| --- | --- | --- |
| `read` | 只读，不改变系统状态 | 允许，记录审计 |
| `write_low` | 小范围、可恢复写入 | 需要确认，允许 dry-run |
| `write_high` | 影响账户、组合、策略、任务、配置或批量数据 | 强制确认，必须 dry-run |
| `admin` | 权限、密钥、运行时配置、系统任务、危险修复 | staff/admin，强制确认，完整审计 |

### 5.2 确认机制

所有 `write_low`、`write_high`、`admin` 能力必须支持服务端确认流程：

1. 首次调用返回执行预览，不执行真实写入。
2. 预览包含影响对象、字段差异、风险解释、可回滚性、证据来源。
3. 服务端生成 `confirmation_token`，设置 TTL。
4. Agent 通过 `agom_confirmation_resume` 提交 token。
5. 服务端重新校验身份、权限、参数摘要和 TTL。
6. 执行后写入完整审计。

### 5.3 幂等

以下能力必须要求 `idempotency_key`：

1. 创建信号、建议、订单、任务。
2. 触发异步刷新、训练、回测、同步。
3. 修改账户、组合、策略、配置。
4. 任何可能被 Agent 重试的写操作。

### 5.4 投资安全底线

MCP 不得默认执行真实交易。真实交易、模拟交易、调仓、清仓、策略启停等能力必须满足：

1. 用户身份明确。
2. 权限明确。
3. 风险等级至少为 `write_high`。
4. 必须 dry-run。
5. 必须二次确认。
6. 返回证据、证伪条件和影响摘要。
7. 写入审计。

---

## 6. 开发标准

### 6.1 新增能力流程

新增 MCP 能力必须按以下顺序：

1. 明确 owner app 和业务语义。
2. 确认是否已有 Application UseCase / Facade / canonical API。
3. 编写 `CapabilityManifest`。
4. 编写 executor 适配器。
5. 编写 schema、示例和失败模式。
6. 编写单元测试和契约测试。
7. 同步 AI Capability Catalog。
8. 更新对应业务或 MCP 文档。

### 6.2 禁止事项

新增或修改 MCP 代码时禁止：

1. 在业务模块中新增 `@server.tool()`。
2. 通过工具名自动猜最终风险等级。
3. 为每个 API endpoint 新增一个同名 MCP tool。
4. 在 MCP 层拼接业务规则。
5. 在 MCP 层直接导入 Django ORM Model。
6. 在 MCP 层返回未归一化异常。
7. 在 MCP 层吞掉后端错误。
8. 在 MCP 文档中暴露内部页面路径作为外部 Agent 契约。

### 6.3 命名规范

| 对象 | 规范 |
| --- | --- |
| 顶层 MCP tool | `agom_<noun>_<verb>`，数量固定 |
| capability key | `<domain>.<action>.<object>[.<variant>]` |
| error code | 小写 snake_case |
| audit tag | `<domain>:<operation>` |
| legacy tool | 保留原名，但 manifest 标记 `legacy=true` |

### 6.4 输出规范

所有 capability 输出必须：

1. 使用统一 envelope。
2. 保留原始业务数据在 `data`。
3. 面向 Agent 的解释放在 `message`。
4. 可选后续动作放在 `next_actions`。
5. 数据来源和时间口径放在 `provenance`。
6. 不把 Python traceback 暴露给 Agent。

### 6.5 文档规范

每个 capability 至少有：

1. `summary`
2. `when_to_use`
3. `when_not_to_use`
4. `input_schema`
5. 成功示例
6. 失败示例
7. 风险说明
8. 权限说明

---

## 7. AI Capability Catalog 对齐标准

### 7.1 Catalog 的角色

AI Capability Catalog 是能力目录和治理投影，不是真实执行代码源。

真实执行源：

1. Application Facade / UseCase
2. canonical API adapter
3. workflow executor
4. MCP capability dispatcher

Catalog 负责：

1. 检索候选能力。
2. 展示能力元数据。
3. 存储治理状态。
4. 记录路由结果。

### 7.2 EntryPoint 分流

Catalog 必须按 entrypoint 过滤：

| entrypoint | 默认候选 |
| --- | --- |
| `web_chat` | `builtin`、`application`、`read_api` |
| `terminal_workbench` | `builtin`、`terminal_command`、`application` |
| `terminal_agent` | 经过批准的 MCP capabilities，通过 core tools 暴露 |
| `tui` | TUI metadata 发布的用户任务能力 |
| `mcp` | MCP manifest 中启用的能力 |
| `agent_runtime` | workflow 和经过批准的操作能力 |

普通站内 entrypoint 不应把 `mcp_tool` 作为默认候选。`terminal_agent` 例外，但只应消费经过治理的 MCP capabilities，不应继续直接暴露 raw tool flood。

### 7.3 API 与 MCP 去重

同一业务语义如果已有 `application` 或 `api` 能力，MCP 只能作为该能力在外部 Agent 场景下的 transport 映射，不得额外进入同一候选池竞争。

对于 governed MCP capability，catalog 中的 `execution_target` 还应保留治理投影元数据，例如：

1. `capability_key`
2. `replacement_for`
3. `idempotency`
4. `idempotency_argument_name`
5. `audit_tags`

---

## 8. 测试与 CI 标准

### 8.1 必须测试

1. Manifest schema 校验。
2. capability key 唯一性。
3. legacy replacement 映射。
4. `agom_capability_search` 检索结果。
5. `agom_capability_schema` 输出稳定性。
6. `agom_capability_call` read/write/admin 调用。
7. RBAC 拒绝路径。
8. `mcp_enabled=false` 拒绝路径。
9. confirmation token 流程。
10. idempotency 重试。
11. 审计日志落库。
12. 错误 envelope 归一化。

### 8.2 CI 护栏

CI 必须阻止以下回归：

1. `sdk/agomtradepro_mcp/tools/` 中新增非 core 的 `@server.tool()`。
2. 新增 capability 没有 manifest。
3. 新增写能力没有确认策略。
4. 新增 admin 能力没有角色限制。
5. 新增 legacy tool 没有 replacement。
6. Catalog 同时暴露同一业务语义的 API 和 MCP 候选。
7. MCP tool 数量超过预算且没有豁免。

当前已落地的护栏起点：

1. `scripts/check_mcp_tool_budget.py` 用于校验默认 top-level MCP surface 仍保持在 core-only 预算内。
2. `scripts/check_mcp_manifest_schema.py` 用于校验 capability manifest 与 registry 结构仍然合法。
3. `scripts/check_mcp_no_raw_tools.py` 用于冻结 raw `@server.tool()` 文件面，阻止新的 legacy surface 扩张。
4. `scripts/check_mcp_catalog_dedup.py` 用于校验 synced MCP catalog 中的 `semantic_key` 去重、governed 优先级与 `replacement_capability_key` 映射不变量。
5. `scripts/check_mcp_write_confirmation.py` 用于校验 governed write-like manifest 必须同时声明 `requires_confirmation=true` 与 `idempotency=required`。
6. `scripts/check_mcp_read_evidence.py` 用于校验迁移型 governed read manifest 同时具备 raw tool、core-only fallback、focused SDK contract、`agom_capability_call` 回归和 catalog replacement 证据；显式声明 `mcp:native` 的 internal handler 必须改以 handler、core-only 与 catalog projection 证据通过门禁，不得伪造 legacy tool。
7. `scripts/check_mcp_write_evidence.py` 用于校验每条 governed write-like manifest 具备 raw tool、执行路径与核心契约测试证据。
8. `scripts/check_mcp_write_preview.py` 用于校验 governed write-like manifest 必须暴露真实 preview-first 语义，而不是只有 confirmation 外壳。
9. `scripts/check_mcp_write_audit.py` 用于校验 governed write-like manifest 必须声明 `audit_tags`，避免审计标准只停留在文档层。
10. 上述脚本现已接入 `.github/workflows/consistency-check.yml` 的 `MCP governance guards` job，作为仓库级门禁的一部分。

### 8.3 数量预算

默认预算：

| 类型 | 预算 |
| --- | --- |
| 顶层 MCP tools | 不超过 10 |
| legacy tools | 只减不增 |
| capability manifests | 可增长，但必须任务级、可治理 |
| workflow capabilities | 按业务需要增长 |

---

## 9. 兼容与退役标准

### 9.1 Legacy tool 标记

所有现有平铺 MCP tools 在整改期内必须分类：

| 分类 | 处理 |
| --- | --- |
| `keep_task` | 转为正式 capability |
| `aggregate` | 合并进更高层任务 capability |
| `internal_only` | 不再暴露给 MCP |
| `legacy_compat` | 仅保留显式兼容调用；声明 replacement 或推荐的正式能力 |
| `remove` | 删除或停止注册 |
| `unsupported` | 当前服务端契约不成立，登记机器可读禁用原因，禁止伪造 replacement |

分类执行标准：

1. `sdk/agomtradepro_mcp/legacy_dispositions.py` 是未替代 raw tool 处置的机器注册表；不得在 Markdown 维护第二份动态数量。
2. 每条没有 `replacement_capability_key` 的 raw tool 必须且只能命中一条 disposition；缺失、重复和多余记录都必须使 `scripts/check_mcp_catalog_dedup.py` 失败。
3. 任意已分类 legacy catalog entry 必须强制 `enabled_for_routing=false`、`review_status=rejected`，不得因它是只读工具而重新进入 Agent 候选。
4. `aggregate` 与 `legacy_compat` 必须声明实际存在的 `recommended_capability_keys`；推荐目标缺失时治理检查必须失败。
5. `unsupported` 必须同时存在于 `sdk/agomtradepro/unsupported_legacy_contracts.py`，并写清错误路径、证据和解冻条件。
6. `keep_task` 只表示真实待迁移债务，不得用于掩盖 aggregate、internal-only 或 unsupported；阶段收口时不得遗留未解释的 `keep_task`。
7. disposition、replacement 和 manifest 的实时统计只写入 `governance/governance_baseline.json`。

### 9.2 退役流程

1. 先新增 replacement capability。
2. 标记 legacy tool。
3. 文档提示迁移。
4. 测试覆盖 replacement。
5. 默认隐藏 legacy tool。
6. 下一版本删除或保留显式兼容开关。

---

## 10. 验收标准

MCP 收口完成后必须满足：

1. 默认 MCP 顶层工具数量不超过 10。
2. 外部 Agent 可以通过 `agom_capability_search/schema/call` 操作所有已批准能力。
3. 普通站内 AI 路由默认不选择 `mcp_tool`；`terminal_agent` 只允许通过 core tools 消费经过批准的 MCP capabilities。
4. 所有写操作都有服务端确认或显式禁止。
5. 所有 MCP 调用都有统一 envelope。
6. 所有 MCP 调用都有审计记录。
7. legacy tools 默认不推荐，且有 replacement。
8. CI 能阻止新增散装 MCP tool。
9. 文档明确说明 MCP 不是 API 平替。

### 10.1 Terminal 持久化审批闭环

130. Terminal 的 medium/high/critical MCP capability 不得依赖 stdio 子进程内存中的 confirmation token 跨请求恢复。Agent 必须先通过 `agom_capability_search/schema/call` 生成完整参数与 preview；当 call 返回 `confirmation_required` 时，Terminal 将 `capability_key + arguments + session_id + risk_level` 冻结为 `terminal_mcp_capability` AgentProposal 并提交人工审批，且不得把临时 token 持久化或返回给浏览器。staff/operator 批准后，执行适配器必须在同一个 MCP server 实例内重新调用 `agom_capability_call`，取得新的 token 后立即调用 `agom_confirmation_resume`；真实 MCP envelope 必须写入 AgentExecutionRecord。MCP 或记录持久化任一步失败时 proposal 必须进入 `execution_failed`，不得报告成功。独立 Terminal proposal 可以不绑定 AgentTask，因此 AgentExecutionRecord.task 允许为空，但 proposal、request_id、审批人和真实执行结果仍为必填审计证据。

131. “Agent 可操作系统全部功能”只指已发布、可路由且具备 canonical owner 的能力。`aggregate`/`legacy_compat` 用户意图必须由 Agent 组合 `recommended_capability_keys` 完成；`internal_only` 递归 AI 调用不得反向暴露为 MCP；`unsupported` 表示系统本身没有可成立的执行合同，不得用空实现或伪成功补齐。该边界不属于 token 优化造成的能力削减。

132. 已发布 TUI operation graph 是“用户可操作系统功能”的补充机器真源。专用业务 capability 未命中时，Agent 必须依次使用 `terminal.search.user_actions`（最多 20 项）、`terminal.read.user_action_schema` 和对应执行桥；`read` action 只能由 `terminal.read.user_action_result` 执行，`ai/write/admin` action 只能由 `terminal.execute.user_action` 执行。后者必须经过 MCP preview、持久化 Terminal 审批、idempotency、原 TUI 权限与审计校验；需要重新认证的 action 只返回 challenge，不得向模型暴露或持久化用户密码。该桥只允许已发布且当前用户可见的 action，不是任意 HTTP/API 代理。`scripts/check_mcp_tui_action_coverage.py` 必须证明每条已发布 action 都有且仅有明确的 read 或 confirmed bridge 分类。
