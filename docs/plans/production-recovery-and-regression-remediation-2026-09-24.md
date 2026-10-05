# 生产恢复与系统性防回归整改计划（2026-09-24）

状态：执行中。用户已要求主代理带领 GPT-6 Luna（max）子代理完成本计划，并设置持续执行 goal。
当前生产基线：`6d9a134e410e8564432cdee3424975684b781e47`（release `20260929110229`，同 SHA CI、PostgreSQL workflow 与全新九阶段 S6 已通过）。仓库当前代码整改基线为 `efb69a7f13744a3d64289e262b1142916e311d06`；其中任务 attempt 所有权、超时预算、authority generation/shadow/final-fence、caller-owned shared fence、锁窗表征和数据库 owner/migrator/runtime 拆分均未部署。角色链已在 disposable PostgreSQL 16.14 完成 bootstrap 故障回滚、全量 migrate、0066 反向/前进、后置 ACL 收敛和 runtime 负例演练，同 SHA 五组 CI 通过；SQLite 快照导入、完整 S6、镜像、部署与生产联合验收仍未完成，因此该 SHA 仍是候选，不是生产恢复证据。下一候选必须重新绑定同 SHA CI、PostgreSQL 契约、完整 S6、镜像和部署回执，不能把本地改动、历史 S6 或仅完成构建的任务当作生产版本。
本计划协调既有 DATA-02、EVID/AUD、TUI 相关整改，不替代 `governance/active_plan_registry.json` 的生产状态真源，也不自动晋级既有单元。
仓库集成单元：`DATA-18`；注册表 `2026-09-30.v186` 将其登记为唯一 repository focus，Luna 子代理是该单元内的有界任务，不新增并行生产放行。

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
  current Publication 和容量门都以北京时间 15:00 为收盘边界；全市场任务触发时间是 provider-ready 的 17:05，
  与收盘 observation 时间分开。提交 `e5fd3c0c8` 已禁止把全市场任务配置到 17:05 之前，并覆盖 14:55、15:00、
  17:04 拒绝和 17:05 接受。候选完成聚焦回归、格式化、mypy 和治理门禁后，
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

#### 2026-09-30 生产只读锁与恢复状态复核

1. 在 release `20260929110229` / SHA `6d9a134e410e8564432cdee3424975684b781e47`
   上，以 `REPEATABLE READ READ ONLY` 事务采样。`2026-09-29T22:15:12Z` 的同一数据库快照中，
   同时存在一个非探针 `idle in transaction` 会话，数据库仍持有运行时组合对应的 22 张
   authority/source 表的已授予 `ShareLock`；首轮采集按 relation 和 session state 分别聚合，未保留 PID→relation
   连接，因此不能把这 22 张锁事后归到一个具体 PID。探针没有执行 authority preflight、publication 或业务写入；
   约 58 秒后的 `22:16:10Z` 复采中已没有活动事务，22 张 `ShareLock` 也全部释放。
   这项生产现象与隔离 PostgreSQL 中“savepoint 内取得的关系锁持续到外层事务结束”的结果一致，直接支持
   “全局关系锁粒度过大，并被外层事务放大锁寿命”的根因；采样没有观察到未授予锁或 publication 写者，
   不能把历史失败归因于 preflight/publication 自竞争。
2. 生产最近五次 `data_center.refresh_full_market_publications` 均为 `failure`，运行时间依次包含
   `1.7951s`、`22.880788s`、`377.86416s`、`413.943629s`、`319.010601s`。生产表尚无
   `attempt_id` 字段，Task Monitor 的 `result` 也为空，说明生产仍缺 attempt 所有权和规范业务 outcome 的
   部署证据；仅凭 Celery/Task Monitor failure 不能区分 authority、provider、写入或 publication 阶段。
3. 四个 `current/published` 指针仍未由失败任务推进：quote 为 `2026-09-24 08:15Z`、price bar 为
   `2026-09-23 16:00Z`、valuation 为 `2026-09-24 07:00Z`、financial 为 `2026-04-29`；前三类各
   5,557 成员，financial 为 80。所有 publication member 的 `source_published_at` 仍为空，当前证据不足以
   证明正式发布满足新鲜度和来源时间契约。
4. Alpha cache 已有六个账户范围的 `2026-09-29` / `qlib` / `available` 记录，因此“仍固定在
   9 月 23 日”不再是当前生产事实；但账户完整覆盖、自然周期及工作台候选更新仍未联合验收。最新 policy
   仍包含 `PX + pending_review + risk_impact=unknown`，Regime 最新观测仍停在 `2026-08-08`，不能把
   health/readiness 或 Alpha 局部更新解释为决策链路已经恢复。

脱敏只读回执：`docs/deployment/production-audit-lock-readonly-2026-09-30-6d9a134e4.json`。

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

22 表的生成清单必须以运行时组合为准：Evidence V5 `_LOCK_MODELS` 的 19 张、OwnerTenant V3 authority/revocation
两张，以及 `build_account_physical_row_v2_provider()` 实际注入的
`simulated_account_row_source_v2_ledger`。`account_physical_row_observation_ledger` 已不是这条 System Audit V3
运行时 physical provider 的第 22 张表，不得因名称相似误装 trigger 或误判覆盖完成。

#### Phase 2a generation/fence 基础设施证据

Phase 2a 选择一个事务性全局 generation 行，而不是 22 个可反向取得的 per-table generation 行。System Audit
恢复本身读取完整 22 表闭世界，全局行只串行化这组低频 Account authority/source 写事务，不涉及行情、估值、
财报或证券事实表；它避免多表写事务以 A→B/B→A 顺序取得多个 generation 行。22 张来源表各安装 DML 与
TRUNCATE 两个 `ENABLE ALWAYS` 的 statement trigger，共 44 个。普通 DML 使用 `BEFORE STATEMENT`，确保在
触碰业务行前先取得 generation 行；generation 与来源写入同事务提交或回滚，零行和多行语句都只推进一次。

迁移安装后核对 22 表/44 trigger、BEFORE/statement 位、函数名、`SECURITY DEFINER`、固定 search path 和
ALWAYS 状态；运行时 coverage verifier 以当前 V5/V3/physical composition 重新计算同一 22 表集合，缺表、
缺 trigger、禁用 trigger、函数漂移或 singleton 缺失均 fail closed。Proof API 强制处于活动的
`REPEATABLE READ READ ONLY` 事务，确保 generation 与后续完整恢复共享同一 MVCC snapshot；final fence API
强制处于可写 `READ COMMITTED` 事务，并用 `SELECT ... FOR SHARE` 比较 proof 后持锁到外层事务结束；同代最终读可并行，来源 trigger 的 generation `UPDATE` 必须等待。

隔离 PostgreSQL 16 最终用例为 `4 passed in 406.32s`：覆盖全部 22 表的直接 SQL、44 trigger catalog、缺失
trigger/singleton fail closed、多行与零行 DML 各加一、来源与 generation 同步 rollback、TRUNCATE、fence
先持有时 writer 等待到提交，以及跨表 BEFORE 写入不会预先占住第二张来源表的业务行锁。SQLite 完整 migration
前进→回退→重放通过；移除 Account→Simulated Trading 的直接 ORM import 后，22 表 runtime coverage 再跑
`1 passed in 43.54s`。增量 mypy 为零回退、全仓 debt ceiling 为零错误，module map 为 44 modules / 210 edges，
entrypoint inventory 为 1,269 项且 `candidate-review=0`。CI 同 SHA 结果仍是本阶段提交后的独立门禁。

#### Phase 2b-1 只读 shadow scanner 切片

已新增独立的 `AccountAuthorityShadowScannerV3` 与 no-lock actor snapshot seam。调用方先完成 legacy
preflight 并把它的结果作为 sole decision input；scanner 在完全相同的数据库 alias 上开启最外层 PostgreSQL
`REPEATABLE READ READ ONLY` 事务，首先读取 generation proof，再恢复和验证完整 authority 闭世界。Actor bundle
通过专用 seam 校验当前连接仍处于同一 RR/RO 事务，不调用旧 locked facade，也不执行 relation lock 或 scoped
advisory lock。其余 authority、revocation、Evidence V5、actor、participant、physical source 与 expiry 校验复用
现有 repository、Application use case 和 Domain validator。

Physical provider 的 `unit_of_work_key` 目前只是构造器可检查的受信 composition 声明；scanner 无法证明实现没有
伪报 alias 或跨到另一条物理连接。该连接身份边界尚未被强制，因此即使测试通过，scanner 仍不得接入 production
decision path。

Shadow 只返回 generation 与脱敏对比：opaque identity/content hashes、source identity digests 和有效期边界；不
暴露账户或用户标识，不缓存跨事务结果，不取 RC final fence、不发布、不写 audit/outbox，也不改变旧 reader 与
legacy preflight 的决策结果。新增单测覆盖 proof-before-scan、同事务 RR/RO、alias/事务模式 fail closed、禁止
锁与写 SQL；opt-in PostgreSQL composition 契约则用真实闭世界和 Application service graph 覆盖嵌套 repository
atomic/savepoint，并检查 generation 不变。在本地隔离 PostgreSQL 16、启用
`AGOM_EVID06_POSTGRES_TEST=1` 后，该真实组合用例为 `1 passed in 169.88s`；PR 的 Publication PostgreSQL workflow
也已把同一用例列为独立步骤，并要求 JUnit 恰好收集 1 项且不得 skip/fail/error。

Legacy observation 在 shadow 事务之前产生，并使用自己的 root/actor/service 时钟读取。Shadow 先以
`authority_repository.now()` 选择 provisional root，再以 `actor_repository.now()` 校验 actor；随后既有
`OwnerTenantAuthorityV3Service.get_current()` 用自身 cutoff 重读 head，并依原有不变量多次调用
`repository.now()` 检查 assignment、participant、physical source、revocation 与有效期。两次观察不共用
cutoff，scanner 也不改写这些 Application 的时序不变量。时钟越界或 authority source 在两次观察之间变化可以
造成差异；这些差异只作诊断并继续由 legacy 结果决定，不允许 scanner 将其改写成业务 allow/deny。

本切片仍不授权把 scanner 接到 production decision path、部署、删除旧锁或发布。后续 Phase 2b 仍需另行设计并
验证短 RC final fence、fence 内重读与同库 publication/audit/outbox 原子提交；此前 2a 的角色 ACL 和并发限制
继续有效。

#### Phase 2b-2 Authority V3 root/revocation final fence 基础切片

新增一个明确标记为 partial、且没有 production composition 的 final revalidator。Shadow scan result 现在携带
精确 database alias；finalizer 在打开 RR 事务前拒绝跨 alias 结果，避免不同数据库 generation 数值偶然相同而
混用 proof。调用方只能取得实例内登记的 opaque handle；handle 禁止 pickle/copy、原子单次消费，失败同样消费，
并有 128 个待消费 proof 的有界容量。该边界仍未证明 physical provider 没有伪报 alias 或跨物理连接。

Capture 阶段在新的最外层 `REPEATABLE READ READ ONLY` 事务中先重读 generation，再只按精确 identity/hash
读取已选 Authority V3 root、后继和 revocation。Final 阶段提供
`with finalizer.fence(proof) as result:`：最外层 `READ COMMITTED READ WRITE` 事务首先对 generation singleton
执行 `SELECT ... FOR SHARE` 并比较 proof，随后使用数据库 `clock_timestamp()` 重读同一 selected root、后继、
revocation 与 expiry；generation 行锁和事务保持到调用方退出 context。早期“revalidate 返回后再由调用方写入”
的接口草案已被拒绝，因为它会在业务副作用前释放线性化点。

本切片的结果 scope 固定为 `owner_tenant_authority_v3_root_revocation_only`，不能代表 Evidence V5 父图、actor、
physical source 或完整 System Audit authority 仍然有效。它不调用旧 facade、closed-world reader、relation/advisory
锁、provider 网络、publication、audit 或 outbox，也没有 production 调用点。将来接入时，依赖该结果的同库
publication/current-pointer/audit/outbox 写入必须发生在 `fence` context 内；外部 provider fetch 和 publisher
网络调用必须位于事务外。

验证结果：finalizer + shadow 单测 `16 passed`；隔离 PostgreSQL 16 组件 `3 passed in 142.50s`，覆盖定向 SQL、
RR 后 source 变化在任何 final row read 前被 generation 拒绝，以及 caller hook 运行时仍处于 atomic block、并发
source writer 一直等待到 fence context 退出。Publication PostgreSQL workflow 增加独立 3-case 步骤、JUnit
精确计数、no-skip/failure/error 断言和 artifact。增量 mypy、全仓 debt ceiling、Black、Ruff、架构扫描与
module-map 检查通过后才允许提交该基础切片。组件测试已按 Account-owned disposable PostgreSQL evidence 登记；
重建后的 Data Center entrypoint inventory 为 1,270 项且 `candidate-review=0`，不得把未归属的新测试证据留作
`candidate-review` 来绕过治理。

本阶段仍不授权部署或重跑。旧 relation locks 和 Phase 1 双 policy locks 全部保留，业务 reader/publication
尚未接入 proof/fence。生产运行角色 ACL 未核实，迁移不会盲目 REVOKE；可直接 UPDATE generation 或修改 trigger
的 owner/superuser 仍是明确运维限制。PostgreSQL 在触发 `BEFORE TRUNCATE` 前已取得 `ACCESS EXCLUSIVE` 表锁，
跨表 DML/TRUNCATE 混合事务仍可能由数据库死锁检测中止。Phase 2b 必须先核实运行角色权限，完成 RR 扫描与短
RC publication 事务接入，在 fence 内重读 head/revocation/actor/physical source/expiry，并保证 publication、
current pointer 与必需 audit/outbox 同库同事务；上述并发矩阵和混合版本证据完成后，才能独立删除旧关系锁。

#### 2026-09-30 根因结论与 Phase 2b-3 接入路线

根因结论分为两层，不再用一个 `authority_unavailable` 混同：

1. 历史失败的已证明主因是锁粒度和锁寿命。旧 reader 在 22 张来源表上获取全局
   `SHARE NOWAIT`，并在外层 Data Center UOW 中由 savepoint 放大到整个 batch 事务。该失败在
   provider、fact write 和 publication 前已终止，因此不能归因为该任务内部的 publication 自竞争。
2. preflight 与后续 publication 之间确实存在独立 TOCTOU：预检后可以插入 revoke、successor、actor
   或 physical-source 变更。这不是历史 1.7951 秒失败的已证明 blocker，但新协议必须同时消除这项
   时序缺陷。修复不能只删 relation lock、放宽 retry 或延长 timeout。

进一步设计复核否定了两个看似简单的接法：

- generation singleton 若用 `SELECT ... FOR UPDATE`，所有最终审计 reader/publication 会在单行上串行。
  最终读 fence 应用 `FOR SHARE`：多个 reader 兼容，而 22 张来源表 trigger 的 generation `UPDATE`
  仍需 `FOR NO KEY UPDATE`，会被共享 row fence 阻塞。fence 必须绑定 alias、物理连接、backend PID、
  PostgreSQL xid 和 generation，正常退出前再读 generation；普通 RC/RW、换连接、raw commit/新 xid、
  同事务 source DML 或退出校验异常都必须 fail closed 并把外层事务标记为 rollback-only。
- 不得把现有 quote UOW 整体套入 generation fence。它包含 5,000+ fact upsert、成员逐条写入、
  candidate/hash 验证和多类 audit，会把全局 Account authority generation 共享锁变成另一个长锁。
  provider fetch 与 fact staging 必须在 fence 外；只有最终可见性切换和必需审计位于短 activation 事务。

生产接入按以下可独立回滚的切片执行：

1. **表征测试。** 固化 provider fetch 在事务外、现有 latest 读可见未发布 fact、旧 runtime provider
   重复读 scope 并进入 22-table lock、generation trigger 互斥以及 5,000 成员的查询/写入数。
   **停止线：** decision reader 清单不完整，或 PostgreSQL harness 不能观测 alias、物理连接与事务模式时，
   不进入行为改动。
2. **未接线的 audit scope lease。** 新增 Application Protocol 和 Infrastructure binding，携带
   `AuditScopeRef`、generation、selector/projection digest、最早失效时间、alias 和物理事务身份。
   writer 只能复用当前 lease，禁止重新调用旧 facade 或 fallback。
   **停止线：** DataPublication writer 仍可以无条件重读 `_scope_provider.get_scope()`，或缺 lease/过期/跨库/
   换连接不会 fail closed。
3. **完整 Account graph proof/final adapter。** RR/RO 事务中读 generation proof 并用 no-lock
   `AccountAuthorityCurrentGraphReaderV3` 恢复完整图；调用方拥有的 RC/RW 事务取得共享 generation
   fence 后重读完整图，精确比对 selector、hash、actor、scope 与最早 `valid_until`。
   **停止线：** final path 仍依赖 old locked facade，physical provider 不能证明同 alias/物理连接，或
   proof 与 final read 的数据库时钟/身份无法绑定。
4. **quote append-only revision 与读侧可见性收口。** 不新增第二张 staging fact 表；继续使用已纳入
   publication fact registry 的 `QuoteSnapshotModel`，但 staging writer 必须永远追加 immutable revision 并返回精确
   PK/ref，不得按 natural key 原地更新或在 activation 时重新查“最新”。所有决策读改为
   current-publication-member bound；raw ingestion/repair 另用显式 candidate API。
   **停止线：** 任一决策 `get_latest/list_latest_for_asset_codes` 还能读到未发布 revision，无 current
   publication 时不 fail closed，或并发 ingest 会让 activation 改指其他 PK。
5. **feature-off 的短 activation UOW。** 最外层同 alias PostgreSQL 事务的首条 SQL 设为 RC/RW，
   拒绝 ambient atomic；获得 fence、完整图 final reread 并绑定 scope lease 后，在同事务写
   publication/member/current pointer/required event+outbox。activation 失败时这些全部回滚，锁外的 immutable
   revision 按 run id 幂等重试，只清理无 PublicationMember 引用的孤儿。
   **停止线：** 任一 current/member/audit/outbox 不能同回滚，或 actor/policy/assignment/source/expiry 漂移
   不阻止提交。
6. **5,000+ PostgreSQL soak 和故障注入。** 校验精确成员 PK 集/hash、audit scope、outbox 幂等、失败回滚、
   stage 对决策读不可见，并对 activation 的 lock wait/持锁时间/query count 设硬阈值。
   **停止线：** 成员逐条写/N+1 使持锁时间超过目标，则不灰度；改为批量成员写入，必要时另立
   “不可见 candidate publication 预构建，current pointer 为唯一可见性原子点”的后续设计项。

部署前还有一个独立的数据库权限硬门槛：运行时角色不得拥有 generation singleton 的直接
`UPDATE`，不得是可修改 generation table/trigger/function 的 owner/superuser；只有受控 `SECURITY DEFINER`
trigger owner 可推进 generation。否则 fenced 事务可以先改 source、再把 generation 改回原值，绕过退出复核。
验收必须用生产 runtime role 执行 `has_table_privilege`、owner/membership、trigger/function owner、`prosecdef`、
`proacl`、fixed `search_path` 和直接 UPDATE/ALTER/DISABLE TRIGGER 负例；未通过前不接 production composition，不删旧锁，
不部署，不重跑全市场。
Phase 2b-3 的首个未接线基础切片已提交为 `05ce1f7dc`：新增 caller-owned generation fence context，
以 `FOR SHARE` 允许同代最终读并发，并绑定 alias、物理连接、PostgreSQL xid、backend PID、线程/task 与 generation；
普通 RC/RW、嵌套事务、换连接、raw commit/新 xid、异步子 task、同事务 source DML 和退出漂移均 fail closed，
异常会把外层事务标为 rollback-only。`AccountAuthorityCurrentGraphReaderV3` 复用完整 Application 图，但文档明确
physical provider identity 尚不可验证，因此不得接 production。partial finalizer 已复用同一 caller context。

本地证据：相关单测 `37 passed`；generation PostgreSQL 文件当前共收集 9 项，本机因缺少显式 disposable EVID-06
数据库配置而跳过，不计作通过；Publication PostgreSQL workflow 已把 exact case count 更新为 9，
必须在 CI 中零 skip/failure/error。Black、Ruff、三个生产文件增量 mypy、全仓 debt ceiling、module map 与 workflow
YAML 解析通过。该切片没有 production composition、没有删除旧 relation locks、没有部署或触发全市场重跑。

#### Phase 2b-3 表征结果与生产 ACL 阻断

接线前的表征测试已锁定现有实现的真实锁窗和复杂度，避免按 12 只异常证券或单次失败打补丁：

1. DataPublication audit writer 对同一 observation 首次写入和 replay 都会重新调用 scope provider；quote UOW 中调用
   发生在外层 atomic 内，且此时 QuoteSnapshot fact 已经存在。旧 scope reader 在这里取得的 22 表关系锁会持续到
   整个外层事务结束，而不是 audit 调用返回时释放。
2. 未发布 QuoteSnapshot revision 可被 legacy `latest` 查询读到；published 查询仍精确返回 current publication
   member 指向的旧 revision。因而把 fact staging 移到短 activation 事务外之前，必须先把所有决策读取收口到
   current-publication-member，不能让 staged revision 提前参与决策。
3. 5,000 条 candidate 查找精确产生 5,000 次 SELECT；`add_member` 以 32 条真实持久化样本证明每成员一条 SELECT
   加一条 INSERT，即 O(N)。把这段逻辑直接放入 generation fence 会形成新的长锁，必须先批量化或预构建不可见
   publication，再把 current pointer 切换保留为唯一短线性化点。
4. 五个聚焦表征文件共 `32 passed in 193.80s`，Black/Ruff 通过；它们只固化现状，没有修改生产行为。提交
   `70efc73c9e170ab5f76cc4a55b7247ca976bbd81` 的 Architecture、Security、Consistency、Publication PostgreSQL
   contracts 与 Fast Feedback 五条 workflow 已全部通过；Publication PostgreSQL 的 9 个 generation/fence 用例
   零 skip/failure/error。

生产 release `20260929110229` / SHA `6d9a134e410e8564432cdee3424975684b781e47` 的只读 ACL 审计在
`2026-09-30T00:46:29Z` 使用 `REPEATABLE READ READ ONLY` 事务并最终 ROLLBACK，结果为：

- `session_user=current_user=agomtradepro`，该角色是 superuser，同时拥有 `public` schema 的 CREATE；
- Account 0065 尚未部署，generation table、bump function 与 44 个目标 trigger 均不存在；
- 22 张来源表全部由该 runtime 角色持有；该角色对 22/22 表均有有效
  SELECT/INSERT/UPDATE/DELETE/TRUNCATE/TRIGGER 权限。

因此生产尚不满足 generation fence 的最低信任边界。只对 generation table 执行 REVOKE 不成立：superuser/owner
可以改回 ACL、改函数或 trigger，也能绕过 generation 单调性。脱敏证据保存在
`docs/deployment/production-account-authority-acl-audit-2026-09-30-6d9a134e4.json`；该文件只记录角色属性、对象数量和
有效权限矩阵，不含口令、连接串、业务行或账户标识。

角色整改必须先于 0065 和业务接线，并采用三类身份：

1. **NOLOGIN object owner。** 持有 schema 内业务对象、generation singleton、bump/lock functions 和 triggers；
   runtime 与 migrator 均不能继承该身份，日常连接不能直接登录。
2. **LOGIN migrator。** 只在受控部署窗口运行 Django migration；可以 `SET ROLE` 到 owner 或通过等价受控机制创建
   owner-owned 对象，不能被 web/Celery 使用。部署必须在启动候选 runtime 前完成数据库迁移和 ACL 验证。
3. **LOGIN runtime。** web、Celery 与只读 MCP 共用最小业务 DML；`NOSUPERUSER NOCREATEDB NOCREATEROLE
   NOREPLICATION NOBYPASSRLS`，无 `public` schema CREATE，无 owner membership；generation table 仅普通 SELECT，
   无 INSERT/UPDATE/DELETE/TRUNCATE/TRIGGER/ALTER 能力。

这里存在一个 PostgreSQL 权限陷阱：`SELECT ... FOR SHARE/UPDATE` 除 SELECT 外还要求目标列具备 UPDATE 权限。因此
不能在保留当前直连 SQL 的同时撤销 runtime 对 generation 的 UPDATE。0065 接线前必须新增由 NOLOGIN owner 持有的
`SECURITY DEFINER` fence-lock function，固定安全 `search_path`，内部对 schema-qualified singleton 执行
`FOR SHARE` 并返回 generation；runtime 只获该函数 EXECUTE 和 generation 普通 SELECT。验收必须证明 runtime 的
直接 UPDATE、INSERT、DELETE、TRUNCATE、ALTER、DISABLE TRIGGER 以及直接 `SELECT ... FOR SHARE/UPDATE` 均失败，
受限 wrapper 可以持共享锁并返回代次，source DML 仍只能经受信 trigger 单调推进 generation。

角色切换采用 fail-closed 的分阶段部署，不在一次应用启动中临时提权：

1. 用现有数据库管理员在独立维护步骤创建 owner/migrator/runtime，撤销 `PUBLIC` 默认 CREATE，并设置未来对象的
   default privileges；备份当前 ACL/owner 清单作为回滚依据。
2. 停止业务 writer，迁移现有对象 owner，安装受信 bump/lock functions 与 trigger，并以 runtime 凭据执行权限负测。
   任一 owner、membership、function 安全属性、44-trigger coverage 或负测不符，恢复旧应用和旧凭据，保留旧关系锁，
   不启动新 runtime。
3. 用 migrator 凭据运行 migration 与 `check --deploy`，再用 runtime 凭据执行只读/业务 DML/fence 组件验收；只有两组
   都通过才向 web/Celery 注入 runtime `DATABASE_URL` 并启动候选容器。migrator URL 不进入长期容器环境。
4. 切换完成后的回滚只回滚应用和 runtime 凭据，不反向删除 generation/revision 数据或恢复旧数据库；旧应用在
   schema 向后兼容期继续运行。若旧应用依赖 owner 权限，必须在预演中先暴露并补精确 grant，禁止恢复 superuser。

这一门槛还必须与 physical-provider identity、统一数据库时钟、完整 graph final reread、短 activation、5,000+
PostgreSQL soak 一起通过。此前不部署 0065、不删除 legacy relation lock、不启动新的全市场刷新，也不把延长 timeout
或容忍固定 12 只证券当作恢复方案。

#### 角色拆分与部署前置检查实现（`31cfbfad5`，治理与 SQLite 导入收口 `e621b4c11`，真实演练修复 `12a97cac1`）

- VPS 数据库身份已拆为 NOLOGIN owner、部署期 migrator 和长期 runtime。web、Celery、beat 只接收 runtime URL；
  migrator URL 仅进入带 `ops` profile 的一次性服务。runtime 启动前以实际连接 fail closed 核验 session/current role、
  角色闭包、public CREATE、runtime 对 public 对象零所有权、精确 22 张 authority source 表、44 个 ALWAYS trigger、
  generation ACL、函数 owner/`SECURITY DEFINER`/`search_path=pg_catalog` 和 wrapper 权限。
- remote 与 bundle 两条部署路径在任何 owner/ACL/migration 变化前都会停止旧 web/Celery/terminal writer；随后按
  PostgreSQL readiness → role bootstrap → migrator → post-migration bootstrap → runtime check → 应用启动执行。SQLite drop/recreate 后必须重新
  bootstrap；flush/loaddata 只走 migrator。独立 helper 若发现 runtime 仍运行会拒绝继续。
- 部署 env helper 原子写入权限为 `0600` 的 env/secrets，生成或复用长度至少 32、URL-safe、互不相同且非占位的
  admin/runtime/migrator 密码；管理员密码也在 bootstrap 事务中同步轮换。status/logs 不生成凭据或改写文件，
  自定义 Compose project 与 SQLite volume 使用同一项目名。
- remote 部署显式携带 SQLite 快照时，会在复制、属主和权限设置全部成功后清除旧 migration marker，再调用统一
  helper 重建 PostgreSQL 并执行 `loaddata`；不能再因旧 marker 静默跳过新快照。顺序契约固定“复制成功 → 清 marker →
  调用 helper”。
- 本地独立证据：相关部署/角色/打包测试 `105 passed, 1 skipped`；唯一跳过是 Windows 无 symlink privilege 的既有
  marker-recovery 用例；Fast Feedback 对应的无数据库套件 `4045 passed`。Ruff、Black、四个生产 Python 文件增量
  mypy、全仓 mypy debt ceiling、shell syntax、Compose config、Data Center entrypoint inventory 与 `git diff --check`
  通过。入口清单共 1,274 项，`candidate-review=0`。Luna max 三轮只读复核发现的 P1 均已关闭，最终复核未发现
  新 P0/P1。
- 同 SHA `e621b4c1123966a68bff57aefc23da7c37ea1fe2` 的 Architecture `36679612078`、Security
  `36679612080`、Consistency `36679612108`、CI Fast Feedback `36679612091` 与 Publication PostgreSQL contracts
  `36679662079` 全部通过；PostgreSQL workflow 包含 generation coverage/fence、shadow、final revalidation、真实
  publication lock/frozen fact 和 backfill control-plane，并拒绝 skip/missing evidence。
- disposable PostgreSQL 16.14 真实演练先删除 1/44 个 authority trigger，bootstrap 按
  `authority source ownership/trigger inventory is incomplete` 失败；事务回滚后固定角色计数仍为 0、对象 owner 未漂移、
  43-trigger 故障现场保留。恢复为 44/44 后 bootstrap 成功，runtime 可 SELECT generation 和调用 owner-owned lock wrapper，
  但 UPDATE generation、在 public 建表和 `SET ROLE owner` 均被数据库拒绝。
- 演练发现并修复三类真实缺陷：bootstrap/checker 使用了不存在的 `account_authority_generation_fence_lock()` 名称；
  PostgreSQL 16 不接受 `collation` 作为该 catalog 查询别名；0066 反向迁移无条件 `RESET ROLE`，导致函数删除已经提交、
  但 Django migration recorder 因 migrator 无表权限而保留 applied 记录。0066 现在只在实际切换角色时恢复原
  `current_user`，反向后得到 record=0/function=false，再前进得到 record=1/function=true/owner=owner。
- 精确生产顺序 `empty bootstrap → migrator full migrate → post-migration bootstrap → runtime checker` 在全新数据库通过；
  post-migration bootstrap 负责收敛迁移中新建对象及特殊 lock wrapper ACL。Publication PostgreSQL PR CI 已加入同一顺序，
  相关 role/migration 脚本变更会触发该 workflow，作业预算按真实全 schema 初始化从 30 分钟调整为 45 分钟；这不改变
  业务请求或 fence 的超时。
- 本地回归：角色/部署单测 `100 passed, 1 skipped`，generation PostgreSQL 组件 `9 passed in 697.80s`；后者覆盖
  22 表/44 trigger、共享 fence 并行、source writer 串行化、同事务写入回滚、原始 commit/new xid 拒绝和 runtime ACL。
  Ruff、Black、shell syntax、workflow YAML、增量 mypy、全仓 mypy debt ceiling、`git diff --check` 通过；Luna max 独立
  只读复核未发现 P0/P1。
- 同 SHA `efb69a7f13744a3d64289e262b1142916e311d06` 的 Architecture `36692681283`、Security
  `36692681306`、Consistency `36692681287`、CI Fast Feedback `36692681337` 和手动绑定该 SHA 的 Publication
  PostgreSQL contracts `36692724868` 全部通过。入口治理投影为 1,275 项、`candidate-review=0`；Publication workflow
  实际完成角色 bootstrap、migrator 全量迁移、后置 bootstrap 和 runtime checker，而非只做字符串断言。
- **未完成硬门槛：** SQLite 快照的真实 dump/flush/loaddata/计数对账尚未演练。生产 statement logging 必须在
  维护窗口关闭，避免 password DDL 进入服务器日志。
  在这些证据及后续门槛完成前不得部署 0065/0066、不得移除 legacy relation locks、不得启动新的全市场刷新。
  physical provider identity、统一数据库时钟、current-publication-member 读侧收口、短 activation 和 5,000+ soak 仍是
  后续独立阻断。

#### Physical provider 事务身份与 final expiry lease 基础切片（2026-09-30）

进一步根因审计确认，`unit_of_work_key="django:<alias>"` 只能证明 provider 的声明，不能证明它实际使用 generation
fence 所在的 Django wrapper、DBAPI socket 和 PostgreSQL transaction。该缺口允许同名 alias 的另一线程连接、重连后
socket、另一个 alias 或伪造 provider 在 fence 外读取 physical source。候选实现新增类型化
`PhysicalAccountRowProviderIdentity`，绑定 alias、Django wrapper、DBAPI connection、backend PID、xid、线程/task 和
可选 generation；RR shadow 与 RC generation-fenced graph reader 都必须把该 capability 交给 concrete provider。
provider 在每次 lock/read 前后及 scope 正常退出时重新核验真实 repository alias、wrapper、socket、PID、xid 和执行
上下文。RC graph 结束后还会再次验证 active generation fence，连接替换、raw commit/new xid 和 generation 漂移均
fail closed。

generation 只能冻结来源写入，不能冻结墙上时间。partial root/revocation finalizer 因此新增 root `valid_until` lease；
进入 fence 时仍用同连接的 `clock_timestamp()` 验证半开区间 `checked_at < valid_until`，调用方工作结束后再读一次
`clock_timestamp()`。数据库时钟倒退，或退出时间达到/越过 `valid_until`，都会抛 typed unavailable 并使同一外层事务
回滚。该结果 scope 仍明确是 `owner_tenant_authority_v3_root_revocation_only`；root lease 不能冒充完整 graph 的最早失效
时间，也不能据此接 production。

本地验证：physical provider、graph、Audit adapter 与 finalizer 单测 `61 passed`；Black、Ruff、7 个生产文件增量
mypy 和全仓 mypy debt ceiling 均通过。全新 disposable PostgreSQL 16 上，generation + 完整 V3 composition/shadow
分组 `10 passed in 489.51s`，final revalidator 独立分组 `3 passed in 160.86s`。前者与后者必须分开调用；pytest 同时把
generation 测试模块既作为测试文件又作为 fixture plugin 时会造成 3 个 fixture discovery errors，这属于测试调用方式
限制，不计作产品通过或失败。临时数据库容器已删除。

该切片仍有三条停止线：第一，完整 graph 尚未把所有 repository 统一到同一个数据库 `clock_timestamp()` cutoff；
第二，finalizer 尚未在 fence 内重读完整 graph 并使用其最早 `valid_until`；第三，尚未完成 candidate pre-stage、
current-publication-member 决策读收口和 5,000+ 短 activation soak。三项完成前继续保留 legacy production path 和关系锁，
不部署、不重跑全市场，也不通过延长业务锁等待来规避缺口。

#### 完整图统一数据库 cutoff 基础切片（`78c2ffdf4`）

进一步审计确认，完整 Authority V3 graph 虽位于一个 RR snapshot 或 generation-fenced RC 事务中，root、actor、policy、
Evidence V5、canonical binding、physical observation、ownership reobservation、provenance receipt 与 subject repository
仍会各自调用应用时钟；读取过程中跨过有效期边界时，不同节点可能按不同时间回答“current”。此外，reobservation
repository 默认重建的 binding/physical 子仓储会丢失父层注入 clock；simulated-trading physical provider 的 source-v2
future-cutoff guard 也仍使用自己的应用时钟。这是独立于 generation 的时间一致性缺口：generation 能冻结来源写入，
不能冻结墙上时间。

提交 `78c2ffdf42e7ab8d51a5d228a29febe9492782ea` 在 caller-owned 同 alias/同物理事务中只读取一次 PostgreSQL
`clock_timestamp()`，把冻结 cutoff 注入完整 Account graph 的所有仓储，并用显式 `AccountAuthorityCurrentGraphReadV3`
返回 `checked_at` 与 point-in-time projection。projection 的 `observed_at` 必须等于该 cutoff；`checked_at` 明确不是
退出租约。reobservation 默认子仓储复用同一 clock。physical provider 新增 typed read-clock scope，与已有 alias、wrapper、
DBAPI connection、backend PID、xid、thread/task identity scope 共同生效；winner/head 两次 source-v2 读取必须使用同一
authoritative cutoff，未绑定、嵌套、naive、漂移或 `as_of` 超过 cutoff 均 fail closed。未经过 graph scope 的既有
source-v2 调用仍保留原时钟行为。

验证证据：相关 unit `64 passed`；Black、Ruff、6 个生产文件增量 mypy、全仓 mypy debt ceiling、current-data 72
surfaces、architecture delta/full verify 与 module map 44 modules / 210 edges 均通过。真实 PostgreSQL 16 composition
首先按旧固定 fixture 复现 `availability` mismatch，证明 graph 确实不再使用被 monkeypatch 的应用时钟；测试随后把该
历史图的数据库 cutoff 显式固定在其有效期内，同时另行调用未拦截的真实 `clock_timestamp()` 并验证其落在主机调用
前后时间之间，最终 `1 passed in 119.78s`。这不是用应用时钟 fallback 获得的通过。

本切片仍不构成 complete-graph final lease：shadow result 当前会解包 graph read，partial finalizer 的 scope 仍是
`owner_tenant_authority_v3_root_revocation_only`。下一切片必须新增不同 proof/result 类型的 complete final path，在
generation `FOR SHARE` 成为第一把锁后，以同一 alias/物理事务/generation 重读完整 no-lock graph，精确比对 selector
与完整 fingerprint，并在 caller work 结束后再次读取数据库时钟，严格要求 `exit_checked_at < graph.valid_until`。
此前继续保留旧关系锁和 production composition，不部署、不触发全市场刷新。

Publication activation 的独立只读复核又确认两项 P0 与四项 P1：现有 published query 会按
`PublicationMember.fact_pk` 精确读取，但 Factor 的估值/财报和 Simple Alpha 的估值、财务及部分 coverage 路径仍调用
raw `get_valuation_facts/get_financial_facts_for_decision`，可以消费 staged、尚未发布的 revision；
`publish_with_members()` 则在一个 outer atomic 内对每个 member 执行 `get_or_create`，5,000 成员约产生 5,000 次
SELECT、5,000 次 INSERT/冲突检查和 5,000 个 savepoint。`get_current()` 只按 PUBLISHED 时间排序，没有数据库 current
pointer 或 scope 唯一锁；并发 publish 可能形成双 current，而读侧 `.first()` 只会掩盖冲突。full-market 在 staging 后
还会重新查询 latest candidate，并非使用 staging 返回的精确 PK/ref；`upsert_publication_safe_facts()` 也只在旧事实已被
member 引用时追加 revision，未引用事实仍可能原地更新。

后续 publication 切片据此固定为：fence 外 append-only fact staging 并返回不可变 receipt；独立事务预构建不可见
CANDIDATE 与批量 members；新增 `(dataset_key, publication_key)` 唯一 current pointer 并预建 scope 行；短 RC/RW
activation 事务只执行 generation fence、完整 authority final reread、pointer row lock、candidate/member/hash/fact
复核、publication/pointer/audit/outbox 原子切换。current 决策读必须沿 pointer → publication → member → exact fact PK，
无 pointer 或成员不完整时 fail closed。5,000+ soak 必须固定 query count、持锁时间与 lock wait 硬阈值，并覆盖并发
ingest 不改变 receipt PK、commit 前只见旧完整快照、commit 后只见新完整快照，以及 candidate/member/pointer/
audit/outbox 各阶段故障注入和 retry 幂等。Factor 与 Simple Alpha 的 publication-member-bound 契约测试是该切片的
必验项。

切片①的提交链为代码 `78c2ffdf42e7ab8d51a5d228a29febe9492782ea`、证据台账
`db3f941f501bdb5eeaba40942f7eed005f9b90c8` 和治理投影
`34da40428334561b54038956d55377aec5e5b51f`，三者均可独立回滚。Black、isort、Ruff 对 10 个相关生产/测试文件
通过；isort 在 Windows checkout 规范化工作树后没有产生相对 Git index 的内容差异。增量 mypy 覆盖 6 个生产文件且
零回归，全仓 mypy debt ceiling 为 0；current-data 72 surfaces、architecture delta/full、module map 44 modules /
210 edges 均通过。本地 Fast Feedback 为 `4045 passed, 0 skipped`。精确 SHA `34da40428334561b54038956d55377aec5e5b51f`
的 Architecture、Security、Consistency、CI Fast Feedback 与手动 Publication PostgreSQL workflow 全部通过；
PostgreSQL workflow 的 authority lock 2、generation 9、shadow 1、finalizer 3、publication 35、backfill 2，共
`52 passed, 0 skipped`。

CI Fast Feedback 的 Linux no-database job 为 `4044 passed, 1 skipped`。唯一跳过项已定位为
`test_personal_readiness_status_blocks_final_acceptance_for_missing_formal_evidence[qlib]`：现有全局 pytest hook 用
`"qlib" in item.keywords` 判断 qlib marker，参数 ID `qlib` 因此在 CI 未安装 pyqlib 时被误标，skip reason 为
`Microsoft pyqlib is not installed`。该用例验证 readiness 文案参数，并非本切片的 authority cutoff 契约；本机安装
pyqlib 后同一完整 fast suite 4,045 项全部通过。参数 ID 与 marker 耦合已记为未完成测试基础设施工作，受本次硬边界
约束不顺手修改。剩余停止线仍是 complete-graph final lease、current-publication-member 决策读、短 activation /
5,000+ soak、SQLite 快照演练与维护窗口 statement logging；此前不接 production composition、不删除 legacy relation
locks、不部署、不启动全市场重跑。

#### 完整 graph final lease 切片（`f8178af21`）

切片②新增与 partial root/revocation API 不可混用的 complete proof/result。shadow scan 现在保留 generation、同一数据库
cutoff、redacted selector、完整稳定 graph digest 和 RR 物理事务身份；complete capture 在新的 RR/RO 事务中验证同 alias、
同 generation、selector、数据库时钟单调性和最早 `valid_until`，proof 继续只保存在进程内、一次性消费、不可复制或
序列化。partial 与 complete proof 共用 128 项容量上限，并按各自 lease 清理过期 proof。

complete fence 保持 production composition 未接线，先在调用方拥有的 RC/RW 事务中取得 generation `FOR SHARE`，再以
同 alias、Django wrapper、DBAPI connection、backend PID、xid、thread/task 和 generation 调用 no-lock
`AccountAuthorityCurrentGraphReaderV3` 重读完整 graph。最终 fingerprint 必须与 shadow 完全相同；graph missing、selector/
fingerprint/physical identity/generation 漂移、数据库时钟倒退、入口过期以及 caller work 结束时
`exit_checked_at >= graph.valid_until` 均 fail closed，并由同一 outer atomic 回滚。完整 graph digest 对 authority、
assignment、policy、Evidence V5 parents、authentication、physical/reobservation/receipt 等递归 dataclass 稳定字段做
canonical SHA-256；命令/actor selector hash 与实体 identity hash 分开，避免把 selector 摘要伪装为 graph identity。

验证证据：相关 unit 与 Audit reader `61 passed`；Black、isort、Ruff、2 个生产文件增量 mypy、全仓 mypy debt
ceiling、workflow YAML、`git diff --check` 与 module map 44 modules / 210 edges 均通过。两个生产文件非空行分别为
860/957，提交后 changed-file size guard 在 1,000 行硬限下通过。全新 disposable PostgreSQL 16 容器执行 finalizer
组件 `7 passed in 1029.09s`，0 failure/0 skip；其中 3 项保留 partial 契约，4 项新增验证 generation lock 先于
`clock_timestamp()`/graph reread、同 PID/XID/generation、完整 digest mismatch fail closed、caller 写回滚和 source
writer 在 complete fence 退出前等待。容器已删除，未连接或修改任何长期 PostgreSQL 容器。此前一次未设置 opt-in
变量的收集得到 `7 skipped`，原因是组件明确要求 `AGOM_EVID06_POSTGRES_TEST=1`；该次不计作通过，随后上述隔离运行
已零 skip 闭合。Publication PostgreSQL workflow 的 finalizer 精确收集数由 3 更新为 7。

切片②的代码提交为 `f8178af210e3d7f61e6358ce92c3f00d5f2bfcf9`，证据台账提交为
`fe90e0316807fc214adca94f54e29ac2fd9a8a17`，补齐生成投影的独立提交为
`a915ebdda1c54e63a85271b54e21c79db5b7452f`，均可单独回滚。精确 SHA `fe90e0316807fc214adca94f54e29ac2fd9a8a17`
的 Publication PostgreSQL contracts `36726731161` 通过：authority lock 2、generation 9、shadow 1、finalizer 7、
publication 35、backfill 2，共 `56 passed, 0 skipped`。同次精确 HEAD 首先使 Consistency 和 Fast Feedback 因
`governance/data_center_architecture_inventory.json` 仍是旧投影而失败；这项遗漏没有作为“CI 环境问题”跳过。生成器
把 current-surface inventory 从 5,226 更新为 5,236 后，精确投影 SHA `a915ebdda1c54e63a85271b54e21c79db5b7452f`
的 Architecture `36727891815`、Security `36727889376`、Consistency `36727889764` 与 CI Fast Feedback
`36727889380` 全部通过；后两者实际重新执行并通过 deterministic Data Center architecture inventory guard。该投影
提交不改生产代码，Publication PostgreSQL 沿用前一精确代码 HEAD 的 56 项零 skip 证据。

剩余停止线：Factor 与 Simple Alpha 的 current-publication-member 决策读尚未收口；无 current pointer 的 fail-closed、
短 activation UOW、5,000+ PostgreSQL soak、SQLite 快照对账与维护窗口 statement logging 尚未完成。继续保留 legacy
relation locks 与 production composition；不部署、不启动全市场重跑，也不通过延长 lock wait/retry/timeout 规避失败。

#### Factor / Simple Alpha current-publication-member 读侧切片（`77ab421fd`）

切片③把 Factor 的估值/财务因子、Simple Alpha 的估值/财务事实、health/universe 估值 coverage，以及账户候选池的
`strict_valuation` / `price_covered` 范围选择统一到 current Publication member。财务查询现在与估值查询一样按证券验证
member；current 缺失、目标证券缺 member、member reader/hash reader 缺失或 member scope/table 不匹配时 fail closed，
不会退回 raw fact。coverage 的 freshness gate、Publication 身份和 member 投影位于同一一致读快照；历史决策继续用
中国市场日首作为 source knowledge cutoff，published 查询只把精确 member fact PK 交给 repository。

代码与治理投影提交为 `77ab421fdc8aa5393ac52be83552a92f7ffe4d5a`，可独立回滚。真实 ORM 组件测试同时保存
published 旧 revision 和 raw/staged 新 revision，证明 raw 查询能看到新值，而 published 估值、财报仍返回旧 member；
另以仅 raw 的估值和价格资产证明 Alpha coverage 不会把未发布证券加入候选范围。Factor 对 Tushare/AKShare 两条路径的
PE/PB/PS/股息率以及缺 member 反例均已覆盖。聚焦回归 `76 passed`；Black、isort、Ruff、7 个生产文件增量 mypy、
全仓 mypy debt ceiling、current-data 72 surfaces、legacy fact/entrypoint guard、module map 44 modules / 210 edges、
全量与增量 architecture guard、changed-file size guard 均通过。`query_services.py` 非空行由基线 1,071 降至 1,068，
没有通过继续扩张超限文件规避门禁。

治理投影附加测试得到 `31 passed, 1 failed`。失败项
`test_inventory_expands_command_edges_and_publishes_full_task_targets` 来自本切片前已存在的
`scripts/manage_vps_migrations.py:dynamic-command` entrypoint；基线 `c234a8388` 的已提交
`governance/data_center_entrypoints.json` 已包含该条目，本切片未修改该脚本或 inventory generator。该失败不计作通过，
按本次硬边界记入未完成测试基础设施工作，没有顺手修复。

精确代码 SHA 的 Architecture `36741989381`、Security `36741989445`、Consistency `36741989430`、CI Fast Feedback
`36741989428` 与 Publication PostgreSQL contracts `36741989493` 全部通过。Fast Feedback 的 Python 3.11 / 3.13
各为 `2,947 passed, 58 skipped`；Publication PostgreSQL 为 authority lock 2、generation 9、shadow 1、finalizer 7、
publication 35、backfill 2，共 `56 passed, 0 skipped`。这些 PostgreSQL 负例产生的 lock timeout、权限拒绝和 rollback
错误日志是预期故障注入，workflow 的 missing/skip evidence gate 已通过。

剩余停止线：数据库 current pointer 与短 RC/RW activation UOW 尚未实现；candidate/member/hash 复核及
publication/pointer/audit/outbox 原子回滚、5,000+ PostgreSQL query count/持锁时间/lock wait 硬阈值尚无证据；SQLite
快照 dump/flush/loaddata/计数对账与维护窗口关闭生产 statement logging 尚未完成。继续保留 legacy relation locks 与
production composition；不部署、不启动全市场重跑，也不延长 lock wait、retry 或 timeout。

#### 短 RC/RW Publication activation UOW 切片（`befab299c`）

切片④新增数据库 current pointer 与 feature-off activation UOW。候选 Publication 和 immutable member 可在 fence 外预构建；
只有 activation 可以推进 pointer。activation 拒绝 ambient transaction，在 caller-owned、同 alias 的短 PostgreSQL
`READ COMMITTED READ WRITE` 事务中先取得完整 Account generation fence，完成完整 graph final reread 并绑定 audit
scope lease，再锁定 pointer/candidate，复核 candidate state、成员数量与精确 PK 集、成员内容 hash、事实内容 hash、
policy 与 frozen evidence。随后 publication、pointer、必需 audit event 和 outbox 在同一事务切换；任一阶段故障、authority
漂移、成员漂移、事实漂移、重复或冲突 run 均 fail closed 并整体回滚。外部 provider、事实 staging 和 candidate/member
预构建保持在 fence 外；legacy publish/rollback 只保留历史，不再被 `get_current()` 当成 current。旧 relation locks 与
production composition 均未删除或接线。

代码提交为 `befab299c7a2e5f0c19e2771b7e8ef9d3b4cd5f8`；隔离写演练兼容提交为
`f5d808ff8c70fc7ea3d6ddff2e9bb66d81e8c41b`；确定性架构投影为
`76f736713394ca149b9cc153de1fa0b577c70270`。旧测试夹具按新指针契约迁移的提交为
`9eb04899ce8d23f6578149298488584bc9ccd5e9`，只补 candidate parent、改为验证 legacy history 且断言 legacy path
不生成 pointer；current-data 测试引用投影为 `30ab82667829b9470883beaa4a1fa47a30414183`。这些提交各自独立，
没有夹带 production composition 或部署改动。

验证证据：activation/query/rehearsal 聚焦回归 `77 passed`，隔离写演练单测 `32 passed`，旧夹具迁移的五个文件
`42 passed in 208.63s`；Black、isort、Ruff、生产文件增量 mypy、全仓 mypy debt ceiling、current-data 72 surfaces、
architecture delta/full、module map 44 modules / 210 edges 与 `git diff --check` 通过。5,001-member PostgreSQL soak
把 activation query count 固定为不超过 35、generation fence 持锁时间不超过 2.0 秒、lock wait 不超过 0.25 秒，并覆盖
精确成员/hash 复核、并发 pointer、audit/outbox 原子回滚与 retry 幂等。精确测试 SHA `9eb04899ce8d23f6578149298488584bc9ccd5e9`
的 Publication PostgreSQL contracts `36802990529` 全部通过：authority lock 2、generation 9、shadow 1、finalizer 7、
publication 36、backfill 2，共 `57 passed, 0 skipped`；其中 publication 组包含 soak 和隔离写演练。精确最终治理 SHA
`30ab82667829b9470883beaa4a1fa47a30414183` 的 Architecture `36803289345`、Security `36803289427`、Consistency
`36803289409` 与 CI Fast Feedback `36803289349` 全部通过。最初 test commit 的 Consistency 因治理清单仍引用旧测试名
失败，该失败未被跳过；更新唯一机器真源后，72-surface guard 与 6 项 checker self-test 均通过。

未验证风险与剩余停止线：member seal 当前由 repository 和 activation 复核保证，数据库尚无阻止绕过 repository 修改
candidate member 的 trigger/constraint；这项 P1 必须与 SQLite loaddata 兼容性一起评估，不能在本片顺手加数据库对象。
本机 disposable Docker PostgreSQL 端口在一次本地复验中关闭连接，因此该次不计作通过；同 SHA 的原生 Linux PostgreSQL
零跳过 workflow 是本片数据库证据。SQLite 快照真实 dump/flush/loaddata/计数对账和维护窗口关闭生产 statement logging
仍未完成；完成切片⑤前继续禁止部署、删除 legacy relation locks、接 production composition 或启动全市场重跑。

#### SQLite 快照迁移与 statement logging 维护窗口切片（`e90419039`）

切片⑤把 SQLite 迁移由脚本内重复的临时计数逻辑收口为一个可执行快照契约：源端与目标端分别记录数据库类型、
全部 managed model 表和隐式 many-to-many through 表的行数，并单独记录 `dumpdata` 可序列化对象数；fixture 行数、
源目标逐表计数或证据自校验任一不一致都 fail closed。合法零行业务快照返回 `noop`，不会因没有业务数据阻断初始化；
CI 证据则强制使用非空历史 publication/member 快照并要求 `success`。该历史快照不创建 current pointer，导入后明确验证
pointer 为空，`get_current()` 返回 `None`，避免 `loaddata` 冒充 activation。

部署迁移脚本在 PostgreSQL ready 且所有 runtime writer 停止后、第一次 role bootstrap 之前进入全局 logging maintenance
window。窗口保存并关闭 `log_statement`、duration/sample/transaction sample、error statement 及两项 parameter logging
配置，从新连接回读确认；退出、HUP/INT/TERM 或命令失败均走恢复，只有恢复回读与对账全部成功后才能写 migration marker。
恢复状态以 0600 原子文件保留，恢复失败时状态文件不删除。角色密码 DDL 另用 session `PGOPTIONS` 纵深防护，SQL 在任何
密码变量展开前验证全部八项设置。代码提交为 `e9041903986b8d63f379175c507601c660b9e800`；PostgreSQL 16 暴露出
`psql \quit` 不接受自定义退出码后，fail-closed 修正提交为 `12dfef2e8140399581ac811b729acbd0a0d0b308`；CI 维护参数
只绑定管理员连接、禁止最小权限 migrator 继承的修正提交为 `a0526496d9f072e4fddc3c8ff6d8c79acda0bfe8`。三项均只在
切片⑤范围内，可按提交独立回滚。

本地验证为相关 migration/role/packaging 契约 `49 passed`，后续 guard 精确回归 `11 passed`；Black、isort、Ruff、
shell syntax、workflow YAML、增量 mypy（1 个生产 Python 文件，0 regression）、全仓 mypy debt ceiling、entrypoint
inventory 1,280 项、architecture inventory、module map 44 modules / 210 edges 与 `git diff --check` 均通过。精确最终
SHA `a0526496d9f072e4fddc3c8ff6d8c79acda0bfe8` 的 Publication PostgreSQL contracts `36809279150` 通过：
authority lock 2、generation 9、shadow 1、finalizer 7、publication 36、backfill 2，共 `57 passed, 0 skipped`；此外真实
SQLite→PostgreSQL 演练对账 561 张表、291 个源/目标物理行、291 个 fixture 对象，mismatch 为 0。logging 演练从
`all|500ms|1s|0.5|0.25|error|1kB|2kB` 进入关闭状态，覆盖正常退出与注入失败恢复。相同 SHA 的 Architecture
`36809279116`、Security `36809279217`、Consistency `36809279122` 和 CI Fast Feedback `36809279102` 全部通过。

两次未计作通过的失败均保留：`36808191279` 证明 PostgreSQL 16 会忽略 `\quit 4` 的参数并返回成功；
`36808744812` 证明 step 级 `PGOPTIONS` 会被非超级用户 migrator 继承并由数据库拒绝。前者改为在
`ON_ERROR_STOP` 下执行确定性 guard error，后者把维护参数限定到两次管理员 `psql` 调用；最终 run 已越过两个原失败点。

未验证风险与剩余停止线：逐表计数和 fixture 对象数证明结构化往返没有丢行，但不证明每列内容等价，也不替代完整
publication/member/fact 语义重算；CI 历史 member 使用有效 manifest hash 并验证无 current pointer，但其 synthetic fact
reference 不是生产事实。数据库级 member immutability trigger/constraint 仍未实现，完整 compose 部署状态机也未在生产环境
执行。本片未部署、未接 production composition、未删除 legacy relation locks、未启动全市场重跑；①→⑤代码与证据已齐，
后续生产部署与正式发布属于⑥，必须等待用户单独授权。

#### 2026-10-01 生产恢复与 active universe 容错根因切片（`f392b6fd4`）

用户授权⑥后，候选 `74effb6852bfe0acf8dbb125f5969bc8f41cc067` 的九阶段 S6 在
`/opt/agomtradepro/rehearsals/s6-74effb685-20261001a` 全部通过，绑定预构建镜像
`sha256:d2113c82f0d1e0b8ba634d471e025a5db6a3ea56ea29673fac3d0a8ffe303258`、release
`20261001133636`、manifest SHA-256
`78bd1d02bd19e5381587dd80fcee69508f4a7b9741ef09b14dd743ff6b77441a`。部署后 TLS、HTTP health、
PostgreSQL schema/migrations、TUI registry、Qlib identity、Celery worker/beat 和运行 SHA/image 独立复核均通过。
部署前 PostgreSQL 备份为远端
`/opt/agomtradepro/backups/database/postgres-20261001T090426Z.dump`、本地
`backups/vps-postgres/postgres-20261001T090426Z.dump`，大小 223,548,588 bytes，SHA-256
`a685b6d6028a9891ad3b94ce394df99ce80bac834257f5120bf00afca589fa10`。

只启动了一次显式全市场刷新，task ID
`0d349eeb-04ee-4187-8b2d-aa29e80696af`。该任务在 263.80 秒后返回规范业务结果
`outcome=blocked`、`requested/succeeded/failed/stored=0/0/0/0`、
`error_code=MARKET_UNIVERSE_SCOPE_INVALID`、`publication_updated=false`；没有用第二次任务覆盖失败，也没有进入正式
Publication。安全诊断证明 provider 本次观察 5,571 个证券，生产资产主表保留 5,572 个 active A 股，唯一差集为
`301139.SZ`。provider 观察 hash 为
`2f2baa4f46edec6a81d1ae15227cd27115cdfd33f63a121a0ef089d621dd3347`，持久化范围 hash 为
`dde92cbeb5d806f450605e6b7c00a908a1868ad0d58f951ec33f9a813011fdc0`。

根因不是该证券本身，而是两条既有不变量互相冲突：自然刷新使用 `deactivate_missing=False`，按规范保留 provider
一次漏报的 active 证券；`AShareUniverseSyncReport.active_count/active_codes_sha256` 却只按本次 touched 集合计算，随后
全市场编排把这组 hash 与持久化后的 target-date active 集合做精确相等校验，于是任何保留漏项都会整批阻断。提交
`f392b6fd4479aca52a6f13750c7231424f11e0bd` 将 provider observed 与数据库 effective 范围拆成两套证据：正式分母和
active hash 从写后 repository 重读；容差内未观测证券继续保留，并输出完整 code 列表、count/hash、比例、容差和稳定
reason；比例按刷新前 active 范围计算，provider 新增证券不能稀释。超过既有 1% 一致性容差时，无论普通保留模式还是
显式 deactivate 模式，都在任何资产写入前以 `A_SHARE_UNIVERSE_RETAINED_SCOPE_EXCESSIVE` 失败关闭。实现未写死证券或
固定数量，也未把 provider 缺行解释成退市。

本地回归为 provider/service/orchestration/真实 ORM Repository 组件 `88 passed`；覆盖 0.5% 保留、精确 1% 边界、
provider extra 不稀释比例、2% 超限、`deactivate_missing=True` 超限写前阻断、effective DB hash 对账，以及保留证券仍进入
完整 valuation 分母且缺事实时禁止 Publication。增量 mypy 为 0、全仓 mypy debt ceiling 为 0；Black、isort、Ruff、
current-data 72 surfaces、Celery task contracts、Data Center architecture inventory 和 `git diff --check` 均通过。

剩余停止线：`f392b6fd4` 及本节证据提交尚未取得同 SHA 的 Architecture、Security、Consistency、Fast Feedback、
Publication PostgreSQL 五组 CI，也尚未重新执行完整九阶段 S6；因此不能把旧 `74effb685` 的 S6 或已失败 task 当作新修复
的发布证据。新候选通过门禁、S6、同镜像部署和身份复核后，才可再启动一个新的显式全市场 task ID；随后仍须完成正式
Publication、decision runtime、Alpha、API/SDK/MCP、普通用户页面和只读零副作用联合验收。生产 token 鉴权 GET 会更新
`last_used_at/updated_at`，严格零写与端到端 token-auth 验收目前存在契约冲突，必须作为独立未完成项修复或明确计量，
不得伪称已证明零副作用。

#### 2026-10-02 全市场 Publication 目标会话绑定切片（`fc6f165e0`）

候选 `4f8a2ee940630fb63c47f02980fce12d52202170` 的五组同 SHA CI 通过后，九阶段 S6 在
`/opt/agomtradepro/rehearsals/s6-4f8a2ee94-20261001a` 全部通过，绑定预构建镜像
`sha256:433a0dbc8bcd706f49b86a9cb68f9b6577a2d1d7313fd0e71c82c840564aba2c`、release
`20261001162320` 和 manifest SHA-256
`481a4342a675762da52c8c9a644b1cf8e6f27aa1a6c35ac7b4acbfc96aa848b6`。同镜像部署及运行身份复核通过后，只启动了一次
显式全市场任务 `1120eed9-8d7c-445e-9298-7f3b0230a59a`。该任务完成报价 56/56 批、估值 56/56 批，业务结果为
`outcome=partial`、`requested/succeeded/failed/stored=5572/5561/11/11125`，但正式发布阶段以
`MARKET_PUBLICATION_VALIDATION_FAILED` 失败关闭，`publication_updated=false`、`published_members=0`；没有用重试
覆盖该结果。8 个报价缺口均由本次 Tushare `suspend_d` 证明为目标日全天停牌；11 个估值缺口包含这 8 个证券及另外
3 个证券，实际覆盖率为 `0.9980258435032304`，达到既有版本化估值 partial 政策门槛。

只读诊断证明失败不是 authority lock、provider 批次或覆盖率门槛：quote preview 正确保留 5,564 个目标日成员和 8 个
停牌 scope 缺口；valuation candidate repository 的 `latest` 查询却为本次 11 个失败证券补入 2026-09-29 旧事实，使
preview 错误显示 5,572/5,572 全覆盖。完成会话不变量随后发现估值 `oldest_observed_at` 不属于目标交易日 2026-09-30，
在发布写入前正确失败关闭。根因是候选选择只有“latest”语义，缺少本次全市场任务的目标交易日绑定；不能通过删除日期
校验、放宽 coverage 或写死 11 个证券解决。

基础代码提交 `fc6f165e01ec1d746e3636350d9038c1bb766c36` 为单数据集 rebuild 和 core coordinator 增加可选、按数据集校验的
`required_observation_date(s)`。全市场完成会话只把本次 `target_date` 绑定到 quote 与 valuation；候选日期不等于目标日
时不进入本次成员集合，并按完整 5,572 requested 分母形成真实缺口。valuation 只有继续满足活动政策
`allow_partial=true`、版本化证据、现有 `minimum_coverage_ratio`、非空成员、无 unexpected 和非空 run id 时才能发布
scope block；quote 仍保留 15:00 收盘与逐证券停牌证据门。price bar、financial 等未参与本次刷新会话的数据集不会被
隐式过滤，未知数据集绑定在读写前失败关闭。

Luna max 独立只读审查确认上述生产路径没有放宽 universe、partial policy、quote 15:00、audit 或锁边界，同时指出估值
自然键 `val_date` 与 `observed_at` 的日期一致性尚未显式验证。加固提交
`e8de9d96c7a0430e28d67d3ba126c9305fb1ea26` 将两者分别解析后要求同一中国市场日期；自然键和观测日期同时属于旧会话时
仍作为本次缺口，二者互相矛盾时直接失败关闭，不能任选一个日期通过。对应测试改为使用真实旧 `val_date` 自然键，并新增
日期身份冲突反例；该提交不改变 full-market 编排、policy、audit、事务或 repository 查询范围。

本地验证：rebuild/orchestration 聚焦契约 `104 passed`；Publication 持久化、查询投影、API 与 readiness 组件/集成回归
`86 passed`，合计 190 项、0 failure、0 skip。新增反例覆盖旧估值不能补足目标会话、低于政策门槛不写 Publication、
日期约束只作用于显式数据集、未知数据集失败关闭，以及 preview/execute 使用同一 quote/valuation 目标日映射。两个生产
文件增量 mypy 0 regression、全仓 mypy debt ceiling 0；Black、isort、Ruff、current-data 72 surfaces、Celery 94 tasks、
architecture full/delta、module map 44 modules / 210 edges、Data Center entrypoint 1,280 项和 `git diff --check` 均通过；
architecture inventory 已按生成器刷新并记录 5,261 个 current-surface references。`run_current_data_contract_tests.py`
不支持按单个 contract 选择，未把该次参数错误计作检查结果；改由上述 103 项直接契约测试和 72-surface manifest checker
闭合本切片范围。

中间候选 `0d9022a81` 的 Architecture、Security、Consistency 和 Publication PostgreSQL 均通过；Fast Feedback 在
Python 3.11 暴露 2 个既有命令边界回归，结果为 `2593 passed, 59 skipped, 2 failed`，没有把该 SHA 计作放行。失败证明
此前 active-universe 容错在解析 provider 之前先读取数据库 active 范围，使 malformed/invalid JSON 的安全错误路径在
无数据库测试环境提前触发 ORM。提交 `c2d497c1f8cf9c15227fbe3b4bfe5c9fc14b5f66` 只把该只读范围查询移到 provider
加载、规范化和身份校验之后，仍位于任何资产写入及 1% 容差判断之前；因此无效输入继续在 provider 边界安全失败，合法
输入仍按数据库 preexisting 范围计算 retained-missing 比例。management command、universe provider 和 full-market
orchestration 回归 `98 passed`；该生产文件增量 mypy 0 regression、全仓 mypy debt ceiling 0，格式、72-surface、Celery、
architecture full/delta 与 module map 检查均通过。

剩余停止线：`c2d497c1f` 及本节最终证据提交尚未取得五组同 SHA CI、完整九阶段 S6、同镜像部署与生产身份回执，因此不得直接重跑。
门禁齐全后才可启动一个新的显式 task ID，并对 business outcome、计数、quote/valuation Publication id/hash/run id、成员
日期与 scope blocks 逐项对账。只有正式发布通过后才能继续 decision runtime、Alpha、API/SDK/MCP、普通用户页面和只读
零副作用联合验收；财报 owner approval 与 token-auth GET 写 last-used 的既有停止线不因本片改变。

#### 2026-10-02 候选部署、单次全市场结果与 production activation 停止线

最终候选 `946ea48106c44ff3465c9712410f82cb908cd1a6` 的 Architecture、Security、Consistency、CI Fast Feedback 与
Publication PostgreSQL contracts 五组同 SHA workflow 全部通过，对应 run 为 `36903055938`、`36903055826`、
`36903055832`、`36903055985`、`36903056125`。九阶段 S6 在
`/opt/agomtradepro/rehearsals/s6-946ea4810-20261002a/evidence-20261002b` 全部通过，绑定预构建镜像
`sha256:3479241f808d0301f06d1b5701ee3d2d6d2a9db804a52d2bc6b5e8bcf935dde6`、release
`20261001213508` 和 manifest SHA-256
`e4c42fdeef7fcc1651f6b44aae19bad41b436003ee6c5df4ad835a75bfb1e9cf`。同镜像部署后，运行 SHA、TLS/health、
PostgreSQL schema/migration/role、ASGI 连接策略、TUI metadata、Qlib 0.9.7、Celery worker/beat 与两节点 ping 均通过；
部署前数据库备份为 `/opt/agomtradepro/backups/database/postgres-20261001-220949.dump`。首次 S6 证据目录
`evidence-20261002a` 因隔离环境的 `AGOM_RELEASE_REHEARSAL_DATABASE` 值不是精确 `1` 以
`REHEARSAL_WRITE_SCOPE_OPT_IN_MISSING` 失败关闭；修正隔离值后使用新 checkpoint 重跑，没有改写失败现场。

部署后只启动了一次显式全市场刷新，task ID 为 `2f0af418-3cdb-40bf-90d1-8dcdc0406cec`。Celery backend 技术状态为
`SUCCESS`，规范业务结果为 `outcome=partial`、`requested/succeeded/failed/stored=5572/5561/11/11125`、
`publication_updated=true`、`published_members=16697`，目标交易日 `2026-09-30`，publication run ID
`c2d05ff0-327d-43dd-9065-3713f6f28c25`。报价 5,564 成员并以 Tushare `suspend_d` 证据明确阻断 8 个全天停牌证券；
日线 5,572 成员；估值 5,561 成员并按活动版本化政策为 11 个缺失证券记录
`valuation_source_data_unavailable`。三组 publication ID 分别为
`d9b21044-94d7-5765-a11f-331eac58ab80`、`5fcce0d7-82ac-5466-a70b-557b44e0f686`、
`38125afa-4390-599f-8279-0afa554e219f`；报价和估值的 source observation 均为中国市场 15:00 收盘，未把 14:55
当作正式收盘。没有启动第二个全市场任务覆盖该结果。

Task Monitor 把该正常返回记成 `failure` 的根因不是 Celery 异常：其本地 `_FAILED_BUSINESS_OUTCOMES` 把
`partial/blocked` 与 `failed` 合并，并绕过共享 outcome resolver；因此形成 `status=failure`、`exception=None` 与
业务 payload `partial` 的矛盾。提交 `08646e590` 把技术状态与业务 outcome 分开：仅规范业务 `failed` 或 Celery
技术失败进入 FAILURE，`partial/blocked/noop` 保留业务投影并记录技术成功；同时把 full-market partial/noop 的兼容
`success` 修正为 guard 规定的 `true`。聚焦回归 109 passed，Celery 94 tasks、current-data 72 surfaces、两个生产文件
增量 mypy 零回归，Black/isort/Ruff 与全仓 debt ceiling 通过。该提交尚未部署，生产旧 Task Monitor 行不做历史篡改。

正式恢复仍停在新的、可复现的 production activation 缺口。三组最新 Publication 行及全部 member 已持久化，policy、
coverage、scope block、日期与 hash 可对账，但 `data_center_canonical_publication_pointer` 对报价、日线、估值和财报均无
current 行；三组新行的 `member_manifest_hash` 为空且 `members_sealed_at` 为 NULL，也不存在以其 publication ID 绑定的
SystemAuditEvent。旧 production rebuild 直接写 `PUBLISHED`，不会调用 feature-off 的短 activation UOW；严格 current
reader 因而按设计 fail closed，不能把“有 published 行”当作“正式 current 已激活”。禁止直接 INSERT/UPDATE pointer、
把旧行改回 candidate 或补造历史 audit。

只读 lineage 对账进一步证明不能安全采用这三组旧行：报价 5,564 个 member 全部带 ingested run，精确对应 56 个成功
RawAudit；日线 5,572 个 member 和估值 5,561 个 member 的 `ingested_run_id` 全为空。publication run ID 是协调器独立生成，
数据库中没有同 run 的 RawAudit；现有 activation 又只接受一条 RawAudit，无法诚实代表 56 个报价批次，更不能代表缺少
ingestion identity 的日线和估值。内容 hash 生成确定性 publication ID；相同内容重建会撞到未 seal 的 legacy
`PUBLISHED` 行，普通 candidate staging 也不能绕过。

decision runtime dry-run 因此保持 `ready=false`，未执行激活。正式 valuation publication 本身为 fresh、partial policy
有效且 11 个 scope block 完整；price publication 虽覆盖 5,572 个证券，但最早 member observation 仍使 dataset gate 返回
`canonical_publication_stale`；财报仍是旧 `1.0:1.0` policy 并返回 `canonical_publication_policy_version_mismatch`，没有伪造
owner approval。provider capability gate 同时报告 historical price、valuation、financial success stale。runtime 仍保留
原 `decision_runtime_blocked` 状态，没有关闭保护开关。

下一整改切片必须先建立候选级多批 RawAudit manifest、让估值/日线事实携带真实 ingestion identity，并把
current rebuild 拆为 fence 外 CANDIDATE/member/manifest 预构建与 fence 内整组 activation。三组 full-market dataset
必须在同一个 complete Account graph fence 和同一个 RC/RW 事务中按稳定顺序锁 pointer/candidate，复核 member/fact/
manifest/policy/freshness 后原子切换，并逐 publication 写 required audit/outbox；任一失败整组回滚。旧关系锁继续保留。
必须补 5,000+ PostgreSQL query count、持锁时间、lock wait 与故障注入证据。历史 adoption 只有在每个 member 的真实来源
RawAudit 可完整重建、当前 policy/freshness/coverage 全过且记录“当前发生的 adoption”事件时才允许；本次日线/估值不满足，
保持 fail closed。上述生产 composition 与 lineage 修复通过同 SHA CI、S6 和同镜像部署前，禁止再次启动全市场刷新，
也不能继续宣称 decision runtime、Alpha、API/SDK/MCP 或普通用户主流程已恢复。

#### 2026-10-02 Candidate staging、价格 lineage 与整组 activation 本地收口

提交 `b89006fa0` 把 current rebuild 的纯候选构建逻辑抽为单一实现，并新增 fence 外
`CANDIDATE/member/seal/RawAudit manifest/空 pointer` 原子 staging。候选在 activation 前保持
`published_at=NULL`；legacy `PUBLISHED` 同 ID 不会被 adoption；RawAudit 必须同时通过内容 hash、规范
capability、hash-bound `extra.source_type` 与 fact ingestion identity 复核。任一成员、seal、manifest 或 pointer
写入失败均整体回滚。原 staging/domain 聚焦结果为 46 个 unit/domain 和 21 个 component 用例通过；复核后又补充
`CURRENT_PUBLICATION_STAGING_INVALID` 稳定 Application 错误码、三组 dataset 的统一 capability 映射及反例。

提交 `08b80ff02` 使显式 `prepare_stock_history` 成为行情历史写入和 RawAudit 的唯一入口；普通 GET/read path 保持
零写副作用。reference snapshot 在 provider 请求前批量捕获，写入 UOW 在 identity/fact 前复核 snapshot hash；
`default_source=failover` 的后续 route 也必须存在可比较 overlap，否则以
`MODEL_MARKET_UNVERIFIED_FAILOVER` 失败关闭。空批次/停牌窗口的成功 RawAudit 作为 request-level exact reference
进入 `MarketPricePreparationResult` 和 full-market 结果，重复读取不新增请求或审计。5,001 资产组件测试首次暴露
逐证券解析 `AssetMaster/AssetAlias` 的确定性 N+1，SQL 超过 9,000 条；批量解析后，真实 SQLite ORM reference
snapshot 加 5,001 次 prepared-cache read 固定不超过 2 条 SQL，canonical/alias 去重和多日 per-asset limit 反例通过。
该规模证据只覆盖只读 reference lookup，不替代 PostgreSQL 查询计划或锁证据。

提交 `e5e658f1b` 新增固定 quote/price/valuation 三候选的整组 activation：只接受一个 complete Account graph fence
和一个最外层 RC/RW 事务，稳定锁定 pointer/candidate/member/fact/coverage/manifest/RawAudit/policy，所有复核完成后
原子切换三组 publication/pointer，并逐组写 required audit/outbox。单候选 Application 与 Repository 双入口均拒绝
这三个 dataset；空 pointer 要求 `publication_id/hash/activation_id` 三字段完整空态；低层构造的错误 capability 候选、
残留 pointer identity、manifest/fact drift、任一 audit/outbox 或第二 pointer 写失败均失败关闭并整体回滚。保留的非
bundle 单候选 `market.news` 成功、幂等与回滚契约继续通过。提交 `5f32569d9` 重新生成 module map，结果为 44 modules、
210 edges。

本地合并复核为 248 passed；activation 聚焦组合为 76 passed、29 skipped。增量 mypy 35 个生产文件零回归、全仓
mypy debt 为 0，Architecture 扫描 3,299 files / 0 violations，current-data 72 surfaces、Celery 94 tasks、data-center
catalog 10 datasets、Black 与 Ruff 通过。`composition.py` 的历史混合 CRLF/LF import block 在本次语义修改前即不能通过
全文件 isort；本片只保留 14 行语义 diff，没有借机格式化整文件，其他改动文件 isort 通过。该历史格式债务不影响运行，
但必须在独立格式治理项处理，不能混入本恢复提交。

剩余停止线：本机未设置 `AGOM_EVID06_POSTGRES_TEST=1`，因此 5,001 成员 PostgreSQL soak、query count、持锁时间和
lock wait 的硬阈值尚无通过证据；测试已接入生产 complete finalizer 的 `capture_complete/fence_complete` 与真实 generation
锁，但阈值仍为 provisional，必须由 exact-SHA PostgreSQL workflow 证明。activation 当前显式只支持 `default` alias，
现有部署没有 `DATABASE_ROUTERS`，因此同事务成立；若未来支持其他 alias，StateWriter 与 staging 注入协议必须显式携带
alias/UOW identity。生产 composition 仍未把 full-market 协调器接到 staging + group activation；price target-session
选择及基于真实停牌证据的 scope block 仍需完成。完成 composition、exact-SHA 五组 CI、全新 S6 和同镜像部署前，继续
禁止再次启动全市场刷新，也不得解除 decision runtime 阻断。

#### 2026-10-02 日线目标会话与动态停牌容错（`e37474a7f`）

`equity.price.bar` 候选现在显式绑定本次 `required_observation_date`。目标交易日之前的旧 bar 不能补足本次正式分母；
目标日 observation 必须达到中国市场官方 15:00 收盘，14:55 observation 会失败关闭。缺口只有同时具备目标日、逐证券、
来源明确的 `price_full_day_suspension` 证据时才进入动态 scope block；代码不包含固定证券列表或固定数量，且 quote 的
`quote_full_day_suspension` reason 不能替代 price reason。版本化 policy 仍保持原 coverage 和 `allow_partial` 配置，
没有降低门槛。

本地证据：current rebuild、policy、staging 和版本完整性共 `76 passed`；current-data manifest 为 72 surfaces；
Black、isort、Ruff、两个生产文件增量 mypy 与全仓 mypy debt ceiling 均通过。没有测试跳过。全仓 debt 首轮曾在并行中的
审计引用切片捕获 `full_market_refresh_orchestration.py` 缺少 `Mapping` 导入；修正后重跑为 0 errors，不把首轮失败计作通过。

剩余停止线：full-market 编排尚未把 `price_full_day_suspension` 和 price 目标日传入正式 staging；quote、valuation、price
三组 RawAudit manifest、complete Account graph proof/finalizer、短 RC/RW group activation 与 5,001+ PostgreSQL soak
仍未在生产 composition 闭合。该提交未部署、未启动全市场重跑，legacy relation locks 保留。

#### 2026-10-02 全市场同步 exact RawAudit 引用（`50a0ee349`）

Quote 成功结果现在返回与同一 sync `run_id/ingested_run_id` 绑定的 exact `RawAuditReference`；quote 与 valuation 的成功和
失败审计都将 provider config 的规范 `source_type` 写入 hash-bound `extra`。valuation provider 抛出的标准
`DataFetchError` 也进入失败审计事务，不能绕过 RawAudit。full-market 按 quote、valuation、price 数据集分别汇总引用；
引用缺失、身份不符或重复都会在 Publication 前失败关闭。

引用校验发生在事实持久化之后时，结果保留真实资产 `requested/succeeded/failed`、已写 `stored` 和独立
`operation_requested/succeeded/failed`；缺引用的 quote 批次不计成功，整体返回 `partial`，不能误报零写入 `blocked`，
也不能进入正式发布。

本地证据：full-market 75、quote sync 9、valuation lineage 6，共 `90 passed`；changed-production mypy 5 个文件零回归，
全仓 mypy debt 为 0；Black、isort、Ruff、Celery contract 94 tasks / 21 exemptions / 24 files、current-data 72 surfaces
与 `git diff --check` 均通过。无测试跳过。

剩余停止线：这些 exact refs 尚未转换为三组 candidate staging binding；price failover 的每条引用仍缺少随返回值传递的
实际 `source_type`，不能用全局 provider 名猜测。production composition、complete Account graph proof/finalizer、
group audit/outbox、短 activation 和 PostgreSQL 5,001+ soak 仍未闭合。本片未部署、未启动全市场重跑。

#### 2026-10-02 Group activation Audit writer 工厂（`bc43e0288`）

Audit composition 新增显式 database alias 的 publication activation writer factory，并经 Audit repository provider 与
`core.integration.data_center_audit` 跨 App facade 暴露。Factory 复用现有 runtime/outbox composition 校验；composition、
coordinator、所需 caller-owned atomic/targeted append/stream lock 接口缺失，或 writer/coordinator alias 与调用方不一致时
均失败关闭。该切片只提供 factory，没有把 full-market 接入 activation。

本地证据：Audit runtime 与真实 Django event/outbox coordinator 共 `33 passed`；changed-production mypy 3 文件零回归，
全仓 mypy debt 为 0；Architecture full 3,299 files 与 delta 10 files / 335 added lines 均为 0 boundary、0 audit violations；
Black、isort、Ruff 和 `git diff --check` 通过。无测试跳过。

剩余停止线：组件测试使用 SQLite，只证明 event/outbox 同成同败和 alias/config fail-closed；尚未在 PostgreSQL activation
事务内验证。Account complete proof/finalizer factory、Data Center staging/group composition、5,001+ soak、exact-SHA CI、
S6 与同镜像部署仍未完成。本片未部署、未启动全市场重跑。

#### 2026-10-02 日线逐引用 source binding（`9233156fc`）

价格历史链路新增专用 `ModelHistoryRawAuditBinding`，将 exact RawAudit reference 与持久 RawAudit `extra.source_type`
绑定；写入返回后重新读取该 hash-bound 元数据并与 ProviderConfig 核对。binding 随 prepared-cache、逐行 evidence、
ModelMarketData 聚合和 `MarketPricePreparationResult` 传播，同时保留原 reference 投影。failover 可让不同引用携带不同
source type；同一 raw audit id 出现不同 source type 或不同 reference identity 时失败关闭，不能静默覆盖。

本地证据：相关 unit `106 passed`；5,001 资产 ORM scale `2 passed in 292.69s`，继续覆盖 prepared-cache read 查询数；
changed-production mypy 7 文件零回归，全仓 debt 0；Black、isort、Ruff、current-data 72 surfaces 和 `git diff --check`
通过。无测试跳过。

剩余停止线：full-market 结果和 staging command 尚未消费 price binding；`MODEL_MARKET_SUSPENDED.details.source` 在空行情
分支仍是 route name、末段停牌分支是 fact source，语义尚未统一，不能写死成 `tushare.suspend_d`。必须先统一逐证券
停牌 evidence source，再接入 `price_full_day_suspension` scope block。本片未部署、未启动全市场重跑。

#### 2026-10-02 Production complete authority capture factory（`af6cb1e35`）

新增未接线的 production authority capture factory。它只接受 production V3 runtime selector，以 `scope_*` 构造
`GetCurrentOwnerTenantAuthorityV3Command`，actor reader 继续固定 `actor_*`；重新读取 actor/scope bundle 并要求与调用方
preflight `SystemAuditReaderContext` 精确一致。factory 使用同一 alias 的 physical provider 运行 RR/RO complete shadow scan，
再由 `AccountAuthorityFinalRevalidatorV3.capture_complete` 生成 opaque proof；返回的 fence 只接受同一 proof，并在 RC/RW
complete reread 后再次绑定 alias、tenant、owner 与不晚于 preflight 的 `valid_until`。

本地证据：聚焦故障注入 `6 passed`；changed-production mypy 1 文件零回归、全仓 debt 0；Black、isort、Ruff、
Architecture full/delta 与 `git diff --check` 通过。selector 缺失/V1 schema、preflight 漂移、alias 不同、legacy identity、
expiry/scan 漂移和 proof capture failure 均未返回可用 fence。无测试跳过。

剩余停止线：尚未在 disposable PostgreSQL 上执行真实 RR/RO capture + RC/RW fence，也未接 Data Center production
composition。`governance/module_map.json` 因新增 core integration entrypoint 及并行 Audit/Data Center 改动产生 drift，须在
所有接线文件稳定后统一生成并检查。本片未部署、未启动全市场重跑。

#### 2026-10-02 日线动态停牌 evidence 与三数据集 preview（`76ce8d98c`）

`ModelMarketRoute` 现在显式携带 provider config 的 canonical `source_type`；空行情全天停牌和有旧行情的末段停牌两条
路径都把同一 source type 写入 `MODEL_MARKET_SUSPENDED.details.source`，不再混用 provider display name 与 fact source。
价格准备结果按证券绑定 asset、目标交易日和 evidence source，缺失、重复或冲突证据失败关闭。

full-market 在正式 preview 前完成 price preparation；quote、price、valuation 三组同时绑定本次 target date。price 的
`price_full_day_suspension` scope 只来自本次逐证券 price evidence，与 quote suspension scope 分离；非停牌证券的旧 bar
不能补本次目标会话，14:55 仍不能冒充 15:00 官方收盘。

本地证据：model-market、price preparation、full-market orchestration 与 5,001 资产 component 共 `135 passed`，最终核心
复验 `13 passed`；changed-production mypy 5 文件零回归、全仓 debt 0；Black、isort、Ruff、current-data 72 surfaces、
Celery 94 tasks 与 `git diff --check` 通过。无测试跳过。

剩余停止线：尚未连接真实 provider 或执行 PostgreSQL 端到端 staging/activation；quote、price、valuation 的 stage
bindings、group request、Audit writer 与 complete authority proof 仍需在 production composition 统一接线。本片未部署、
未启动全市场重跑。

#### 2026-10-02 Task attempt 身份门禁（`49b200764`）

生产任务现在只能取得同时匹配当前 Celery request 与 Task Monitor `STARTED` 记录的 `task_id/attempt_id`；缺少 request、
attempt marker、记录不存在、终态/RETRY 状态、重复投递 marker 不一致或 repository 读取失败，均以稳定业务码
`CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE` 失败关闭，不生成生产 fallback。Celery retry 重新进入 `task_prerun` 时会
强制签发新的 attempt marker，不能沿用上一次 request 中的旧 marker；旧 attempt 因此不能成为新 candidate manifest 的
幂等身份。

本地证据：Task Monitor identity 与 signal lifecycle 聚焦测试 `45 passed`；3 个生产文件增量 mypy 零回归；Black、isort、
Ruff 与 `git diff --check` 通过。全仓 mypy debt 本轮被共享工作树中尚未提交的 production publication composition 一条
`arg-type` 阻断，非本提交文件；该 composition 切片必须修复并重新取得全仓 debt=0，不能把本轮记作通过。

剩余停止线：full-market 尚未在 provider 写入前调用该 getter，也未把 attempt identity 写入三组 stage command；production
composition、整组 staging/activation、5,001+ PostgreSQL soak、exact-SHA 五组 CI、S6、同镜像部署及单次生产重跑均未完成。
本片未部署、未启动全市场重跑。

#### 2026-10-02 日线成员 lineage 与请求级证据分离（`6ca3f259e`）

`MarketPricePreparationResult` 现在分别保留完整请求级诊断 binding 与只属于最终目标会话成员事实的
`member_owning_raw_audit_bindings`。空批次、全天停牌和未被最终选择的 provider 尝试继续出现在诊断证据中，但不能进入
Publication candidate manifest；成员 binding 必须是完整诊断集合中 identity/source 完全一致的有序子集，缺失、重复或来源
冲突均失败关闭。成员归属仍由 staging repository 按最终 fact ingestion identity 复核，没有按证券数量、provider 名称或
`stored_count` 猜测来源。

本地证据：price preparation 与 model-history 两个相关 unit 模块 `101 passed`；1 个生产文件增量 mypy 零回归；
current-data 72 surfaces、Black、isort、Ruff 与 `git diff --check` 通过。新增反例覆盖 stale primary 仅保留为诊断证据、
fallback 成为唯一成员 owner、空停牌批次无 member owner，以及 member/diagnostic 缺失和来源冲突。全仓 mypy debt 本轮仍被
共享工作树中未提交的 publication composition 一条 `arg-type` 阻断，必须在其独立切片修复并重跑，不能计作通过。

剩余停止线：full-market 尚未把 member-owning bindings 转成 price stage command，quote/valuation stage、任务 attempt、
complete authority capture、group audit/activation 仍未统一接线；PostgreSQL 5,001+ soak、exact-SHA CI、S6、同镜像部署和
单次生产重跑均未完成。本片未部署、未启动全市场重跑。

#### 2026-10-02 Production staging/group activation composition（`70152c1dc`）

Data Center production composition 现在固定组装 quote、price、valuation 三个 `CurrentPublicationStagingUseCase` 与一个
`ActivateCanonicalPublicationGroupUseCase`。候选构建复用 legacy rebuild 的同一组 dataset/policy/freshness/coverage 规则；
staging repository、RawAudit resolver、manifest repository、group activation repository、Audit writer 和 complete Account
authority capture 全部显式绑定 `default` alias，非默认 alias、组件 alias 漂移、Audit writer 缺少 manifest append 或 authority
capture 返回类型/alias 不符均失败关闭。group use case 改为依赖只含 `activate_candidate_group` 的窄 repository protocol，没有用
cast 掩盖实现不完整。factory 已经由 `apps.data_center.composition` 的 typed wrapper 暴露，但尚未接入 Celery task。

本地证据：production composition unit `11 passed`，existing staging component `21 passed`；8 个生产文件增量 mypy 零回归，
全仓 mypy debt ceiling 复跑明确通过 `0 errors in 0 files`；Black、适用文件的 isort、Ruff、Architecture full/delta、
`git diff --check` 均通过。module map 已由生成器刷新并通过检查，结果为 44 modules / 210 edges。`composition.py` 存在本片前
已有的混合行尾/全文件 isort 债务，本片只保留新增 import/export/wrapper 的语义行，没有归一化历史内容。没有测试跳过；
PostgreSQL 端到端未在本片执行。

剩余停止线：full-market 仍使用 legacy `publications.execute`；三组 stage command、pointer CAS、activation request、Audit writer、
complete authority proof 与 task attempt 尚未在同一编排闭合。必须继续补故障注入和 5,001+ PostgreSQL query/持锁/lock-wait
硬阈值，再取得 exact-SHA 五组 CI、S6 与同镜像部署；本片未部署、未启动全市场重跑。

#### 2026-10-02 Full-market candidate staging 与整组 activation 接线（`5c2a8b098`）

full-market 生产任务现在在任何 DATA-02 preflight、provider 读取、进度写入和市场写入之前，先从当前 Celery request 与
Task Monitor `STARTED` 记录取得不可由调用参数伪造的 task attempt identity；身份缺失以
`CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE` 返回零写入 `blocked` 结果。完成事实写入和三数据集 preview 后，编排先读取
quote、price、valuation 三条 current pointer 的完整 CAS 快照，再在 fence 外按固定顺序 staging 三组 candidate/member/
seal/RawAudit manifest。price manifest 只接收最终成员事实的 `member_owning_raw_audit_bindings`，请求级空批次、停牌或未选中
provider 审计继续保留为诊断证据，不进入成员 manifest。

三组 staging 全部成功后先构造同 alias 的必需 Audit writer，再捕获完整 Account graph authority；capture 之后只做纯内存
activation request 构造，并立即进入一次 group activation。结果只有在精确返回 quote、price、valuation 三组 `PUBLISHED`
publication，且 publication ID/hash/run 与 staged candidate 全部一致时才设置 `publication_updated=true`。preview、pointer、
任一 staging、Audit writer、authority capture、audit/outbox 或 activation 的已知校验、composition 与数据库失败均映射为稳定
业务码，保留已完成事实写入的 `requested/succeeded/failed/stored`，不会把 CANDIDATE 数量或 Celery 技术状态误报为正式发布。

本地证据：full-market orchestration 与 production bundle 聚焦回归 `106 passed`；staging/activation component 回归
`74 passed in 315.74s`，两组均无跳过。故障注入覆盖 identity-before-I/O、preview/pointer/staging/Audit writer/authority
capture/group activation 的 `DatabaseError`、第二阶段 staging 失败后不 capture/activate、audit/outbox 失败不更新 pointer，
以及成功路径同一 run/task attempt、member-only price lineage、三个 CAS 先读和 capture 后仅一次 activation。7 个生产文件
增量 mypy 零回归，全仓 debt `0 errors in 0 files`；Black、适用文件 isort、Ruff、Celery 94 tasks、current-data 72 surfaces、
Architecture full 3,303 files / delta 6 files、module map 44 modules / 210 edges 与 `git diff --check` 通过。新增协调器拆到独立
Application 模块后，主编排为 1,194 个非空行，large-file 治理违规为 0。

跳过与未验证风险：`apps/data_center/composition.py` 的全文件 isort 仍受本片前已有混合 CRLF/LF import 行影响，本片只新增
一个显式 facade export，没有进行无关全文件行尾改写；其余相关文件 isort 通过。完整 governance consistency 唯一失败为
本片前已由 `af6cb1e35` 引入并已提交的 `core/integration/production_account_authority_capture.py` 三条 Account infrastructure
直接 import（`core_integration_infrastructure_import_growth` 0→3）；本片没有抬高 baseline，也未顺手改动该边界，必须列入
“未完成工作”单独整改。

剩余停止线：尚未在本提交 exact SHA 上完成 5,001+ PostgreSQL staging/activation soak，并重新证明 query count ≤35、
generation fence 持锁时间 ≤2.0 秒、pointer lock wait ≤0.25 秒及真实 RR/RO capture + RC/RW fence；五组同 SHA CI、完整 S6、
同镜像部署、正式 Publication 和联合验收均未执行。本片未删除 legacy relation locks、未部署、未启动全市场重跑；这些证据
未齐前不得进入用户授权的生产重跑。

#### 2026-10-03 Audit authority activation 硬门槛复验（`f5e59d119`，证据计数 `405538d00`）

完成项：切片④的 Account generation 文件规模门禁已按职责拆分。运行角色 ACL 与 role-closure SQL 移入独立
Infrastructure 模块，稳定异常移入无反向依赖的 errors 模块；原模块继续导出旧异常身份和
`verify_account_authority_generation_runtime_acl` wrapper，调用方契约不变。PostgreSQL pointer lock timeout 反例现在断言
`AccountAuthorityFinalRevalidationUnavailable` 及底层 `OperationalError` cause，保留稳定业务异常而不延长 lock timeout。
合并 fence SQL 后的模拟游标同步为五列状态，新增无 PostgreSQL 依赖的 wrapper 参数透传和异常身份兼容测试。CI JUnit
证据守卫依据保留的 XML 从 36 更新为实际 37 个 publication 用例，没有删除、跳过或放宽任何测试。

测试计数：本地 Account generation/finalizer/shadow/role contract 共 `71 passed`；activation/Audit 回归
`75 passed`；disposable PostgreSQL ACL、role-closure 和 generation fence `9 passed`；生产文件增量 mypy 3 文件零回归，
全仓 mypy debt `0 errors in 0 files`；Black、isort、Ruff、文件规模、Architecture full/delta、module map 44 modules /
210 edges 及治理一致性通过。精确 SHA `405538d00d0f46a598ba1ee9f46629471b33784e` 的 Publication PostgreSQL contracts
`37056214885` 通过：authority lock 2、generation 9、shadow 1、finalizer 7、publication 37、backfill 2，共
`58 passed, 0 skipped`。publication 组包含 5,001-member soak，因此 query count ≤35、generation fence 持锁时间
≤2.0 秒、pointer lock wait ≤0.25 秒三项硬断言均通过。相同 workflow 的 statement logging 正常/故障恢复、production
role bootstrap/migration ordering 和 SQLite dump/flush/loaddata 对账也通过；SQLite 证据为 563 张表、源/目标 291 行、
fixture 291 个对象、mismatch 0。相同 SHA 的 Architecture `37056214859` 与 Security `37056214750` 通过。

未验证风险：相同 SHA 的 Consistency `37056214883` 与 CI Fast Feedback `37056214838` 被本片前已存在的
`unregistered_script_entrypoint:scripts/manage_vps_migrations.py` 阻断；该脚本来自早期提交 `31cfbfad5` / `e1f632dbc`，
不属于用户限定的①→⑤剩余切片。本轮按“发现新问题只记录未完成工作、不得顺手修”保留失败，没有登记该入口或改写治理
真源。因此五组 exact-SHA CI 仍不是全绿，候选不得进入 S6、部署或生产全市场重跑。数据库级 candidate member
immutability trigger/constraint 仍是既有 P1 风险，本片未扩边处理。

下一片是否可开始：①→⑤实现与 PostgreSQL/SQLite 核心证据已完成复验，没有新的顺序切片可开始。必须先在独立授权范围
处理 legacy entrypoint 治理阻断并取得 exact-SHA 五组 CI 全绿；随后仍须由用户单独授权⑥。当前继续保留 legacy relation
locks，不部署、不接新的 production composition、不启动全市场重跑。

#### 2026-10-03 Migration runner 入口治理阻断整改（`cc9a39b44`）

完成项：`manage_vps_migrations.py` 是部署和 PostgreSQL/SQLite 演练共用的正式 runner，并非待退役 legacy 入口；阻断根因是
入口投影只看到两个运行时选择的 `dynamic-command`，同时缺少该脚本的运维生命周期和受控 Data Center 私有能力审计。
runner 现在把既有 allowlist 显式展开为 `migrate`、`flush`、`loaddata` 三条静态命令边，仍由同一 allowlist 拒绝其他命令；
只有 `loaddata` 分支取得 candidate-manifest fixture restore capability。入口扫描器新增通用的
`execute_from_command_line(["manage.py", ...])` 静态模式，治理真源分别把 runner 记为 `active_public` 运维入口、把唯一私有
导入记为 `adjacent_operational`，并登记现有恢复契约测试；生成投影从 `candidate-review=2` 收敛为 0。测试固定三条命令边、
脚本双重生命周期和唯一允许的 Data Center 私有导入，后续增加命令或私有依赖会失败关闭。

测试计数：角色隔离、snapshot restore、入口治理和 legacy 扫描联合回归 `44 passed`；最终入口/legacy 契约复验
`27 passed`，额外私有导入聚焦反例 `1 passed`。两份改动脚本增量 mypy 零回归，全仓 mypy debt
`0 errors in 0 files`；Black、isort、Ruff、治理一致性、entrypoint stale-check、Architecture full 3,306 files / delta、
module map 44 modules / 210 edges、module cycle 与 `git diff --check` 全部通过。无测试跳过。

exact-SHA 证据：包含上述实现和本节台账的 `8f21c897398999eb903fd4c471e714b04d8423ae` 五组 CI 全绿：CI Fast
Feedback `37088698350`、Publication PostgreSQL contracts `37088698321`、Architecture `37088698284`、Consistency
`37088698282`、Security `37088698283`。Publication workflow 再次通过 5,001-member publication/authority soak、生产角色
bootstrap/migration ordering、statement logging 正常与失败恢复，以及真实 runner 的 SQLite dump/flush/loaddata；快照为
563 张表、源/目标 291 行、fixture 291 行、mismatch `{}`、`outcome=success`。

未验证风险：本片仍未执行 S6、部署或生产全市场重跑；数据库级 candidate member immutability trigger/constraint 仍是既有
P1 风险，本片未扩边处理。

下一片是否可开始：①→⑤和入口治理阻断的本地及 exact-SHA CI 门槛已齐，可以在用户单独授权⑥后开始 S6。当前继续保留
legacy relation locks，不部署、不启动生产全市场重跑。

#### 2026-10-03 ⑥首次生产重跑阻断与模型行情路由能力整改（`6299ae299`）

完成项：精确候选 `2eb462b29708e3136123feb060f5716d90c257e7` 已通过五组 CI、九阶段 S6、同 SHA
预构建镜像与 handoff receipt 部署；部署后独立校验通过 HTTPS/health、PostgreSQL runtime role、ASGI 连接策略、
migration、Data Center schema、TUI metadata、Qlib identity、Celery worker/beat 及运行镜像身份。唯一一次生产全市场任务
`e14eed07-0f03-402c-968c-3a62b4177e3d` 返回规范业务结果 `partial`：`requested=5572`、
`succeeded=5561`、`failed=11`、`stored=11133`；quote 56/56、5,572 行，valuation 56/56、5,561 行，
publication 0/1，`publication_updated=false`，稳定阻断码为 `MODEL_MARKET_BULK_PREPARATION_REQUIRED`。

根因不是 audit authority 锁竞争：生产策略以 Tushare 为主源并启用 AKShare failover；Tushare 实现审计批量准备，AKShare
实现审计逐证券准备。原预检在 provider I/O 前要求每条启用 route 都具备批量能力，导致完整覆盖范围的合格主批量源也被
备用源的能力形态提前否决。`6299ae299` 将大范围预检绑定到实际首选 route；首选 route 仍必须具备批量审计能力，完整批量
结果不会再因未使用的逐证券备用源被拒绝。批量主源失败、无 provider identity、截断批次、缺审计、超出显式逐证券预算等
路径继续 fail closed；未放宽 freshness、coverage、audit 或策略阈值，也未写死 11/12 只证券。

测试计数：model-history 聚焦测试 `19 passed`；market publication 与 5,001 证券规模组件回归 `97 passed`，合计
`116 passed`。新增契约证明“批量主源 + 审计逐证券备用源”在主源完整覆盖时只调用主源，不产生备用源请求；既有反例继续
证明逐证券主源面对 5,001 范围在零 provider/audit I/O 前失败关闭。生产文件增量 mypy 零回归，全仓 mypy debt
`0 errors in 0 files`；Black、isort、Ruff、current-data 72 surfaces 与 `git diff --check` 通过。仓库约定的
`agomtradepro` Conda 环境在当前主机不存在，因此测试使用当前 Python 3.13.5 / Django 5.2.12 环境；这是本地环境差异，
exact-SHA CI/S6 仍须用规定运行时复验。

未验证风险：`6299ae299` 尚未取得 exact-SHA 五组 CI、九阶段 S6、同镜像部署和第二次生产重跑证据；第一次任务已完成的
事实写入不等于正式 Publication，current pointer 仍未更新。逐证券备用源的动态缺口预算目前没有生产 Config Center 真源，
因此本片没有擅自设置固定数量或扩大逐证券调用；主批量结果中无法证明为停牌的剩余缺口仍会明确失败关闭。该配置能力列入
未完成工作，不作为本次正式发布门槛的旁路。

下一片是否可开始：可以开始 `6299ae299` 的 exact-SHA CI 与 S6；只有全部门槛通过后才能用其同 SHA 预构建镜像部署，
再启动一次显式全市场重跑。任何失败先诊断，禁止复用旧镜像、盲目重跑或扩大 timeout/retry。

#### 2026-10-03 发布验证流水线提速与生产策略一致性左移（`7615d44c5`、`b8e523fca`、`01839c967`、`cea02c7ee`、`8df1b1b66`、`23d575a03`、`d2d805bdd`）

背景：用户指出单轮"CI → S6 → 部署 → 全市场重跑"约 8-10 小时太慢。本组改动只做并行化、缓存、
条件化与缺陷左移，不降低任何门禁强度、不删测试、不放宽阈值；六个 commit 组均可独立回滚。

完成项：

1. **CI 提速（`7615d44c5`）**：Architecture/Consistency/Security 三个 workflow 补 concurrency 组
   （cancel-in-progress）；`incremental-quality` 的 npm/playwright 改为仅在 TUI 范围变更时执行，
   mypy 增加 `.mypy_cache` 缓存；`run_incremental_domain_coverage.py` 的逐包串行 pytest-cov 子进程
   改为 ThreadPoolExecutor 并行（每包独立 `COVERAGE_FILE`，全部跑完再汇总失败）；ci-fast-feedback 与
   architecture 增加 docs-only paths-ignore。Consistency/Security 保持全量触发（治理/密钥检查不随
   docs 变更跳过）。fast-feedback 未启用 pytest-xdist：干净树验证（17,463 passed / 44 failed in
   14:37）后串行复验确认约 8 例失败属于测试间顺序/全局状态依赖（如 risk_center scenario_models、
   event_bus 全局单例）， blanket 并行会引入假红，维持单进程；该项留作测试卫生专项，不抢跑。
2. **S6 后三段并行（`b8e523fca`）**：provider_probe 之后的 response_replay /
   full_universe_capacity / isolated_postgresql_write 改为 ThreadPoolExecutor 并行；
   checkpoint.complete 严格按 stage_order 顺序在主线程执行，前缀有序不变量保持；隔离库容器身份
   复核前移到组启动前。失败语义不变，兄弟段跑到自然结束。
3. **部署链路重叠（`01839c967`）**：预部署备份（只读 pg_dump/BGSAVE，对旧 release）提前到远端
   `docker build` 期间执行，部署段仅在备份身份与 PREVIOUS_RELEASE 匹配时跳过重复备份；镜像 tar
   回传与远端部署以独立 SSH 连接并行；`check --deploy`+`collectstatic` 与 AI capability catalog
   同步并行。回滚 trap、身份复核、健康轮询逐字未动。明确否决了"构建期间提前启动 postgres/redis"
   （会替换正在服务旧栈的数据库容器）。顺带修正 `test_data_center_0085_rollback_compatibility.py`
   一处 HEAD 上就失败的断言（脚本实际为 `sh` 而非 `bash` 调用）。
4. **生产发布前分钟级预检（`cea02c7ee`）**：新增只读 `preflight_full_market_publication`
   command + Application 用例：provider 策略/路由批量能力（复用 `6299ae299` 修复的
   `evaluate_model_market_bulk_preparation` 纯函数，与生产 preparation 共用同一实现）、三组 dataset
   发布门（policy/freshness/preview dry-run）、authority capture 装配、task attempt 链路；全部检查
   执行完再汇总，输出稳定阻断码 JSON。零数据库写入、零 provider I/O。
5. **预检快照绑定（`23d575a03`）**：`--provider-settings-json` 显式快照覆盖 Config Center 读取，
   `provider_settings_sha256` 写入证据；`--checks` 支持子集执行（canonical 顺序校验）。
6. **S6 生产策略一致性段（`d2d805bdd`）**：新增 `production_policy_parity` 段（加入并行组，第
   四成员）：候选容器内以显式生产策略快照执行预检 bulk 门，报告携带快照内容与 sha256；
   `build_release_rehearsal_manifest.py` 与 `validate_release_rehearsal.py` 将
   `release.production-policy-parity.v1` 纳入必需报告集（image-bound + digest-only），validator
   重算快照 hash、要求 route gate 通过；`governance/release_rehearsal_policy.json` 登记
   `required_reports` 并由 validator 比对防漂移。旧 receipt（缺 parity 报告）一律拒绝。

测试计数：S6 编排 `70 passed, 1 skipped`；validator + manifest `94 passed, 1 skipped`；预检
`27 passed`；parity runner `8 passed`；domain coverage 并行 `7 passed`；部署脚本相关
`87 passed, 1 skipped`。全部改动文件 ruff/black/isort 通过；生产文件增量 mypy 零回归；全仓 mypy
debt ceiling `0 errors`；entrypoint inventory 1,291 项 `candidate-review=0`；module map 44
modules / 212 edges；architecture inventory 与 current-data 72 surfaces 通过。

未验证风险：

- **本组改动自身尚未取得 exact-SHA 五组 CI**，CI workflow 变更（concurrency、paths-ignore、
  条件化）只能在真实 push 后验证；paths-ignore 对必需检查的影响需要在下一次 docs-only 提交时
  复核（GitHub 对 path 过滤跳过的必需检查有特定的 pending 语义）。
- S6 并行组、parity 段与部署重叠未在 VPS 真实执行；parity 段需要运维在每次 S6 前准备
  `--provider-settings-json` 生产策略快照（只读导出），该导出步骤尚未脚本化，列入未完成工作。
- `provider_state_repositories.py` 274/250 行超限（`test_data_center_repositories_structure`）、
  `test_tui_action_copy_and_density` 889/871、`test_web_to_tui_candidate_consistency` 与
  evid09 共 4 项失败在本组改动前已存在，按硬边界只记录不顺手修。

下一片是否可开始：本组不改变 `6299ae299` 候选的业务语义，其 exact-SHA CI 与 S6 可以继续；
但下一次 S6 必须携带 `--provider-settings-json` 快照并包含 parity 段证据，旧格式 receipt 不再被
validator 接受。继续不部署、不启动全市场重跑，等待用户授权。

补充（`9ec4e7635`）：上节遗留的"生产策略快照导出尚未脚本化"已关闭。新增只读
`export_provider_settings_snapshot` command，与预检/S6 共用同一 `load_provider_settings_payload`
真源：stdout 即快照文件（digest 摘要走 stderr，可直接重定向），`--output` 排他创建；
blocked payload 原样导出以复现生产阻断而非隐藏。单测 `3 passed`，entrypoint inventory 1,292 项
`candidate-review=0`，增量 mypy 零回归。操作路径已写入 `docs/development/quick-reference.md`
"发布预检与 S6 策略快照"节；`AGENTS.md` §6 表格新增"发布预检/S6 证据段或策略快照"行，
把 `required_reports` 三方同步（policy、manifest builder、validator）固化为改动类型契约。

#### 2026-10-04 过去 18 小时 CI/S6 审计与开发收口（`c5e24857f` 至 `3d295ac45`）

完成项：对测试团队在过去 18 小时提交的 CI、full-market preflight 与 S6 变更逐提交复核，并按根因拆成九个
独立可回滚 commit。`c5e24857f` 把 publication preflight 的 Audit/Task Monitor 跨 App 读取移到
`core/integration` composition，恢复 Data Center 单向依赖和 0 module cycle；`10d1b00e2` 补齐 release bundle
collector 的必需 `production_policy_parity` fixture；`f097169cc` 将 full-universe capacity 独占执行，再并行
response replay、policy parity 与 isolated write，避免写入流量污染 query count、持锁时间和 elapsed 证据；
`f4b496e10` 删除 required workflow 的 docs-only `paths-ignore`，避免 GitHub 把未创建的必需检查永久留在 pending，
并把手工 dispatch 与 push 的 concurrency identity 分离；`3043beb08` 在任何 provider/policy preview 前读取并校验
quote、price、valuation 三条 current publication pointer，无 current pointer 或坏指针以
`CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE` 失败关闭。

`55a077bdc` 在 S6 启动时冻结只读 provider settings 副本，并把 raw-file digest 与 canonical-payload digest 分别绑定到
candidate identity、manifest、parity report、bundle、validator、handoff 和 deploy 再验证；外部文件在 build 后替换、
仅空白变化以及自洽伪造 parity 报告均被拒绝。`efc6bd9eb` 进一步把实际 model-market route 的
`provider_id/source_type` 写入 capability evidence，要求每条路由匹配同一冻结 provider identity；只比较 identities digest
而路由实际指向其他 provider 的自洽报告不再通过。`d80b71ee4` 修复 Ctrl-C 时线程池等待兄弟任务、Docker 子进程残留且
run status 长期显示 running 的问题：活动进程组统一取消、阶段容器定向清理、CLI 返回 130、状态写入
`S6_RUN_INTERRUPTED`，不生成 handoff。`3d295ac45` 把 isolated database preflight 的迁移图/身份查询放入
PostgreSQL `REPEATABLE READ, READ ONLY` 事务；SQLSTATE `25006` 映射为稳定码
`REHEARSAL_WRITE_PREFLIGHT_READ_ONLY_VIOLATION`，使“零写入”由数据库约束而非代码约定保证。

回归证据：跨 App preflight `32 passed`；bundle fixture `4 passed, 1 skipped`；capacity 隔离后的 S6 编排
`70 passed, 1 skipped`；CI workflow 治理 `9 passed`；current pointer preflight `30 passed`；settings identity
绑定组合回归 `261 passed, 3 skipped`；route identity 绑定组合回归 `208 passed, 1 skipped`；中断语义
`74 passed, 1 skipped`；只读 database preflight 单元/编排回归 `107 passed, 1 skipped`。跳过项均为本机 Windows
symlink 能力或显式未启用的 disposable PostgreSQL；新增 PostgreSQL 写入反例已进入 Publication PostgreSQL workflow，
本机运行明确显示“Enable the disposable loopback PostgreSQL test explicitly”，不能计作本地通过。各生产切片增量 mypy
均为 0 回归，全仓 debt ceiling 均为 `0 errors in 0 files`；Black、isort、Ruff、current-data 72 surfaces、module map/
architecture 及 `git diff --check` 按各切片通过。`actionlint` 在本机不可用，因此 workflow YAML 仍须以远端 GitHub Actions
执行结果为准。

根因结论：本轮不是 freshness、coverage、audit 或超时阈值不足，而是五类证据边界缺口：composition 跨 App 反向依赖、
required-check 触发器与 fixture 不完整、性能测量和写入并发污染、快照/实际路由身份未端到端绑定，以及中断/只读语义只靠
约定。所有修复均保持现有业务阈值、provider 配额、lock wait、stage timeout 和 retry 不变，也没有按 11/12 只证券写死
分支。

未验证风险与停止线：上述本地提交尚未 push，因此最终 exact SHA 的 Fast Feedback、Architecture、Consistency、Security、
Publication PostgreSQL 五组 CI 尚无结果；新增 SQLSTATE `25006` 反例必须在 Publication PostgreSQL workflow 真正执行。
S6 parity 证明的是启动时冻结的导出快照，不能感知导出后的实时 Config Center 修改；运维必须在每次 S6 前重新导出，任何
后续策略变更都废弃该次输入并重新开始。最终候选尚未执行 VPS 九阶段 S6、同镜像部署、正式 Publication、decision runtime、
Alpha、API/SDK/MCP、普通用户页面和只读零副作用联合验收；candidate member 数据库级 immutable trigger/constraint 仍是既有
P1 未完成项。本节未部署、未启动全市场重跑。

下一片是否可开始：可以 push 当前最终 SHA 并取得五组 exact-SHA CI；只有五组全绿且 PostgreSQL 反例实际通过后，才可用
该 SHA 的全新 provider settings 导出启动九阶段 S6。CI 或 S6 任一失败先读取安全诊断并修复根因，不复用旧 receipt、
不盲目重跑、不扩大 timeout/retry，也不放宽 freshness、coverage、audit 或 `SIGNAL_WEAK`。

#### 2026-10-04 S6 真实 failover 路由身份契约整改（`f49f02634`）

完成项：候选 `6933d8fe160144e8444e0d6a64fc738e9d5bc6d9` 的五组 exact-SHA CI 全绿后，VPS S6 已通过
build、provider probe、response replay 与 5,572 只全量 capacity。首次 policy parity 以
`PREFLIGHT_MODEL_MARKET_ROUTES_UNAVAILABLE / SystemAuditCompositionUnavailable` 阻断；同候选镜像逐层诊断取得稳定根因为
隔离库复用了旧 rehearsal 数据库，缺当前生产 Config Center active runtime profile（`profile_unavailable`）。已把当前生产
PostgreSQL 3.26 GB 一致性快照经 234,622,886-byte 临时 custom archive 恢复到专属 disposable 数据库，临时归档完成即删除；
候选正式 migrator 入口确认 526 条迁移、无待迁移项，角色 bootstrap 前后均通过。随后 runtime config 读取为 production v19、
Audit writer composition 为 8 个 writer、Account authority preflight 返回当前 v2 bundle，同一冻结 settings 的手工 policy
preflight 通过。

恢复原检查点后，S6 进一步以 `REHEARSAL_PROVIDER_IDENTITY_MISMATCH` 正确失败关闭。根因是既有 identity schema 硬限制为
quote/valuation 两条（生产均为 provider 2），而真实 model-market policy 同时启用 provider 3 AKShare failover；上一轮新增的
“每条 route 必须匹配冻结 identity”校验没有同步扩展 identity 集合，单路由 fixture 因此漏检。`f49f02634` 将契约改为必含
quote/valuation，并按实际 route evidence 自动追加有界 `model_market_route:<provider_id>` 身份（最多 32 条）；新增只读
`export_rehearsal_provider_identities`，从同一 provider settings 快照生成完整集合。S6 输入、parity、response replay、validator、
manifest 与 handoff 继续绑定整个有序集合的同一 digest；伪造 route role、缺 route identity、来源不匹配及输出覆盖均失败关闭。
该实现不写死 provider 2/3 或证券数量，后续 provider 增减和 failover 切换按实际路由自适应。

测试计数：identity/parity/export/S6 launcher/release validator 组合 `198 passed, 1 skipped`，跳过项为 Windows symlink 能力；
entrypoint inventory 与 architecture tooling `38 passed`；增量 mypy 4 个生产文件 0 回归，全仓 debt ceiling `0 errors in 0 files`；
Black、isort、Ruff、module map（44 modules / 210 edges）、Data Center entrypoint inventory（1,293 entries，
`candidate-review=0`）及 `git diff --check` 通过。仓库不存在 `scripts/check_architecture_boundaries.py`，该命令无法运行；已由上述
architecture tooling tests 覆盖现有治理入口。

未验证风险与停止线：`6933d8fe1` 的失败 S6 不可转成部署凭证；`f49f02634` 及本节后续文档提交尚未取得 exact-SHA 五组 CI、
全新 provider settings/完整 provider identities/unit contract、九阶段 S6、同镜像部署和生产联合验收。当前未部署、未启动全市场
重跑，也未调整 freshness、coverage、audit、锁等待、stage timeout、retry 或 `SIGNAL_WEAK`。

下一片是否可开始：可以提交并 push 本节最终 SHA，取得五组 exact-SHA CI；全绿后必须重新导出同一时点的 provider settings
和完整 route identities，重建 unit contract 并启动全新 S6。旧 `evidence-20261004b` 只保留为根因证据，不续接新 SHA。

#### 2026-10-04 S6 正式发布时钟与已有 current graph 整改（`288bf4828`）

完成项：候选 `258531188d03b82728579858a8a87db3a523b7f7` 的五组 exact-SHA CI 全绿，VPS 全新 S6 使用同一
生产只读快照通过 build、镜像身份、provider probe、response replay、5,572 只全量 capacity 与 production policy parity，
随后在 isolated PostgreSQL write 以 `REHEARSAL_WRITE_COLLECTION_FAILED` 失败关闭，未生成 handoff、未部署。绕过管理命令的
泛化包装后取得底层异常 `Publication published_at must be later than current publication`：演练错误地以目标交易日的
`observed_at + 2 minutes` 作为 `published_at`，而真实生产快照已有更晚的 current Publication，严格单调发布不变量正确拒绝
时间倒退。根因属于演练发布时钟与真实快照契约缺口，不是 audit lock、锁等待或 timeout。

`288bf4828` 保留目标交易日作为 fact 的 `observed_at/available_at`，在写事务内用一条 PostgreSQL 查询取得同一个
`clock_timestamp()` cutoff 和当前最大 `published_at`，把 synthetic Publication、knowledge cutoff 与新鲜度判定统一绑定该
数据库时钟；已有 current 时间为空、类型非法或不早于 cutoff 时分别以稳定业务码失败关闭，未放宽 repository 的严格单调
发布保护。演练不再假设空库：写入前保存已有 scope、current pointer 以及 active/pointer-bound publication 的 member 与
coverage graph，synthetic 发布期间 pointer 必须保持不变，外层回滚后 pointer、Publication、member、coverage 必须逐项恢复。
写入计数只统计本次 publication ID，避免把真实快照已有行误算为演练写入。receipt、report 与 validator 新增数据库时钟、
pointer 保留和完整 graph 回滚证据；旧报告或 receipt 缺任一证据、时钟不一致或 receipt/report 不一致均失败关闭。未来
current Publication 的 PostgreSQL 故障注入已加入 S6 candidate regression 必跑集合。

测试计数：release validator/collector/isolated writer 单元回归 `148 passed`；显式空库 disposable PostgreSQL 组件回归
`2 passed in 163.09s`，覆盖完整已有 current Publication/member/coverage/pointer 正例和未来发布时间稳定码反例。生产文件
增量 mypy 2 文件零回归，全仓 debt ceiling `0 errors in 0 files`；Black、isort、Ruff、governance consistency、module map
44 modules / 210 edges 与 `git diff --check` 通过。无测试跳过。current-data 专项检查被并行测试团队提交的来源时间 matcher
投影暂时阻断：治理仍要求已移除的 `_MATCHERS` marker；该问题不由本片引入，本片未混入或覆盖并行改动。

未验证风险：本提交及本节文档后的最终 SHA 尚未取得五组 exact-SHA CI；修复后的全新 S6 尚未执行，旧失败 evidence 和镜像
不可复用。真实快照 graph 可能显著大于组件夹具，仍须由 S6 isolated PostgreSQL write 证明查询规模与回滚证据可接受。
测试团队的 current-data marker 投影必须先独立收口，否则 exact-SHA CI 会失败。本片未部署、未生成 handoff、未启动生产全市场
重跑，也未调整 freshness、coverage、audit、lock wait、stage timeout、retry 或 `SIGNAL_WEAK`。

下一片是否可开始：先等待或独立提交测试团队 current-data 投影收口，并在包含本节文档的最终 SHA 上取得五组 CI 全绿；随后
必须从最新生产只读快照创建新的 disposable 数据库、重新导出冻结输入并启动全新 S6。只有九阶段 S6 和 handoff 完整通过后，
才可使用其同 SHA 预构建镜像部署；任何失败继续读取稳定业务码和安全诊断，不续跑旧证据、不延长 timeout/retry。

#### 2026-10-05 ⑥正式发布失败的模型行情来源身份整改（`df214f445`）

完成项：测试团队收口后的候选 `dbfd098ea6e02048e0961b219ab2180e5f4883a8` 已取得五组 exact-SHA CI
全绿：Consistency `37215872580`、Publication PostgreSQL `37215872577`（39 个 publication tests）、
Security `37215872579`、Architecture `37215872599`、Fast Feedback `37215872637`。VPS 全新 S6 根目录
`/opt/agomtradepro/rehearsals/s6-dbfd098ea-20261005a` 使用最新生产快照、5,572 只动态 universe、三条真实
provider identity 和冻结 settings 通过九阶段，生成 candidate SHA、镜像
`sha256:0f3b2c106198bdb79cf8e0b7f05daa098ccde23d2d43f4ec4f960dbde6b5a413` 与 handoff receipt 三方一致的
部署凭证。部署第一次在任何生产切换前以 `REHEARSAL_GITHUB_TOKEN_UNAVAILABLE` 失败关闭；根因是受保护 runner 环境未进入
部署 validator 进程。加载同一 S6 的受保护 `runner.env` 后独立 validator 通过，随后复用同一预构建镜像完成部署；未重建镜像、
未清空 volume，web/worker/beat/qlib worker、PostgreSQL runtime role、migration、TUI metadata 和 pyqlib 0.9.7 均通过。

本次授权范围内只投递了一次正式全市场刷新：task ID `e19c871a-d0d7-45c1-b3e8-a1e57c09f3e9`，attempt ID
`6d87b312504b4b5b92424a98368a2fad`。Celery 技术状态为 success、retry 0，但规范业务结果为 `partial`：
`requested=5572`、`succeeded=5572`、`failed=0`、`stored=11144`，quote 与 valuation 均为 5,572/5,572；
operation 112/113，publication 0/1，`publication_updated=false`，稳定错误码 `MODEL_MARKET_INVALID`，publication run ID
`254df965-6f2c-4368-83d9-9e8c0449a032`。因此事实完整写入不等于正式 Publication，current pointer 未切换；没有把 HTTP/Celery
成功误报为恢复，也没有盲目投递第二次任务。

生产安全诊断把失败定位到 `prepare_stock_history` 的审计写入校验。真实 provider route 的稳定 `source_type` 分别为
`tushare`、`akshare`，但两个适配器给 `ModelDailyBar.source` 传入了可变展示名称 `Tushare Pro`、`AKShare Public`；
`record_model_history_fetch_success` 按 provider 配置要求每行来源严格等于稳定 source type，因而整批规范化历史行以
`MODEL_MARKET_INVALID` 正确失败关闭。日志末尾集中出现北交所代码只是处理顺序的表象；只读 Tushare 截面复核为 daily 5,572
唯一证券、adj_factor 5,572 唯一证券、无缺失/重复/非法 factor。根因属于 provider 身份维度混用，不是 11/12 只证券特例、
audit lock、行情覆盖、超时或 retry 预算。

`df214f445` 将 Tushare/AKShare 两个 model-market 装配点统一绑定 `provider_source()`；展示名继续用于人类可读 provider 名称，
事实、路由和审计使用规范 source type。新增真实适配器行为契约先在旧实现上稳定红测，分别观察到 `Tushare Pro` 与
`AKShare Public`，修复后两者分别输出 `tushare` 与 `akshare`。既有审计正例继续证明规范来源可写入，反例继续证明来源类型
不匹配以 `MODEL_MARKET_INVALID` 失败关闭；没有降低校验或增加展示名白名单。

测试计数：适配器、model-market、历史准备和价格审计联合回归 `108 passed`；Celery 治理脚本通过（94 个登记任务、21 个
exemption、24 个 governed file），对应 guardrail 测试 `13 passed`；current-data 72 surfaces 通过。两个生产文件增量 mypy
零回归，全仓 mypy debt `0 errors in 0 files`；Black、isort、Ruff 与 `git diff --check` 通过，无跳过项。

未验证风险与停止线：`df214f445` 及本节文档后的最终 SHA 尚未 push，也尚无五组 exact-SHA CI；旧
`s6-dbfd098ea-20261005a` 的 receipt、镜像和已部署 release 不包含本修复，不能复用为下一次部署凭证。正式 Publication、
decision runtime、Alpha、API/SDK/MCP、普通用户页面与只读零副作用联合验收仍未通过。不得在这些证据前重跑生产任务，
也不得放宽 freshness、coverage、audit、来源一致性、锁等待、timeout/retry 或 `SIGNAL_WEAK`。

下一片是否可开始：可以提交本节台账并 push 最终 SHA，取得五组 exact-SHA CI；全绿后必须用新 SHA、最新生产只读快照和
重新导出的 provider/settings/unit-contract 输入运行全新九阶段 S6。只有新 handoff receipt 完整通过后才能部署其同 SHA
预构建镜像，再投递一轮显式全市场刷新并执行联合验收；任何失败先保留稳定业务码和证据再修根因。

#### 2026-10-05 正式发布日线收盘时间投影整改（`d967c6efc`）

完成项：候选 `8558cbd6a0d9736b8882654c08dd796be1dde504` 已取得五组 exact-SHA CI 全绿，并以最新生产快照完成
九阶段 S6；同 SHA 预构建镜像、handoff receipt 与部署运行镜像一致。部署后 preflight 的 provider route、current
publication gate、完整 Account authority capture、5,572 只 quote/price/valuation preview 均通过。授权范围内只投递一次
正式全市场刷新，task ID `2df6470b-60c2-4557-9731-321ff7eb6171`，远端 dispatch receipt SHA-256 为
`cf58197085a72c38b6e17062faa649f5c182742620a40f60e56195c6ff69b0be`。任务返回规范业务结果 `partial`：
`requested=5572`、`succeeded=5572`、`failed=0`、`stored=11144`；quote 与 valuation 均为 5,572/5,572，
publication 0/1，`publication_updated=false`，稳定码 `MARKET_PUBLICATION_VALIDATION_FAILED`。技术状态 success 未被当作恢复。

底层安全诊断为 `Current market publication contains an observation before the official China-market close`。本次新写入的
5,572 条 quote 全部精确为 `2026-09-30 07:00:00+00:00`（北京时间 15:00），无 14:55 或更早记录；失败也不是 audit
lock 或少数证券缺口。根因是日线 `PriceBarModel.bar_date` 的 canonical publication identity 仍使用
`cn_market_date_start_utc()`，把一个已完成交易日投影为北京时间 00:00，而 target-session publication 门禁已正确要求官方
15:00 收盘。S6 的 PostgreSQL historical snapshot 仍使用同一旧投影，导致演练与生产共享该盲区。发布前 pointer 基线为空，
失败后 quote、price、valuation pointer 仍为空，没有部分 activation。

`d967c6efc` 将 canonical daily-price identity 与 S6 historical snapshot 的 price 投影统一为
`cn_market_session_close_utc(bar_date)`；quote、valuation、fund NAV、capital flow 等其他时间语义不变，price natural key、
raw payload hash 与 revision identity 也不变。current-data 两条治理 marker 同步到官方收盘函数。红测先稳定观察到两条旧值
均为 `2026-09-10 16:00:00+00:00`，期望 `2026-09-11 07:00:00+00:00`；修复后 canonical identity 和 isolated snapshot
均通过。15:00 门槛、freshness、coverage、audit、锁等待、timeout/retry 与 `SIGNAL_WEAK` 均未放宽。

测试计数：current-publication/Data02 单元 `45 passed`；完整 fact identity 组件 `19 passed`；full-market、preflight、capacity
与 isolated-write 回归 `165 passed`；repository 组件 `34 passed`；current-data runner/guard `10 passed`；price publication
回归 `5 passed`。current-data 治理检查为 72 surfaces；两个生产文件增量 mypy 零回归，全仓 debt ceiling
`0 errors in 0 files`；Black、isort、Ruff 与 `git diff --check` 通过，无跳过项。

首次推送后的 Consistency `37245827307` 中，业务、current-data 与 MCP 治理步骤全部通过，唯一失败为 deterministic Data
Center architecture inventory 过期。生成器复核显示只因两个生产文件新增 import 行导致既有命中行号平移，计数保持
`current_surface_references=5381`、`cross_app_orm_imports=48`、`direct_data_center_imports_outside_data_center=0`；已使用
`python scripts/data_center_architecture_inventory.py --write` 重新生成，并以无参数 check 通过，没有手工改写投影内容。

未验证风险与停止线：`d967c6efc` 及本节文档后的最终 SHA 尚未取得五组 exact-SHA CI；旧 S6 receipt、镜像和当前已部署
release 不包含本修复，不能作为新部署凭证。必须以最终 SHA、最新生产只读快照和重新导出的 provider/settings/unit-contract
启动全新九阶段 S6；全绿并同镜像部署前不得再次启动生产全市场刷新。正式 Publication、decision runtime、Alpha、
API/SDK/MCP、用户页面和只读零副作用联合验收仍未完成；生产没有普通角色测试账户，普通用户权限隔离继续作为补充验收项。

下一片是否可开始：可以提交并 push 本节最终 SHA，取得五组 exact-SHA CI；全绿后执行全新 S6、同镜像部署，再投递一轮
显式全市场刷新。任何失败继续先读取稳定业务码和安全诊断，禁止盲目重跑、复用旧证据或扩大 timeout/retry。

#### 2026-10-05 ⑥全市场刷新事实写入锁竞争根因整改（`ab1ffc4b7`）

完成项：候选 `e8ab5dc6373f00626432b2832710121840c87110` 的五组 exact-SHA CI 和全新九阶段 S6 已通过，
并以 handoff receipt 绑定的同 SHA 预构建镜像完成部署。部署后 preflight 的 provider route、三组 current publication
preview、5,572 只 quote/price/valuation 覆盖、完整 Account authority capture 和 task attempt identity 均通过。授权范围内
只投递一次正式全市场刷新，task ID `689775f6-66d9-47a2-8c3e-b86f5748e382`、attempt ID
`cb2e5720bc8e4fd7afff8fd93876971b`。任务先完成 valuation 5,572/5,572，再在 quote 第 6/56 批后以 PostgreSQL
`canceling statement due to lock timeout` 失败；quote 已写 600 行，没有执行 Publication activation，三条 current pointer
仍未切换。该技术失败没有被误报成业务恢复，也没有盲目投递第二次任务。

生产 traceback 精确落在 `QuoteSnapshotRepository.bulk_upsert` → `upsert_publication_safe_facts` →
`publication_fact_write_lock` 的 `LOCK TABLE data_center_quote_snapshot IN SHARE ROW EXCLUSIVE MODE`。同一窗口内例行
`refresh_decision_quote_snapshots_task`（task ID `bc85858a-e2e9-4129-bfae-384b280f1023`）正在写入 2 条决策行情；两个
事务即使证券自然键不相交，也会被同一个表级排他写锁串行。后者总运行约 47 秒，其中大部分时间处于前序表锁队列，取得锁后
又让全市场下一批超过既有 5 秒 lock timeout。根因是事实写入锁粒度过大并把整段同步 UOW 纳入表锁生命周期，不是 Audit
authority、freshness、coverage、provider 缺口、12 只证券、15:00 收盘规则或 timeout/retry 预算不足。

`ab1ffc4b7` 将 publication-safe 写入改为两级 PostgreSQL 事务 advisory fence：同事实表的写入者取得共享表 fence，
因此不相交的决策行情与全市场批次可以并行；每个规范 source natural key 另取独占 fence，继续序列化同键缺失插入和更新。
单条及三组 Publication activation 在锁 pointer、candidate、member 和 fact row 之前，以规范表顺序取得同表独占
fence；等待受调用方既有 lock timeout 与 5 秒上限的更严格者约束，超限即失败关闭并回滚。现有 fact row locks、Account fence 和所有 legacy
relation locks 原样保留。writer 的 5 秒 lock timeout 上限、freshness、coverage、audit、来源一致性和 `SIGNAL_WEAK`
均未修改；实现按模型表和真实 natural key 自适应，不包含证券数量或代码白名单。

测试计数：新增真实 PostgreSQL 故障注入 `3 passed in 2.80s`，证明不相交 writers 在 1 秒硬阈值内并发完成且 fast path
固定 5 条查询、activation 在 writer 占用时 2 秒内失败关闭并在释放后恢复、同 natural key writers 仍互斥；相关发布事实、
仓储、单条激活与 composition 回归分别 `36 passed, 3 skipped` 和 `38 passed`，跳过项仅为未显式启用 disposable PostgreSQL，
随后已由上述真实 PostgreSQL 运行补齐。5,001-member activation 查询数为 29，低于 35 硬阈值；本机 Windows/Python 3.13
冷容器两次持锁时间分别为 3.665353 秒和 2.634640 秒，均未满足既有 2 秒停止线，因此明确记为本地未通过，未提高阈值，
必须由 exact-SHA Linux Publication PostgreSQL CI 复验。5 个生产文件增量 mypy 零回归，全仓 mypy debt `0 errors in
0 files`；Black、isort、Ruff、current-data 72 surfaces、governance 0 violations、Data Center architecture inventory
（5,381 current references、48 cross-app ORM imports、0 外部直连）与 `git diff --check` 通过。CI workflow 将新增 3 个
PostgreSQL 用例纳入必跑集合并把不可跳过计数从 39 更新为 42。

未验证风险与停止线：`ab1ffc4b7` 及本节文档后的最终 SHA 尚未 push，五组 exact-SHA CI 未执行；尤其 5,001-member
Linux 持锁时间必须小于等于 2 秒，否则继续优化临界区，禁止放宽门槛。`test_publication_activation.py` 整文件本地回归另有
24 个既有 group fixture 在候选 staging 阶段失败：日线成员已按官方 15:00 收盘投影，但 fixture 的 publication `as_of`
仍早于成员 observation；失败发生在新增锁代码之前，作为测试夹具未完成工作单独保留，不在本片顺手修改。新 SHA 尚未执行
全新 S6、同镜像部署、生产重跑或正式 Publication/decision runtime/Alpha/API/SDK/MCP/普通用户页面联合验收。

下一片是否可开始：可以提交本节台账并 push 最终 SHA；只有五组 CI 全绿且 Publication PostgreSQL 的 42 个用例全部执行、
5,001-member query count/持锁时间/lock wait 三条硬阈值均通过，才能以新 SHA、最新生产只读快照和重新导出的
provider/settings/unit-contract 启动全新 S6。S6 与同镜像部署通过后才允许再投递一次显式全市场刷新；任何失败继续先保存
稳定业务码和安全诊断，禁止盲目重跑、延长锁等待、扩大 timeout/retry 或降低业务门槛。

补充（`5f20ef1eb`）：候选 `9c4826e61b0d0ab099d92bf288f6fbf1d14ed11d` 的 Security
`37256299254` 与 Architecture `37256299319` 通过，Publication PostgreSQL `37256299219` 为 `41 passed / 1 failed`。
唯一失败是既有 concurrent group activation 契约：新增独占 fact fence 正确选出一个 winner，但 loser 的底层
`OperationalError` 越过 repository，被 Account fence 包装为 `AccountAuthorityFinalRevalidationUnavailable`；首次归一化为
`PublicationActivationError` 后，立即拒绝语义仍早于 pointer CAS，测试要求的稳定 `compare-and-swap` 业务拒绝丢失。
`5f20ef1eb` 将单条和组激活的 fence 异常统一映射到 `PublicationActivationError`，并把 activation 独占 fence 改为受调用方
既有 lock timeout 与 5 秒上限更严格者约束的等待；并发 activation 因而先由 winner 完成原子切换，loser 随后在既有 pointer
CAS 返回稳定业务拒绝。writer 超过预算时仍失败关闭，不增加 timeout/retry。真实 PostgreSQL 聚焦复验为 `4 passed`，覆盖
concurrent group CAS winner/loser 与三条 writer/activation fence 故障注入。该补丁尚未取得最终 exact-SHA 五组 CI，继续
禁止 S6、部署和生产重跑。

补充（`18e020de3` / `ae775aa2d` / `96c82b6fe`）：候选
`fc4234454dd2300ddca335a85c97f8ca16602c7d` 的 Security `37257345168`、Architecture
`37257345174` 和 Publication PostgreSQL `37257345101` 已通过；后者确认并发 activation 的 winner/loser
仍按 pointer CAS 返回稳定业务拒绝。Consistency `37257345132` 与 Fast Feedback `37257345165` 失败。
安全日志把失败限定为三个独立问题：新增 PostgreSQL 故障注入文件尚未进入 Data Center entrypoint 投影；日线官方
15:00 收盘投影生效后，group activation fixture 仍用当天日期并在收盘前构造未来 observation；writer lock token
错误复用 publication identity builder，使原本允许缺少 `observed_at` 的估值 repository fixture 被额外发布校验拒绝。

`18e020de305b75d49f82256179924b984795a675` 将 writer fence token 改为直接编码各 repository 已声明的
natural key，按类型和 JSON 边界生成确定性、无拼接碰撞的输入；它不增加发布资格校验，也不改变自然键或事实写入语义。
`ae775aa2d1ce881bf06649b97f523fe6adfd42e1` 把 price fixture 固定为前一完整日，并令 publication `as_of`
覆盖最晚 member observation；生产侧“未来 observation 失败关闭”和官方 15:00 收盘门槛未修改。
`96c82b6feca239a995e77595ef893a8361ae308a` 仅重新生成 Data Center entrypoint 投影，登记新增真实 PostgreSQL
故障注入证据；architecture 投影随生产 import 行号变化同步生成，计数仍为 5,381 current references、48 cross-app ORM
imports、0 外部直连。

测试计数：估值天然键聚焦回归 `1 passed`；publication activation 与 published-fact refresh 合并回归
`51 passed`，最终三文件合并回归 `52 passed in 70.21s`。本轮使用 `--nomigrations` 避免 Windows 本地完整迁移图的
启动开销；迁移本身未修改，完整迁移与 PostgreSQL 行为由 exact-SHA CI 继续验证。增量 mypy 生产文件 0 回归，
全仓 debt ceiling `0 errors in 0 files`；Black、isort、Ruff、current-data 72 surfaces、governance 0 violations、
entrypoint/architecture 生成后 check 与 `git diff --check` 通过。无测试跳过。

未验证风险与停止线：上述三个提交及本节文档后的最终 SHA 尚未取得五组 exact-SHA CI；尤其 Publication PostgreSQL
必须继续执行 42 个用例并满足 5,001-member query count、持锁时间和 lock wait 既有硬阈值。未运行新 S6、未部署、
未再次投递生产全市场任务。旧 S6 receipt、镜像和当前生产 release 均不包含这些修复，禁止复用；不得扩大 timeout/retry、
延长锁等待或放宽 freshness、coverage、audit、来源一致性、15:00 收盘和 `SIGNAL_WEAK`。

下一片是否可开始：可以提交本节台账并 push 最终 SHA，等待五组 exact-SHA CI。只有五组全绿后才能用最新生产只读
快照和重新导出的 provider/settings/unit-contract 启动全新九阶段 S6；S6 与同镜像部署通过后才允许投递一次新的显式
全市场刷新并继续正式 Publication、decision runtime、Alpha、API/SDK/MCP、普通用户页面与只读零副作用联合验收。

#### 2026-10-05 ⑥价格停牌探针与最终业务结果投影整改（`e5c09bfc5` / `3d0ea139c`）

完成项：最终候选 `1f696704b3fe7e6b85b1f2fae877c770305fc653` 已取得五组 exact-SHA CI 全绿：
Consistency `37259308415`、Architecture `37259308359`、Publication PostgreSQL `37259308399`、
Fast Feedback `37259308379`、Security `37259308389`；PostgreSQL workflow 实际执行锁故障注入、5,001-member
query count/持锁时间/lock wait 硬门槛及 SQLite 快照演练。VPS 全新 S6 根目录
`/opt/agomtradepro/rehearsals/s6-1f696704b-20261005a` 使用最新生产只读快照、5,572 只动态 universe、完整真实
provider identities 和冻结 settings 通过九阶段，handoff receipt SHA-256 为
`c29dab7f31e12ffb969d181608fbd10b5bd0ebad526622c7e1c3c936c758177d`，同 SHA 预构建镜像
`sha256:4758948766beb1b644aea0d4aab91344e72fbaef05868ab0af6b02ad1c615015` 完成部署；运行 source/image、
PostgreSQL role、526 条迁移、TUI metadata、provider token readiness 和 production statement logging 逐项复核通过。

本次授权范围内只投递一次全市场刷新：task ID `9af9deaa-148b-4df1-96b6-866f6a659ead`、attempt ID
`ef451a53c1784b66ab78e702f5bd5921`、publication run ID `44d9c519-f178-48a3-a89d-bd9f1c658f7b`。任务历时
3,259.208 秒，quote 56/56、valuation 56/56，规范业务结果为 `partial`，
`requested/succeeded/failed/stored=5572/5572/0/11144`；publication 0/1、`published_members=0`、
`publication_updated=false`，稳定错误码 `MARKET_PUBLICATION_VALIDATION_FAILED`。Celery 技术状态虽为 SUCCESS，未被
视为恢复；三条 current pointer 仍为空，没有部分 activation。安全证据保存在
`/opt/agomtradepro/rehearsals/production-refresh-9af9deaa-148b-4df1-96b6-866f6a659ead/final-business-result.json`，
SHA-256 为 `180d967ad7d6fbd89048cb76f0aeb03ec30724a93313e588345d63c4d98709b5`。

底层 traceback 精确落在 `CurrentPublicationRebuildUseCase._select`，异常为
`Market suspension scope requires a target-date observation probe`。全市场编排会把目标日价格停牌排除传给
`equity.price.bar`，重建器按既有 fail-closed 规则要求 candidate repository 证明被排除证券没有目标日价格事实；生产
`PriceBarRepository` 没有实现该 Protocol，而 quote repository 已实现。S6/replay 只覆盖 quote suspension，单元 fake
repository 又普遍自带 probe，导致真实 price composition 缺口未被发现。`e5c09bfc5e15ba14ff5c0392f60ee9808629b4d3`
为价格仓储补充精确 `bar_date` 的日线/分钟线探针，周线/月线不作为当日成交证明；生产 bundle 组合测试同时证明无目标日事实
时可预览、发现冲突时继续失败关闭。实现按请求证券和日期查询，不包含固定证券名单，也未调整 freshness、coverage、audit、
15:00 收盘、锁等待、timeout/retry 或 `SIGNAL_WEAK`。

同一次运行还暴露 Task Monitor 的独立系统性缺陷：Celery backend 保留完整业务 dict，但 postrun 使用
`str(retval)[:10000]`，截断点落在大型 raw-audit 数组中，持久结果长度恰为 10,000 且 JSON/repr 均不可解析，页面/API
最终只剩技术 `success`。`3d0ea139c319347f0cd8b0e570f03ab869f91221` 将超长结果改为确定性有界业务投影，保留 outcome、
四项计数、phase/phase_results、稳定错误码、阻断原因、publication_updated/run ID、最多三组 publication ID 与每数据集
ID/hash/member count/policy/source time 摘要；raw audit、scope blocks 和证券清单不进入 Task Monitor。普通小结果仍保留既有
表示，未通过扩大字段或隐藏截断来规避问题。

测试计数：价格 repository/current-publication 回归 `46 passed`，生产 composition 回归 `12 passed`；Task Monitor
unit/API 回归 `65 passed`。价格生产文件及 Task Monitor 三个生产文件的增量 mypy 均为 0 regression，全仓 mypy debt
ceiling 为 `0 errors in 0 files`；Celery 治理检查 94 个登记任务通过；Black、isort、Ruff 与 `git diff --check` 通过。
新价格探针反例和超长 partial 结果反例均先在旧实现稳定失败后转绿，无跳过项。

未验证风险与停止线：上述两个生产修复提交及本节文档后的最终 SHA 尚未取得五组 exact-SHA CI；旧
`s6-1f696704b-20261005a` receipt、镜像和当前部署不包含这些修复，禁止复用。必须以最终 SHA、最新生产只读快照和新导出的
provider/settings/unit-contract 重新执行完整九阶段 S6，随后只部署其同 SHA 预构建镜像。全绿和部署身份复核完成前不得再次
启动生产全市场任务。正式 quote/price/valuation Publication、decision runtime、Alpha、API/SDK/MCP、普通用户页面和只读
零副作用联合验收仍未完成；financial source-time owner approval 仍须独立取得，不得伪造或自动放行。

下一片是否可开始：可以提交本节台账并 push 最终 SHA，等待五组 CI；全部通过后启动全新 S6。S6 与同镜像部署通过后，
才允许投递一次新的显式全市场任务，并同时从 Task Monitor API 与 Celery backend 对账业务 outcome、四项计数、阶段、
Publication IDs/hash/run ID。任何失败继续先保存稳定业务码和安全诊断，不盲目重跑、不扩大 timeout/retry、不放宽业务门槛。
