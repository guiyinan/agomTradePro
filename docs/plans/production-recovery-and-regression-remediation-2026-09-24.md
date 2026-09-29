# 生产恢复与系统性防回归整改计划（2026-09-24）

状态：执行中。用户已要求主代理带领 GPT-5.6 Luna（max）子代理完成本计划，并设置持续执行 goal。
当前生产基线：`6d9a134e410e8564432cdee3424975684b781e47`（release `20260929110229`，同 SHA CI、PostgreSQL workflow 与全新九阶段 S6 已通过）。仓库当前集成基线为 `5678c6dae`；`0906f94e1`（任务 attempt 所有权）与 `02d11f952`（超时预算、Redis visibility、发布授权异常归一化）已提交但尚未部署。下一候选必须重新绑定同 SHA CI、PostgreSQL 契约、完整 S6、镜像和部署回执，不能把本地改动、历史 S6 或仅完成构建的任务当作生产版本。
本计划协调既有 DATA-02、EVID/AUD、TUI 相关整改，不替代 `governance/active_plan_registry.json` 的生产状态真源，也不自动晋级既有单元。
仓库集成单元：`DATA-18`；注册表 v180 将其登记为唯一 repository focus，三位子代理是该单元内的有界任务，不新增并行生产放行。

## 1. 完成标准与边界

1. 对用户十项问题逐项提供根因、改动范围、失败复现、回归结果、生产证据和剩余风险。
2. 正式报价、日线、估值和财报分别证明发布身份、规则版本、完整适用范围、真实来源时间和内容一致性；不合格证券保留可解释阻断。
3. API、SDK、MCP 和普通用户页面对同一账户、证券、数据时间给出一致结果；HTTP 200、Celery SUCCESS、零报错均不构成恢复证明。
4. 普通 GET、浏览和只读 MCP 不排业务任务、不更新推荐或研究历史；需要刷新的用户操作必须显式且校验权限。
5. 五类系统性整改独立记录退出条件；新数据链上线前必须提供真实 provider 小规模预演和规模预算证据。
6. SIGNAL_WEAK 的 0.6000 阈值不调整；空信号、零候选允许存在且必须说明原因。禁止合成来源时间、绕过审计、降低 freshness/一致性门槛或用测试身份冒充真实主体。
7. 用户本次授权包含整改、测试及协作。涉及真实数据写入的动作先完成具体候选、预检、回滚点和影响范围；已有授权继续有效。缺少不可推导的真实 owner 合约/receipt/账户身份时记录实际缺口，不伪造、不自动审批。

## 2. 启动事实（北京时间 2026-09-24 21:39，后续必须注明时间）

- 原任务 `0d739398-3052-4378-bed1-0b99405ebfdf`：17:05:00–17:48:05，failure，2585.294 秒，retries=0；公开状态没有业务 outcome、阶段和写入计数。
- 最新抽查 `300750.SZ` 报价：Publication `04cb3649-961b-5e88-b767-73aab5a6a646`，观测 09-24 16:15、发布 19:13，返回 `publication_member_fact_changed`，零数据且决策不可用。不能继续写成“报价仍停 09-18”，也不能仅凭日期认为恢复。
- 实时信号 MCP 默认 limit=5 返回 400；本地 API 已支持 offset，但 MCP schema 尚无 offset。
- Policy MCP 已正确返回 PX/待分类/manual approval/决策不可用；Regime 返回 `capability_execution_failed`、上游状态 unknown，底层业务阻断与网络失败待区分。
- 15:38 生产快照中 audit required/outbox=true/authority selector 已生效，不能继续照搬历史 audit off 根因；该快照 decision-ready 仍 503。
- 代码仍有 Alpha 读取自动排队、历史 upsert/replace；Workspace bridge 和普通列表自动 POST；刷新提示跳过所有运行中记录。
- 启动聚焦回归 55 passed/28.48 秒，只覆盖 SDK 信号、Policy、MCP dispatcher、信号校验和提示；不是生产/API/浏览器全链路验收。原始读取结果：`output/acceptance-gap-review-2026-09-24.json`。

## 3. 工作拆分与所有权

| 主线 | 主责 | 修改边界 | 依赖 |
| --- | --- | --- | --- |
| R1 发布与运行时恢复 | 主代理 | data_center、decision runtime、生产取证与预演 | 先复现一致性错误和实际阻断，再实施恢复 |
| R2 API/SDK/MCP 契约 | Luna max A | signal API/SDK/MCP 与通用错误传递 | 与 R1 共用只读结果，不改发布链 |
| R3 只读与用户主流程 | Luna max B | Alpha homepage、Workspace、对应浏览器/权限测试 | 使用 R4 提示结构；不修改 R4 的提示文件 |
| R4 任务诊断和进度 | Luna max C | task_monitor、Alpha refresh notice、相关 SDK/MCP task 投影 | 不改 R1 的数据任务实现；向主代理提出所需阶段事件 |
| R5 防回归与发布门槛 | 主代理集成，空闲 Luna 复核 | CI selector、provider 合同、预演脚本/证据 | R1–R4 独立红绿测试后接入 |

所有代理使用同一长期分支，不创建分支、不 reset、不覆盖其他工作、不自行提交/部署；主代理整合独立 commit。各测试使用独立 basetemp；共享 SQLite 建库和大回归串行协调。共享治理清单及本计划由主代理统一编辑。独立代码审查使用另一位 Luna，不允许仅自评完成。

执行协调更新（2026-09-26）：本任务是唯一集成与部署负责人；重复生产任务已停止。主代理在同一长期分支整合补丁，只有冻结新 SHA、同 SHA CI/PostgreSQL/S6 全部通过后才部署。`data_center.0085` 部署前必须验证当前 schema 与回滚目标 writer 兼容，健康检查不能代替写入兼容证明。

## 4. 十项整改工作包

### R1.1 / P0 原任务根因与可恢复重试（用户 1）

- 读取原 Task Monitor、Celery 返回/异常、持久批次与 item attempts、任务时刻日志和 Publication 历史；按阶段还原最后成功点和写入残留。
- 区分 provider 超时/额度、范围漂移、数据时刻、审计续期、发布验证及队列阻塞；同类失败统一稳定业务码。
- 在任务入口、阶段异常和时限退出路径发布 outcome 与 requested/succeeded/failed/stored，并说明统计单位、部分写入、发布是否切换及可重试方式。
- 重试绑定原冻结范围/目标日/授权与幂等身份；旧范围已变化时开启可追踪的新批次，不静默沿用 offset。
- 验收：原任务根因定位到具体证据；重复重试不重复产出，失败不发布半成品；真实重跑四项统计与数据库、publication 对账。

### R1.2 / P0 正式发布不可用（用户 2）

- 优先复现 `publication_member_fact_changed`：记录失配 dataset/member/fact 字段和写入来源；排查同一自然键更新、重复抓取、财报后台补录与发布验证窗口竞态。
- 修复必须保持 immutable publication 身份及事实证据约束；选择满足现有模型的事务隔离、版本化事实或受控发布方案，不能跳过完整 hash 验证、更新旧 member hash 或只缩减校验范围。
- 报价/日线/估值和财报独立记录 raw refresh、validated candidate、published 三阶段；收盘日期、knowledge time、规则版本及适用资产范围一致。
- 财报需要真实时区来源时间和 retained response/row identity；pending 的 owner contract 和 matcher 不以代码默认值强行激活。
- 验收：发布后再刷新同日事实、其他资产变化、并发读写均有测试；正常更新不会无期限破坏可读发布，真实篡改仍 fail closed；真实四类发布逐项对账。

### R1.3 / P0 决策总阻断（用户 3）

- 核对实际 runtime guard 状态、当前 audit acceptance、authority、配置版本和审批链；把基础行情门与历史 MCP 审计验收门分开。
- 修复审计事实或过期验收流程后，使用既有批准、candidate-bound activation/CAS 和激活后复验正常解锁；失败自动重新阻断。
- 验收：Regime/估值返回有效业务结果或准确的独立数据限制；不允许关闭总闸、编辑历史 receipt 或把 health 正常当决策正常。

### R1.4 / P1 Alpha 全链路（用户 4）

- 逐段核对目标交易日、日线准备、Qlib build evidence/instruments、推理 scope、缓存 scope hash/date/model、工作台候选。
- 核验通用与账户任务路由、Qlib 锁、配额预算；日线失败/部分范围不得派发全部账户推理，入队数不得计成缓存 stored。
- 覆盖新上市、停牌、账户池变化、跨日缓存、交易日回退和 stale failover；旧结果只研究展示。
- 验收：目标账户各阶段来源/日期/范围一致，失败或等待准确显示；自然计划另留真实周期回执，手动成功不替代自动成功。

### R2.1 / P1 信号统一查询（用户 5）

- 同步 API、SDK、MCP 的 limit/offset/status/asset_code 与空列表语义、边界校验和返回计数定义。
- 契约矩阵：无参数、offset=0、非零分页、空页、状态/证券单独及组合过滤、非法参数；校验分页发生在过滤后。
- 验收：API Content-Type/status、SDK 实际请求参数及 MCP discovery schema/dispatcher 一致；真实默认查询不再 400。

### R2.2 / P1 错误和政策信息保留（用户 6）

- 上游业务错误保留稳定 code、中文安全 message、观测时间、freshness、must_not_use_for_decision 与 trace；网络失败单独编码，不伪装成业务门禁。
- 验证 PX/unclassified/manual approval 全链路保持；Policy neutral 只有真实分类结果才允许使用。
- 内部 traceback、token、SQL、原始第三方异常只进入有权限诊断端；公开错误采用字段白名单。
- 验收：真实 503、400、空数组、网络超时与政策待审在 API/SDK/MCP 一致；不凭单一 mocked success 验收。

### R3.1 / P1 候选详情与性能（用户 7）

- security/account 参数先经当前用户授权范围验证，再直达相应研究详情；宏观阻断禁止执行但不隐藏研究数据和解释。
- 研究读取不依赖推荐刷新 POST 或无关建议单完成；独立显示 loading、超时、重试，快速切换不显示上一账户数据。
- 优先复用批量 publication 验证和有界查询，禁止跨请求复用失效的完整性证明。
- 体验预算依据 09-08 评审建议：100ms 内反馈、主内容 P95 2s、服务端分页 P95 1s。它们是本计划待测目标，不写成已满足；慢数据独立显示等待/超时，不以空壳打点冒充完成。
- 验收：山东黄金候选→正确账户详情，宏观 blocked 仍可研究；记录冷/热多次时延、请求数、超时恢复和权限反例。

### R3.2 / P1 消除隐式写入（用户 8）

- 删除 Alpha GET 自动推理、读取时历史写入、Workspace bridge/list 自动刷新或自动用户动作；将确有需要的写操作放到明确授权动作。
- 保留后台自然计划及显式刷新；权限不足不排队，重复读取不改任务数、建议或历史记录。
- 验收：普通用户 GET 连续多次、读 MCP、跨账户拒绝、缓存缺失和 stale 场景均零业务写入；明确 POST 有权限才执行且可追踪。

### R4 / P2 运行进度与诊断（用户 9，同时支持 1）

- 扩展 owner DTO/query/serializer，再同步 SDK/MCP：technical status、business outcome、phase、started/finished、统计、稳定错误码及 trace/task id；未知计数用 null，不补假零。
- 同时返回 current_attempt 与 last_completed，运行中不被旧失败覆盖；运行失败后保留本轮及上次成功来源时间。
- 用户端只用安全摘要；原始诊断读取按运维权限，跨用户任务不泄露账户或参数。
- 验收：运行/重试/失败/部分成功/业务 blocked 但 Celery SUCCESS/零产出全部覆盖，状态端与数据库结果一致。

### R3.3 / P2 文案与时间（用户 10）

- 统一原始采集与正式发布、流动性输入缺失与证券流动性不足、研究候选与可执行推荐。
- 缺失价格显示“暂无”，不以默认 0 格式化为有效价格；局部零阻断不得遮盖上层阻断。
- 面向用户的时间明确 Asia/Shanghai 和数据日期；原始 ISO 时间保留在机器契约。英文业务状态映射中文，技术诊断按权限保留。
- 验收：页面回答什么不可用、为何、可做什么、处理角色；health 和 decision readiness 分开；普通用户浏览器主流程验证。

## 5. 五类永久防回归工作项

| ID | 类别 | 必做实现与退出条件 |
| --- | --- | --- |
| S1 | 真实 provider 契约 | 每条启用链有脱敏真实响应、provider/version/endpoint/schema/unit/time/cardinality 证据；离线重放必跑，真实请求 opt-in；空样本/全 mock 不计通过。严格财报语义缺授权时阻断，不编造 fixture 当批准 |
| S2 | 业务不变量 | 源时间不可伪造、count 与实际写入一致、部分失败不发布、读取零写入、发布后完整性、过滤再分页、账户隔离；反例测试进入 PR |
| S3 | 时间维度 | 开盘前/盘中/收盘/供应商窗口、周末节假日、授权过期/同身份续期、跨日 scope/cache、源观测/系统获取/请求时间分离；可控时钟加真实周期 |
| S4 | 规模测算 | 从当前冻结 universe 取规模，测请求数/配额/并发/数据库查询和写入/内存/任务时限，保留假设与余量；50 样本不能替代全市场容量证据 |
| S5 | component 进入 PR CI | 保留已存在的按模块 component 选择，补 SDK/MCP 路径与跨模块消费者选择回归；关键 PG 并发不因 SQLite skip 被计通过；选测和执行结果均可追溯 |

## 6. 新功能生产预演门槛（S6）

工具链恢复规则见 [S6 预检、续跑和诊断](../development/s6-rehearsal-recovery.md)。以下执行台账中的“无 resume”描述保留为当时事实；支持检查点的新版本按该规范续跑，不因同一候选的环境修复自动重跑全量。

上线涉及 provider、current Publication、Alpha 或任务规模的改变时，必须先形成与候选提交绑定的预演报告。

1. 固定真实 provider、目标交易日、当前完整 universe/hash 和确定性的约 50 只样本（若不足则完整范围）；覆盖不同交易所、单位、新上市、停牌等真实可获得类别，不造边界数据。
2. 使用真实配置/真实时钟调用 provider，记录脱敏来源、响应身份、单位、源时间、覆盖、failover 一致性、延时/请求配额和数据错误。
3. 默认不修改生产事实、current publication、推荐或任务；写路径演练在隔离 staging/临时数据库中走真实装配并验证回滚/零残留。provider 读取本身消耗配额，必须记录预算。
4. 重放有效/缺失/截断/陈旧/重复/单位错误/后续事实更新等契约；财报 source-time 无证据必须明确 blocked。
5. 按真实规模测算全量预算，记录审计有效窗口、软硬时限和安全余量；不接受线性外推掩盖有状态锁/配额上限。
6. 发布门检查报告的候选、测试哈希、provider/范围/目标日、实际调用证据与时效。缺报告、mock-only、failed 或 blocked 不得宣称门禁通过；`partial` 只有在运行时发布策略明确允许、覆盖率达到策略门槛、完整 requested 分母和逐证券缺失原因均可核验时，才是估值数据集的合格业务结果，不能扩展到报价或用来掩盖范围缺失。
7. 保留生产部署后自然周期联合复验；预演成功不替代全量正式发布和普通用户验收。

## 7. 阶段与停止线

| 阶段 | 工作 | 退出条件 |
| --- | --- | --- |
| P0 基线与计划 | 固定问题、真实响应、责任边界、goal | 本计划入索引；代理拿到有界任务；生产状态不误报 |
| P1 红灯与局部修复 | R1–R4 并行，先补真实反例 | 每主线根因、红绿测试、类型/架构通过，无权限/业务语义放宽 |
| P2 集成和防回归 | S1–S6、跨模块契约、普通用户本地流程 | 关键组合测试、只读断言、CI 选测、预算/预演门与独立复核通过 |
| P3 候选预演与生产修复 | 读取实际版本，真实小样本、备份/回滚、正常恢复流程 | 按已有授权执行；缺真实语义/身份材料准确列阻断；不绕门 |
| P4 联合复验 | 四发布、原任务重跑、Regime/估值、账户 Alpha、API/SDK/MCP、普通用户 | 同一候选/日期/范围/发布身份证据齐全；自然周期单列，未完成不标 overall complete |

生产操作前先读适用 deploy/hot-update 技能。禁止未经验证整库恢复、强制终止活动任务、无边界写入或凭过期 envelope 激活门禁。无法执行的阶段记录缺失输入及其影响，继续独立可完成工作。

## 8. 测试、提交与回滚

- 修改生产 Python 必跑增量 mypy、全量债务门禁；Black/isort/Ruff 与架构、current/Celery 契约按范围执行，禁止抬债务基线。
- API 测状态码/Content-Type/权限/空集；SDK/MCP 测真实参数、错误和 schema；模板跑 migration inventory；浏览器测用户完整任务，不能以源码字符串替代。
- 发布竞态和事务使用隔离 PostgreSQL；SQLite 通过不能替代。新代码测试须有行为断言，避免镜像实现的无效测试。
- 主代理按 sdk/mcp、task observability、readonly/workspace、publication/runtime、rehearsal/CI 分 commit；记录精确源码、命令、原始日志和结果。
- 回滚优先代码/配置 successor；保留旧 immutable publication 与 append-only 审计，不改历史哈希，不通过整库恢复覆盖用户新数据。

## 9. 执行台账

| 项目 | 状态 | 当前证据 / 下一步 |
| --- | --- | --- |
| P0 计划与 goal | 已完成 | goal 已启动；2026-09-24 本计划建立；原始核查 JSON 见第 2 节 |
| R1 发布/运行时/Alpha | 代码完成并多次部署，正式发布未恢复 | 四类事实不可变修订、provider 交易日历、动态停牌/未上市容错、单次 PreparedQuoteSession 预取、发布证据声明一致性等已随多个候选部署；09-29 生产重跑在 publication 前因超时/Redis 重投/Audit 异常未归一化失败，修复 `0906f94e1`+`02d11f952` 待放行；当前日 Alpha 链路未验 |
| R2 信号/MCP | 代码完成，生产复验待最终部署 | API/SDK/MCP 分页、业务 503、政策待分类安全透传已形成回归；部署重启后的新 MCP 会话复验未做 |
| R3 只读/工作台/文案 | 代码完成，生产普通用户 UAT 待验 | 账户归属、GET 零写入、研究入口、慢请求/重试、缺失价格语义已通过本地与受控 Chromium 验收；生产认证浏览器 UAT 未做 |
| R4 进度/诊断 | 代码完成，attempt 防护待部署验证 | current/last completed、phase、outcome、计数单位与稳定码投影已回归；09-29 Redis 重投暴露单行覆盖问题，`0906f94e1` 的 attempt 所有权修复待部署验证 |
| S1–S5 | 已集成，最终 SHA 须重取证据 | 真实 provider 契约、业务不变量、时间维度、规模测算、跨消费者 PR 选测均已纳管并经多轮同 SHA CI/PostgreSQL 验证；每次代码变更产生新 SHA 后必须重新绑定 |
| S6 | 流程已对多个候选完整成功；当前修复候选须全新重跑 | `66615517e3`、`ffde6de93`、`d387ddc19`、`e74804125`、`6d9a134e4` 均有九阶段成功记录；旧 bundle/receipt 不授权新 SHA |
| 生产联合复验 | 未完成 | 四类正式发布、guarded decision runtime 激活、财报链、Alpha、API/SDK/MCP 与普通用户页面的联合验收均未完成 |

本表在每个阶段完成后更新，只写实际验证结果。最终报告必须列完成项、未完成项、已验证测试与未验证风险。

2026-09-24 至 2026-09-29 上午已闭环的执行日志（历次根因定位、修复、CI/S6/部署证据链）已逐字归档至
[archive/plans/production-recovery-execution-log-2026-09-24.md](../archive/plans/production-recovery-execution-log-2026-09-24.md)；
归档件仅作历史证据，不代表当前状态。2026-09-26 用户决策的估值 partial 发布七条不变量仍然生效
（requested 恒为完整冻结 universe、缺失证券只局部阻断且不生成默认值、outcome=partial 全程保留等），
全文见归档件同名单节。

### 当前未完成工作（截至 2026-09-29）

1. **放行当前修复候选**：`0906f94e1`（Task Monitor attempt 所有权）+ `02d11f952`（全市场 soft/hard
   5,400/5,700 秒、authority window 6,300 秒、Redis visibility 默认 7,200 秒及启动校验、
   `SystemAuditCompositionUnavailable` 归一化为规范 `partial/blocked` 结果）。退出条件：冻结新 SHA →
   五组同 SHA CI → PostgreSQL workflow → 全新九阶段 S6 → 预构建镜像部署 → 只启动一次显式全市场重跑 →
   Task Monitor、四项计数、Publication id/hash/run id、成员与 scope block 逐项对账。
2. **正式发布恢复**：quote/price/valuation 正式 Publication 仍为 2026-09-24 的 5,557 成员旧版本；
   financial 仍为 80 行历史部分发布。退出条件：同一 run id 下四类合格发布与策略版本、来源时间、
   成员 hash 对账一致。
3. **财报链**：`financial_source_time_match_contracts` 仍待 owner approval；必须取得 provider-native
   exact source-time 并由获批 match contract 验证；财报续批（短租约/checkpoint）恢复后单独对账。
   缺真实语义/身份材料时只记录缺口，不伪造、不自动审批。
4. **决策运行时**：decision-ready 仍为 503。退出条件：四类 activation preflight 全过后按既有批准走
   candidate-bound CAS 激活并复验；Regime 另有 PMI/CPI 数据不足，须保持独立稳定码，不得误归因行情或总闸。
5. **Alpha 当前日链路**：核对日线准备、工作日 17:30 自然调度回执、账户 scope、缓存日期/hash 与候选更新；
   手动成功不替代自然周期。
6. **API/SDK/MCP 生产复验**：部署重启后的新 MCP 会话验证默认查询、offset 分页、状态/证券过滤、空集、
   业务 503 与政策待审透传；scope-block 的 SDK/MCP/UI 消费者专项测试补证。
7. **普通用户页面**：生产认证浏览器 UAT——候选详情账户归属（山东黄金用例）、宏观阻断下研究可读、
   局部阻断呈现、文案/北京时间/缺失值语义；记录冷/热时延与超时恢复。
8. **只读零写入生产对账**：部署前后对账重复 GET/MCP 的任务数、建议与研究历史行数；显式 POST 验权限；
   provider alert 等旁路写入继续观察。
9. **规模证据（S4 剩余项）**：新候选查询在生产规格 PostgreSQL 的 EXPLAIN、wall-clock、锁与内存实测，
   与 5,400 秒外层预算的余量记录；SQLite/命令级预算测试不替代该项。

### 2026-09-29 全市场长任务超时、Redis 重投与发布授权异常归一化

- 修复候选 `6d9a134e410e8564432cdee3424975684b781e47` 已通过同 SHA CI、手工 PostgreSQL
  workflow 和全新九阶段 S6，并部署为 release `20260929110229`、镜像
  `sha256:316849080cee63c12ec57a0d8c45b7ad9dcd2e4e27fcaffe97b931ca10068bc6`。随后只显式启动一次生产
  全市场任务 `89b521ed-76cd-4625-8f2f-2a6612982621`，目标交易日为 `2026-09-29`；本日 active universe
  为 5,571，前一日两只未上市证券按真实上市日自然进入本日 requested，没有固定证券名单。
- 原始执行于 09:42:24 UTC 开始。估值阶段写入 5,559、局部失败 12；行情预取完成 56/56 批、写入
  5,562，对应本日动态行情排除 9。约 3,600 秒后 Redis visibility window 到期，同一 task id 于
  10:43:08 UTC 被第二个 worker 接收；终止该副本后 late-ack 又在 10:47:01 UTC 重投。副本覆盖了单行
  Task Monitor 的 `started_at`、进度和结果，最终页面错误地显示约 319 秒运行时长和空 payload。
- 运维处置只针对该 task id：保留原始 worker，终止两个重复副本，并向两个 worker 广播 revoke 以丢弃后续
  同 id 重投。原始执行继续到 publication，但于 10:52:24 UTC 命中 4,200 秒 soft limit；同一阶段 Audit
  authority preflight 又抛出未被 Data Center 业务边界归一化的
  `system_audit_authority_unavailable`。因此本次结果是技术 failure，不能作为规范业务 outcome；旧 quote、
  price、valuation 和 financial Publication 均未切换，原子发布保护有效。
- 根因按类别拆为四项：broker visibility 小于任务 hard limit；4,200/4,500 秒预算不足以覆盖真实规模和发布
  收尾；同 task id 的重复 attempt 可覆盖监控证据；发布 composition 的 Audit 异常越过业务边界。它们与本日
  12 个估值局部失败、9 个行情局部排除不是同一问题，局部证券不得阻断其他合格证券，也不得用静态代码表处理。
- 当前候选把全市场 soft/hard limit 调整为 5,400/5,700 秒，authority window 调整为 6,300 秒，Redis
  visibility 默认 7,200 秒。启动设置会拒绝低于仓库任务 hard-limit 真值的声明，也会拒绝不严格大于声明上限的
  visibility；AST 契约测试扫描全部 Application task，新增或提高长任务上限时必须同步治理值。该技术预算不改变
  provider 单请求超时、北京时间 15:00 收盘、新鲜度、覆盖率、审计或 `SIGNAL_WEAK=0.6000`。
- Task Monitor 候选为每次执行 attempt 建立所有权：重复 `STARTED` 不再重置首次开始时间、worker 或实时进度，
  旧 attempt 的 postrun/failure 信号不能覆盖当前 attempt，合法 Celery retry 仍可领取新 attempt 并保留原始生命周期。
  broker visibility 不变量负责避免正常运行中的并发重投；监控 attempt 防护负责在异常重投时保留可信证据，二者不能
  相互替代。
- 发布 composition 候选把 `SystemAuditCompositionUnavailable` 映射为稳定的 Data Center blocked reason。
  若事实已完成写入而正式发布被 authority 阻断，任务返回 `outcome=partial`、`phase=publication`、完整
  `requested/succeeded/failed/stored`、`publication_updated=false` 和
  `must_not_use_for_decision=true`；无已写事实时才返回 blocked，不再只留下 Celery failure 和空结果。
- 14:55 仍仅用于负向回归：它证明同日出现过交易，因此可否定“全天停牌”，但绝不代表正式收盘。生产常量、
  current Publication 和容量门都以北京时间 15:00 为收盘边界。候选完成聚焦回归、格式化、mypy 和治理门禁后，
  必须形成新 SHA、重新取得同 SHA CI/PostgreSQL、全新 S6 和部署回执，再以新 task id 只启动一次生产刷新；只有
  Task Monitor 与业务结果、Publication id/hash/run id、成员及动态 scope block 全部一致，才能继续解除决策运行时
  和 Alpha/API/SDK/MCP/普通用户页面的后续阻断。
- 本地候选验证为：Celery/发布/监控聚焦回归 93 passed，Task Monitor PostgreSQL 等价 ORM 组件反例
  2 passed，高风险 TUI/terminal agent/SDK/SSL 回归 375 passed；Celery 合同 94 tasks、current-data 72
  surfaces、module map 44 modules / 210 edges、迁移生成检查、Black、isort、Ruff、13 个生产文件增量 mypy
  与全量 debt ceiling 均通过。该证据只证明候选可进入同 SHA CI/S6，尚未形成新生产恢复证据。

### 2026-09-30 Audit authority 锁根因门槛

用户要求在继续部署和全市场重跑前，停止叠加 `tolerate/retry` 补丁，先区分锁粒度缺陷与
preflight/publication 时序竞争。当前部署及新 S6 因此暂停；候选 `c8f66595906535ce1ecd32474b097dddb2ea77ac`
的 Architecture、Security、Consistency、Fast Feedback 和手工 Publication PostgreSQL workflow 均已通过，
但这些代码证据不授权部署。

#### 已证明事实

1. 失败任务 `afc2775f-b91c-4ba7-8c88-48a58efba7a0` 的持久时间为
   `2026-09-28T21:15:19.878286Z` 至 `21:15:21.673436Z`，耗时 1.7951 秒；业务结果为
   `blocked/stage=authority/requested=0/succeeded=0/failed=0/stored=0`，稳定码
   `system_audit_authority_unavailable`。任务未访问 provider、未写市场事实、未开始 publication。
2. System Audit V3 scope current read 不是普通 MVCC 读。它在一个 `READ COMMITTED` 事务内先取得 policy-id
   shared advisory lock，再对 V5 父图 19 张表和 Authority V3 两张表执行
   `LOCK TABLE ... IN SHARE MODE NOWAIT`，随后对 physical account-row source 表再取一张 SHARE NOWAIT；
   实际关系锁范围为 22 张表。任何被覆盖表上的普通 INSERT/UPDATE/DELETE 都会持有与 SHARE 冲突的
   `ROW EXCLUSIVE`，即使写入属于不同 policy、账户或 authority selector，也会令读预检立即失败。
3. 隔离 PostgreSQL 16 组件复验确认：两个 current read 可以并行；reader 存在时，相同 policy writer 被拒绝；
   不同 policy writer 也因全表关系锁被拒绝。当前测试把这项跨 policy 串行化当成既定行为，证明锁粒度是全局的，
   不是按当前 selector 收窄。四项真实 PostgreSQL 根因用例均通过（`4 passed in 217.73s`），并额外证明
   savepoint 内取得的旧关系锁会持续到外层事务结束，而顺序执行的 publication 事务不会继承已结束 preflight
   事务的锁。
4. `CoreCurrentPublicationRebuildUseCase.execute` 在进入 publication transaction 前同步执行二次 authority
   preflight；显式 preflight 与同一 publication 写事务不重叠，也没有该任务内部的异步 publication 竞争。
   把本次初始预检失败归因于 publication 自竞争不成立。
5. Data Center quote batch 的外层 UOW 内，DataFetch/DataPublication audit writer 会再次读取 scope；此时
   authority facade 的 atomic 只是 savepoint，22 张表的 SHARE 锁会保持到整个 batch 外层事务提交。
   该 batch 不写 Account authority 表，不会直接自冲突，但会扩大其它账户/权限治理写入的冲突窗口。
6. authority provider 当前以宽泛 `except Exception: return None` 隐去底层异常。relation NOWAIT、advisory
   lock、数据库连接、解码、物理来源和真实非 current 状态最终都可能压成同一 `authority_unavailable`；失败现场
   没有 blocker PID、relation、lock mode 或子阶段，因而历史任务的具体持锁者不可追溯。

#### 生产证据边界

失败窗口中唯一重叠的受监控任务是 `system_audit_authority_renewal_guard_task`，时间为
`2026-09-28T21:15:00.054Z` 至 `21:15:27.814Z`。它按当前租约执行只读检查并返回健康/noop；shared
advisory 与 SHARE relation read 应当兼容。同期 System Audit event/outbox 为零，22 张来源表没有记录到该窗口的
新 append。后续只读诊断也没有阻塞链。这些事实排除了“已证明是 renewal guard 或 publication writer”的说法，
但不能排除未进入 Task Monitor 的短事务、直接治理写入、连接/数据库异常或失败瞬间已经释放的锁。归档中
“与受治理写入锁竞争路径一致”的表述只是一项事后推断，不能继续作为具体 blocker 的证明。

#### 类别修复方案与停止线

1. **先恢复诊断因果链。** 在 provider/Application 边界保留公开稳定码和 fail-closed 行为，同时记录有界的
   内部 component、typed exception、transaction/lock phase、task/trace id；不得记录 selector 原文、SQL、
   token 或账户敏感字段。下一次 unavailable 必须能区分 relation lock、advisory lock、连接、数据损坏、过期和
   identity drift。失败瞬间运维诊断采集 `pg_locks`、`pg_stat_activity` 和 blocker PID；事后空快照不算根因证据。
2. **用 selector/source scoped advisory fence 取代全局关系读锁。** key 使用固定命名空间、版本和排序；reader
   取 shared、writer 在首次变更前取 exclusive，同一事务持有到最终 current revalidation/受保护数据库写提交。
   Authority head/revocation、policy/evidence lineage、actor/raw source 和 physical source 都必须纳入同一 key
   计划。只改 reader 不改 writer、只删除 SHARE lock 或只延长 retry 均不合格。
3. **把重工作与线性化点分开。** 完整 closed-world 恢复可在无锁 `REPEATABLE READ READ ONLY` 候选快照中
   完成，但该快照不能单独授权：另一个事务可能在快照建立后提交 revoke/successor。最终必须在短
   `READ COMMITTED` scoped fence 内重读当前 head、revocation、selector、hash、parent/seal、clock、actor 和
   physical source；任何漂移立即 fail closed。
4. **修正事务边界。** preflight 保护后续 claim/append 时，最终 revalidation 与数据库副作用必须处在同一
   fence/事务中；fence 不跨外部 publisher 网络调用。Data Center batch 内 scope read 不得把 selector fence
   无意义地延长到不相关的 provider I/O 或全批处理尾部。
5. **混合版本发布必须双锁。** 旧 reader 使用 relation lock、新 writer 只使用 advisory lock 时不会互斥。
   滚动期所有 writer 同时获取旧 relation lock和新 scoped key；所有 reader/writer 升级并验证后，另一个独立
   提交才能删除旧 relation lock。不得在单个滚动版本内直接切换协议。
6. **PostgreSQL 退出测试。** 必须证明 `pg_locks` 不再出现 22 张表的 authority ShareLock；不同
   policy/authority/source 可并行；同 selector reader-vs-revoke/change 即时 fail closed 且零写入；writer 先提交
   revoke 后 reader 不返回旧 active；RR 扫描期间提交变更会被最终 fence 发现；反向 key 集合无死锁；rollback、
   连接复用和事务结束完全释放锁；preflight 与 outbox claim 之间的 revoke 会阻止副作用；混合版本双锁有效。

在上述实现、PostgreSQL 并发矩阵、增量 mypy/债务/架构/current-data/Celery 门禁和独立审查完成前，不再扩大
authority retry 次数，不部署候选，不启动新的全市场正式重跑。重试可在协议切换完成后仅作为数据库瞬时故障的
有界韧性保留，不能作为锁设计正确性的验收依据。

首个基础实现切片已经提供固定版本 key 派生、稳定排序、多 key savepoint 回滚、shared/exclusive
transaction-scoped advisory lock 和脱敏 typed error；两项真实 PostgreSQL 双连接用例均通过（`2 passed in
1.99s`），证明部分获取失败不会把前序锁泄漏到调用方外层事务，成功获取会保持到外层事务结束。该切片尚未接入
任何业务 reader/writer，也未删除旧 relation lock，因此只算迁移基础设施证据，不算锁缺陷已经修复。

Phase 1 混合版本迁移桥已把 Evidence V5 与 OwnerTenant Authority V3 的 policy reader/writer 接入新 key；
read 使用 shared、write 使用 exclusive，同时完整保留旧 advisory/relation locks。V3 固定按 V5→V3 获取，整组
新旧锁由嵌套 savepoint 包围，后续 legacy advisory 或 relation lock 失败会释放本次已经取得的新 key。真实
PostgreSQL 组件用例通过（`1 passed in 39.07s`），证明同 policy 的新 key 互斥、不同 policy 的新 key 独立；
快速锁序、异常映射和回滚契约 `7 passed`，inventory 全量测试 `22 passed`，增量 mypy 与全仓 debt ceiling 均为
零错误。旧 relation lock 仍会跨 policy 阻断，因此该阶段仍不授权部署或重跑。

最终拆锁采用“两阶段 + 最终线性化点”：完整 closed-world 恢复移到锁外的一致只读快照，并生成含 selector、
ledger generation/high-water 与最早失效时间的不可复用 proof；随后在短 `READ COMMITTED` scoped fence 中比较
generation 并精确重读 head、revocation、actor、physical source 和 expiry。publication/member/current-pointer、
必需 audit event/outbox append 必须与最终 revalidation 在同一数据库事务；provider fetch、publisher preflight
和外部 publish 必须在事务外。只有所有 22 张来源表的 writer 都能推进 generation 或取得同一 key，且混合版本
并发矩阵通过后，才能在独立提交删除旧 relation locks。
