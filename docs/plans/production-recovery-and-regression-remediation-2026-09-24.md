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

**2026-10-07 授权更新（Asia/Shanghai）**：用户在 chat `01a1166e-ec55-7fd1-a552-83dce4620f21`
明确回复“R1.2 的第四类：financial 正式发布 │ 需要用户新的明确授权（当前 ceiling 仅 N≤1 预演）；能力本身已在 S6 #4 被真实 provider 双原件证明，卡点纯粹是授权——授权”。
据此，financial 正式发布及其必要的受控生产刷新已获用户授权；下文历史台账中的“financial refresh 未获授权／仍需新的明确授权”
仅描述当时状态，后续不得据此重复索要同一授权。授权不等于已经执行或验收成功：执行前仍须核验候选绑定的 CI、完整 fresh S6、
handoff receipt 与同镜像部署证据，并冻结 provider、资产/公告日范围和请求预算。现有
`governance/financial_sync_request_budgets.json` 的单次 `N<=1 / 2N<=2` 执行上限保持有效；扩大规模须先形成容量证据并完成治理变更，
不得通过循环小批次规避总量评估。用户引用的 S6 #4 双原件证明不能替代本次正式发布的 publication/current identity、来源时间、
完整性与 requested/succeeded/failed/stored 对账。此次授权不改变既有全市场任务禁止重跑、两个周期入口 disabled 的边界。
登记时主发布 chat `01a0d39f-13d8-7990-a75b-baf6f8182e31` 正为候选 `c3e1527bd31d7067c732cdcc9ae395cf9c5ce80a`
准备 fresh S6 attempt `98c8bcbe3bb34f2e9c6c56fb68504bf0`；本次仅登记授权，没有启动第二条部署链或执行生产写入。

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

#### 2026-10-05 ⑥全市场重复投递与停牌候选保存根因整改（`9528afcbe` / `4eddb2242`）

完成项：最终候选 `0539318e00aa493603f525da637098061a02680e` 已取得五组 exact-SHA CI 全绿：
Consistency `37273700340`、Publication PostgreSQL `37273700129`、Architecture `37273700189`、Security
`37273700178`、Fast Feedback `37273700200`。全新 S6 根目录
`/opt/agomtradepro/rehearsals/s6-0539318e0-20261005a` 使用最新生产只读快照、5,572 只动态 universe 和冻结 provider
identity 通过十阶段，handoff receipt SHA-256 为
`a5f55eec06c74328a44fc5cd81454dcfe3d576903e0c187d7a432646c128e41e`，同 SHA 预构建镜像
`sha256:db96f5bd0136d2a80d45e5e7f02c91c5bedbf70c1557c9c35a607d50ce611921` 完成部署。运行 revision、image、
526 条迁移、服务健康、provider readiness、TUI metadata 与生产 statement logging 恢复均通过。部署后 preflight 对
quote/price/valuation 的 5,572/5,572 预览、完整 Account authority capture 与 task attempt identity 均通过。

授权范围内只显式投递一次全市场刷新：task ID `7c54f6d8-a93f-43c3-9a68-a610bcacca8e`、attempt ID
`d153af49544b458299eed0d8271c3993`。任务历时 5,202 秒，quote 56/56、valuation 5,572/5,572，规范业务结果为
`partial`，`requested/succeeded/failed/stored=5572/5572/0/11144`；publication 0/1、`published_members=0`、
`publication_updated=false`，稳定码 `CURRENT_PUBLICATION_STAGING_FAILED`，publication run ID
`5785ca78-ce82-4bcc-9a0b-60df8844d5f5`。Task Monitor 保存了 875 字节可解析的有界业务投影，完整保留 outcome、四项计数、
phase、错误码与 run ID，证明本候选的结果投影修复有效；Celery 技术 success 没有被视为正式恢复。

生产 traceback 将首次失败精确定位到 candidate RawAudit lineage：`candidate fact belongs to a foreign or missing ingestion run`。
根因是 Beat 的同名任务 `1b9b6a55-9e7c-406d-a779-3372d581b6a8` 在显式任务尚未结束时开始执行；其 attempt ID 为
`be0c8a4d19f34bdeb4909a237c102a2b`，配置仍是工作日 17:05 Asia/Shanghai，实际因队列延迟于 17:10:39 开始。
全市场事实写入只有单批事务和 natural-key fence，没有覆盖 provider 读取、56 个批次、candidate staging 与 activation 的
任务级所有权。后启动任务因此在相同 natural key 上替换 `ingested_run_id`；首次任务的 lineage 门禁正确失败关闭，candidate、
pointer 与正式 Publication 均未部分切换。这里没有固定证券数量，也不是延长 lock wait、timeout 或 retry 可以修复的问题。

后启动的 Beat 任务在首次任务结束后继续完成 quote 56/56 与 valuation 5,572/5,572，历时 4,701 秒，最终也返回
`partial`、`requested/succeeded/failed/stored=5572/5572/0/11144`、publication 0/1、稳定码
`CURRENT_PUBLICATION_STAGING_FAILED`。它的底层异常与 lineage 不同：
`Market suspension scope requires selected members`。生产 staging repository 先调用
`CanonicalPublicationRepository.save(publication)` 保存带 quote/price 全天停牌 scope block 的 p2 candidate；该方法在成员尚未
写入且调用方未提供 candidate members 时执行必须依赖成员的 snapshot policy 校验，因而合法的动态停牌分区必然失败。
根因是 candidate 保存契约缺少同一 UOW 的 member evidence，不是 11 只停牌证券特例；整改必须让 candidate metadata 在保存前
使用其完整成员校验，同时保留 scope block、policy、lineage、identity 和原子回滚反例，禁止跳过或放宽停牌政策。

过去 18 小时 CI/S6 改动复核确认，PostgreSQL workflow 已实际运行三个 publication fact writer lock 用例和 concurrent group
activation CAS 用例，但 `scripts/validate_release_rehearsal.py::REQUIRED_POSTGRESQL_TESTS` 尚未列入这四个既有 node id。
因此 CI 能执行它们，S6 candidate regression validator 却不能证明 evidence artifact 必含这些用例；本轮须补齐固定清单并以
validator/collector 缺失与 skipped 反例证明 fail closed。新增全市场任务级 mutex 还须覆盖 manual/Beat 共用入口、竞争者在任何
provider/数据库写入前规范 `noop`、cache 不可用时规范 `blocked`、正常/异常/soft-timeout owner release，以及 lease TTL 严格大于
5,700 秒 hard limit 且严格小于 6,300 秒 authority window 的不变量。不得延长现有任务时间或等待竞争者。

`9528afcbef39adc267f0963c8031920309fda1cc` 在 manual/Beat 共用的 Celery 入口增加 task-wide fail-fast lease。
竞争者在 provider、事实写入和 Publication 前返回规范 `noop`，四项计数均为零，稳定码为
`FULL_MARKET_REFRESH_ALREADY_RUNNING`；lease cache 不可用时返回规范 `blocked` 和
`FULL_MARKET_REFRESH_LEASE_UNAVAILABLE`，不降级为无锁执行。正常、异常和 soft-timeout 路径按 owner identity 释放；进程崩溃
依靠 6,000 秒 TTL 回收。该 TTL 严格大于 5,700 秒 hard limit、严格小于 6,300 秒 authority window，没有延长任务时间、
锁等待或 retry。S6 固定 PostgreSQL 证据清单同时补入三个 publication fact writer lock 用例和 concurrent group activation
CAS 用例，candidate validator/collector 缺少或 skipped 任一必需用例时继续失败关闭。

`4eddb2242795b24ef2b38eadad912bff76558038` 为 candidate repository 增加带完整冻结成员的保存契约；staging 在同一事务内先用
成员验证 policy、coverage、publication/dataset identity、natural key/member/fact 唯一性、`as_of`/observation 边界和停牌
scope block，再保存 metadata 和 members。元数据单独保存、成员缺失、coverage 数量不一致、publication ID 错配、重复自然键、
缺失 `as_of` 或停牌证据不完整均在首行写入前失败关闭；既有 lineage、candidate identity、manifest seal、pointer 与原子回滚
门禁保持不变。实现按候选成员与 scope blocks 动态处理，不包含证券数量或代码白名单。

测试计数：task-wide lease 新增 6 个契约反例；完整全市场刷新单测 `101 passed`；release validator/manifest 单测
`103 passed, 1 skipped`，跳过项为本机 Windows 不支持目录 symlink 的平台分支，不是固定 PostgreSQL 证据。候选保存旧实现红测为 quote/price
`2 failed, 21 deselected`，均稳定复现 `Market suspension scope requires selected members`；修复后 staging component
`23 passed`，版本化 Publication integrity component `11 passed`。current-data 72 surfaces、对应 guard 单测 `6 passed`、module map
44 modules/210 edges、governance 0 violations、architecture delta 0 violations、Data Center architecture inventory
（5,384 current references、48 cross-app ORM imports、0 外部直连）和 entrypoint inventory 1,294 条均通过。两个切片涉及的生产
文件增量 mypy 均为 0 regression，全仓 debt ceiling `0 errors in 0 files`；Black、isort、Ruff 与 `git diff --check` 通过。
本地未执行 disposable PostgreSQL 用例，必须由 exact-SHA Publication PostgreSQL CI 补齐。

未验证风险与停止线：task-wide lease 先覆盖 manual/Beat 的同一 full-market 入口；决策行情最近只写 `510300.SH` 与
`000300.SH`，不在本次 5,572 只 A 股 Publication scope，但其他 API、回填、按需修复或维护 writer 若在全市场运行期间写入
相同自然键，仍可能触发 lineage fail closed，须作为后续共同 writer-fence 风险记录，不能用本次 mutex 证据宣称全部 writer
已隔离。两个修复已经独立 commit 并完成本地门禁，但尚未取得最终文档提交后的五组 exact-SHA CI，也未运行全新 S6、同镜像
部署或第三次生产重跑；旧 S6 receipt、镜像和当前部署均不包含本轮修复，禁止复用。在这些证据齐备前禁止再次投递生产全市场
任务，禁止放宽 freshness、coverage、audit、15:00 收盘、停牌证据、来源一致性或 `SIGNAL_WEAK`。

下一片是否可开始：可以提交本节台账、push 最终 SHA 并等待五组 CI。只有 exact-SHA 全绿且 Publication PostgreSQL artifact
包含新增固定 node id 后，才能从最新生产快照启动全新 S6，S6 与
同镜像部署通过后才允许投递一次新的显式全市场任务，再继续正式 Publication、decision runtime、Alpha、API/SDK/MCP、
普通用户页面与只读零副作用联合验收。

#### 2026-10-06 S6 启动身份与重试隔离整改

根因：候选 `61f53246dc0289268203f471b337b29ca1891d9e` 的首次新 S6 在镜像构建完成后才以
`Timeout waiting for redis at agom-s6-redis-0539318e0:6379` 失败。远端 prepare 脚本由前次脚本复制并以字符串替换旧
namespace；当实际前次候选由 `1f696704b` 变为 `0539318e0` 时，隔离 env 仍指向旧 Redis。第二次同 SHA 尝试又在导出阶段
以 `snapshot output already exists: /tmp/agom-s6-61f53246d-provider-settings.json` 失败，因为临时路径只含 SHA short，
没有一次尝试的独立身份。第三次 prepare 使用新 namespace 后完成，但在本整改完成前停止，没有启动 S6 runner。
这两次失败均发生在生产写入和部署之前，失败证据保留；旧成功 receipt 和镜像继续禁止复用。

完成项（`025417721`）：S6 CLI 现在拒绝仓库外复制的 launcher；隔离 env 必须在任何远端构建前完整、一致地绑定
PostgreSQL host/DB、runtime/migrator URL、Redis host/URL 和显式隔离标记。PostgreSQL 与 Redis 容器必须均为指定网络中
与 host alias 对应的运行实例。旧 namespace、缺失/重复 env key、独立字段与 URL 不一致或关闭隔离标记均返回稳定
`S6_ISOLATED_ENV_*` 业务码，不回显 DSN、密码或原始 env。新增 Redis CLI 参数及恢复文档已同步。

`453d3f8bedc5c6a1b93d168420b2b0e093a631e5` 将远端 build report 从固定共享文件改为 release tag 与随机 128-bit build attempt
共同命名；prebuilt verifier、source upload 和 git clone 三条路径都只接受本次预分配路径，远端回报不一致即失败关闭。下载到
本地的报告使用同一 attempt ID，清理也只删除本次远端报告，因此同 tag 重试或并行构建不再互相覆盖报告或误删证据。
`641bdfd652587edb8b35a1fa40b1bbc1c4b6a9ce` 新增仓库内 attempt 规划器：每次新 S6 使用 UUID4，与候选 SHA 共同派生
root/evidence、PostgreSQL/Redis/network/volume/database 及两个 provider export `/tmp` 路径；`--reserve` 原子创建 root 和只读
计划，既存目录或 symlink 失败关闭；同 attempt 只有显式 `--resume` 且计划逐字节一致时可复用。规划器及其测试已纳入
deployment CI 选测映射。

`17a3415e217844426a7abeda2ca13e7c8bb28ecb` 为每个子命令生成独立 invocation ID；兼容的
`current-command.json` 之外，同时维护活动命令汇总和每 invocation 活动文件。并行成员结束时只移除自身，其他成员继续按约
5 秒心跳；最终各自保存历史。诊断仍只含 label、耗时、预算、字节计数、白名单类别、稳定码与 traceback 位置，不持久化 argv、
env、原始 stdout/stderr 或秘密。

测试计数：`tests/unit/test_run_release_rehearsal.py` 为 `84 passed, 1 skipped`；跳过项是 Windows 不允许创建测试所需
symlink。新增故障注入覆盖旧 PostgreSQL/Redis host、URL、数据库名、隔离标记、重复 key、Redis 容器预检失败和 launcher
来源不一致。`scripts/run_release_rehearsal.py` 增量 mypy 为 0 regression，全仓 mypy debt ceiling 为
`0 errors in 0 files`；Black、isort、Ruff 与 `git diff --check` 通过。

远端报告隔离回归为 `76 passed, 1 skipped`，attempt 规划器与 CI 选测回归为 `71 passed, 1 skipped`；两处跳过均为
Windows symlink 平台分支。两个生产脚本的增量 mypy 均为 0 regression，Black、isort、Ruff 通过。新增反例证明两个 tag、
同 tag 两次 build、同 SHA 两次 S6、路径注入、既存目录、symlink、计划篡改和错误清理均失败关闭或保持资源互不相交。
命令心跳切片回归为 `86 passed, 1 skipped`，新增真实子进程 barrier 与 6.5 秒阻塞反例，证明两个并行 invocation 同时可见、
一个完成后另一个仍保留且心跳推进、最终活动集合归零，并确认 argv/env/stdout 中的 sentinel 没有进入诊断文件；增量 mypy
为 0 regression，Black、isort、Ruff 通过。

最终组合 deployment 回归为 `336 passed, 4 skipped`，覆盖 launcher、attempt 规划器、远端构建/部署、manifest、validator 与
CI 选测；四个跳过项均为 Windows symlink 平台分支。全仓 mypy debt ceiling 为 `0 errors in 0 files`；module map
44 modules/210 edges、governance 0 violations、Data Center entrypoint inventory 1,294 条和 `git diff --check` 通过。入口投影已由
生成器同步远端构建与 launcher 行号，未手工编辑。

未完成工作与停止线：工具链代码片与本地组合门禁已完成，仍须取得最终 SHA 的五组
CI；旧 `s6-61f53246d-20261005a/b/c` 不作为新 SHA 证据，且在新 S6 前只能按精确 manifest 清理其 disposable 资源。

下一片是否可开始：可以执行组合门禁、提交台账并 push；在 exact-SHA CI 和新 S6 成功之前，
不得部署或投递生产全市场刷新。不得以删除旧证据、复用固定 `/tmp` 文件、延长 timeout/retry 或人工放宽身份校验解冲突。

#### 2026-10-06 部署入口契约漂移根因与永久门禁

根因不是 CI 选测漏跑。`55a077bdc` 将 provider settings 的 raw-file 与 canonical-payload 两个摘要加入
S6 runner、manifest、handoff receipt、Python validator 和 Python 部署器，但 PowerShell 一键部署入口仍手工维护一份
validator 参数表，未同步两个新增的 `required=True` 选项。Fast Feedback 已会为 validator 或部署入口变更选中 deployment
测试；原测试只分别验证 validator 核心、Python receipt 绑定和 PowerShell 的旧参数字符串，没有比较 validator 的全部必填
CLI 与每个真实消费者实际组装的参数块。S6 自身不调用 `deploy-vps.ps1`，所以十阶段预演通过也不能覆盖这条调用边。

该故障在 push、凭据临时文件、SSH 与生产变更之前由 argparse 失败关闭；生产部署最终通过已完整校验 receipt 的 Python
部署入口完成，同一预构建镜像与候选身份没有变化。修复提交 `75a258d80` 已为 PowerShell 增加两个摘要输入、格式校验和精确
转发。`e94353fc7` 进一步从 validator 源码自动提取所有 literal `required=True` CLI 选项，并要求 PowerShell 一键部署与 S6
release-validator 的实际参数块全部覆盖；故障注入删除任一必填选项后，门禁必须报告该缺项。该测试位于已有 deployment
selector 的固定测试文件内，因此以后新增 validator 必填项而遗漏任一跨语言消费者时，PR Fast Feedback 直接失败。

这类缺陷的最终收敛方向是版本化 handoff receipt 成为部署证据的单一结构真源：PowerShell 只传 receipt、候选 SHA、镜像 ID
和 manifest digest 等外部期望值，由一个 Python preflight 完成 schema、时效、摘要和消费者绑定并输出安全的规范化结果。
该收敛必须作为生产联合验收后的独立可回滚切片，保留当前两次本地 fail-closed 校验及 Python 部署器的独立复核；迁移完成前
不得删除本次消费者自动对齐门禁。这样既先阻断现有参数漂移家族，也避免在本次全市场任务运行期间改动刚验证过的部署路径。

完成项：部署包装器摘要漏传已修复；新增 validator 必填 CLI 到 PowerShell/S6 消费者的自动对齐门禁与缺项故障注入。

测试计数：`tests/unit/test_remote_build_deploy_vps.py` 为 `83 passed, 1 skipped`，跳过项为 Windows symlink 平台分支；
`tests/unit/ci/test_select_tests.py` 为 `62 passed`。Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险：当前仍有跨语言手工参数组装，自动门禁能阻断必填选项缺失，但不能证明任意未来参数的业务值来源正确；
receipt-only 单一入口尚未实现。该风险只影响下一次候选部署，不改变正在运行的生产刷新或其 Publication 原子性。

下一片是否可开始：当前生产全市场任务和联合验收可继续；receipt-only 收敛须在本轮生产恢复验收后独立开始，且不得借此
重跑 S6、重新部署或再次投递全市场任务。

#### 2026-10-06 生产刷新终态与估值实际来源血缘整改

生产终态：候选 `294ee8354265c84e49f9fd32978f99f738198e15` 已通过五组同 SHA CI；S6 attempt
`eb57a2f97f3947309438fa7625a61a56` 的十阶段全部通过，handoff receipt SHA-256 为
`5d50e1094fb4c5584b60605e0cbfbdb8ca17b08241f18c016857f122813b834a`，预构建镜像为
`sha256:256c35640243b90ce932e7ff050cb326f2740e6fc822de4ad42d89fc15b0da37`。生产使用该同 SHA、同镜像部署并通过
身份复核后，只投递了一次显式全市场任务 `719e7f38-6d42-46c3-b2e2-f58e5739b808`，attempt 为
`e98e2a94637e44c58d0f0392538dcf5c`。Celery 与 Task Monitor 的技术状态均为成功，但规范业务结果为 `partial`：
`requested/succeeded/failed/stored=5572/5572/0/11144`；quote 与 valuation 各完成 5,572 条事实，publication
为 `0/1`、`published_members=0`、`publication_updated=false`，稳定码为
`CURRENT_PUBLICATION_STAGING_FAILED`。quote/price pointer 仍为空，valuation/financial pointer 不存在，未发生部分 activation。
终态安全证据位于
`/opt/agomtradepro/rehearsals/production-refresh-719e7f38-6d42-46c3-b2e2-f58e5739b808/terminal-evidence.json`，
SHA-256 为 `e55396bf107dda8ce1d54f77700ad5831e976b60d929de7fec5840cca7468c35`。

根因：本次动态停牌集合的 11 只证券已经由真实目标日证据隔离，不是发布失败原因；Audit authority 也仍有效。唯一失败血缘为
valuation ingestion run `2ed452d4-f073-4a7c-a3a4-951f8328fa3f`：5,572 条 `ValuationFact.source` 都是实际上游
`tencent`，但 RawAudit `53055` 的 hash-bound `extra.source_type` 写成 provider 配置路由 `akshare`。full-market 又用
`selected_valuation_source=akshare` 构造 staging binding，metadata resolver 因请求和 RawAudit 同为 `akshare` 而通过，最终
repository 将 ingestion→`akshare` 与 candidate member→`tencent` 严格比较后正确失败关闭。既有 S6 分别验证真实 fetch、
response replay、provider identity 与 PostgreSQL publication，却没有贯通真实 adapter→sync→RawAudit→staging，因此没有提前
暴露两个来源维度被混用。

完成项（`db093a293`）：成功 valuation batch 在任何 fact 写入前动态归一并要求唯一实际来源；缺失或混合来源分别返回
`CURRENT_VALUATION_SOURCE_TYPE_INVALID`、`CURRENT_VALUATION_SOURCE_TYPE_CONFLICT`，不维护 provider 对应白名单，也不写死
证券。成功 RawAudit 的 `extra.source_type` 记录实际 fact 来源，`extra.provider_source_type` 单独记录配置路由且一同进入内容
hash；空批次或失败 audit 仍不可进入 Publication。`SyncValuationBatchResult` 显式携带 `fact_source_type`，full-market staging
只用该实际来源建立严格 binding，并在任务业务结果中保留上述稳定码。现有 staging/activation 的 fact-source 严格相等校验未
放宽。

新增 PostgreSQL 固定 node id
`tests/component/data_center/test_current_publication_staging.py::test_valuation_sync_reference_stages_actual_source_and_rejects_route_binding_postgresql`
使用真实 `AkshareUnifiedProviderAdapter` 与确定性 Tencent gateway response，贯通真实 sync UOW、exact RawAudit reference、
production resolver/repository staging；正例证明 route=`akshare`、actual=`tencent` 分列后可以生成 candidate，反例把 route
冒充 actual 时失败且 current pointer 保持空。该 node 已同时加入 Publication PostgreSQL workflow、S6 release validator 必需
清单及证据计数断言；不新增演练阶段。

测试计数：全市场刷新单测 `103 passed`；估值同步单测 `22 passed`；估值 lineage component `9 passed`；新增端到端节点
`1 passed`；release validator 单测 `100 passed`。任务稳定来源码参数化反例 `2 passed`，已包含在上述 103 个用例中。
增量 mypy 覆盖 3 个生产文件且 0 regression；全仓 debt ceiling `0 errors in 0 files`。Black、isort、Ruff、
`git diff --check`、Celery 94 个任务合同与 current-data 72 个 surface 均通过。

未验证风险与停止线：新增端到端节点本地只在隔离 SQLite 下通过，必须由 `db093a293` 后最终文档 SHA 的 Publication
PostgreSQL CI 证明真实 PostgreSQL 行为。生产现有 valuation facts 与 RawAudit 是不可改写的历史证据，不能原地修补；必须在
修复候选通过五组 exact-SHA CI、全新生产快照 S6、同一预构建镜像部署后重新取得一批正确 lineage，再启动新的正式发布流程。
旧 `294ee8354` receipt、镜像与失败任务均不得复用为新代码证据。禁止再次盲目投递全市场任务、改写 append-only RawAudit、
扩大 timeout/retry、放宽 freshness/coverage/audit/source 校验、降低 `SIGNAL_WEAK` 或写死停牌/缺失证券集合。

下一片是否可开始：可以提交并 push 本节台账，取得最终 SHA 的 Architecture、Security、Consistency、Fast Feedback、
Publication PostgreSQL 五组 CI。只有全部通过且 PostgreSQL artifact 包含新增固定 node id 后，才能从最新生产只读快照执行全新
S6；S6 与同镜像部署通过后，才可投递一次新的显式全市场刷新并继续正式 Publication、decision runtime、Alpha、
API/SDK/MCP、普通用户页面和只读零副作用联合验收。

CI 补充证据：`92f07f06d` 的 Consistency run `37372855981` 在 current-data 等前置门禁通过后，由
`data_center_architecture_inventory.py` 以 stale projection 失败。根因是本片新增三个 current-surface 文本引用后漏跑生成器，
不是运行时、来源契约或 PostgreSQL 行为失败。`2ffc3dc37` 已用唯一生成器刷新
`governance/data_center_architecture_inventory.json`，references 从 5,384 变为 5,387，cross-app ORM 48、外部直连 0 等其余
计数不变；本地重新执行生成器 check 通过。该遗漏说明“生产代码门禁通过”仍不足以替代受影响治理投影检查；最终 SHA 必须重新
取得五组 CI，旧 run 中已通过的部分 job 不能单独拼成发布凭证。

#### 2026-10-06 生产 Publication authority outer-fence 根因整改

生产终态：候选 `0fc273d790c7a39addd61be2f733e66a83c12c74` 的五组 exact-SHA CI、S6 attempt
`2057ca35f2d4416e8f3d5b02cfffb2b4` 十阶段和同镜像生产部署均通过。部署后唯一一次显式全市场刷新 task
`4e80d16a-391a-472e-9374-f91146a179aa`、attempt `cb730e492a4e472d8e47e6633d689cb4` 已业务终态
`partial`：`requested/succeeded/failed/stored=5572/5572/0/11144`，quote 与 valuation 均 5,572 条成功，
publication 为 `0/1`、`published_members=0`、`publication_updated=false`，稳定码
`MARKET_PUBLICATION_VALIDATION_FAILED`，run ID `17425453-20eb-4dbd-a0ed-5e287f44ee74`。Celery 与 Task Monitor
技术状态虽为 success，未被视为恢复；lease 已释放，price/quote/valuation 三个 current pointer 仍为空，没有部分 activation。
终态、traceback 与根因摘要保存在
`/opt/agomtradepro/rehearsals/production-refresh-4e80d16a-391a-472e-9374-f91146a179aa/evidence/terminal`；
三个文件 SHA-256 分别为 `cacbfbbddb5adfc12cfbb5094127a9a943799e162d1e901660f974f5861c049b`、
`496d50365707af7bc8161284a36f8b49331670e6978b571a5955b2d084917d6e`、
`2470f2bcdd305b3d5ba1adb0f9095db589801edf85c457127dc6cb734382f642`。

根因：publication group repository 在没有 ambient transaction 时正确进入 finalizer；finalizer 建立唯一最外层 READ COMMITTED
generation fence，并绑定 alias、Django wrapper、物理连接、backend PID、transaction xid 与 generation。随后真实 complete
Account graph 的 `OwnerTenantAuthorityV3Service.get_current()` 调用普通
`DjangoOwnerTenantAuthorityV3Repository.atomic()`，该 repository 即使已有外层事务仍无条件创建 savepoint。actor raw-source
bundle 在该 savepoint 内执行 generation-fence 校验时观察到 `atomic_blocks=2`，按既有 fail-closed 规则抛出
`AccountAuthorityGenerationUnavailable: active generation fence requires the outermost transaction`。因此故障是 production
composition 的 UOW 时序冲突，不是 12/11 只证券、provider 数据、锁等待或 authority 失效；不得通过允许嵌套 fence、延长等待或
放宽校验规避。

完成项（`3c75e9677`）：只为 generation-fenced complete graph 当前读取注入专用 Authority repository UOW。该 UOW 不再创建
savepoint，而是在进入和退出时分别复核 caller-owned fence 的 alias、连接、xid 与 exact generation，并维持不授予写能力的
只读 scope；缺少 fence、代际不一致或重入仍失败关闭。普通 Authority 服务、shadow RR/RO 读取及写入路径继续使用原有独立
`transaction.atomic()`，未扩大调用边界。既有 PostgreSQL finalizer 组件节点现会在真实 generation fence 内执行这一专用 UOW，
并硬断言 `atomic_blocks==1`；该准确 node id 同时加入 S6 `REQUIRED_POSTGRESQL_TESTS`，其 JUnit 文件成为 release validator 的
必需官方 artifact，缺失、跳过或失败都会阻断候选。

复核收紧项（`511b8277d`）：专用 caller-owned read scope 不再激活 Authority repository 的写入 UOW token；任何未来误用
`append`/`append_revocation` 都会因缺少 private UOW 失败关闭，避免在外层 publication 事务内获得无 savepoint 的写能力。
PostgreSQL finalizer 节点同时在该 scope 内实际调用 generation-fenced actor bundle `_snapshot()`，证明原生产失败检查点看到的
事务深度仍为 1，而不是只检查专用 repository 自身。

测试计数：Account graph/fence 单元回归 `62 passed`；Account graph 单文件 `41 passed`；release validator 与 evidence collector
回归 `156 passed`。增量 mypy 覆盖两个生产文件且 0 regression；全仓 debt ceiling `0 errors in 0 files`；Black、isort、Ruff
与 `git diff --check` 通过。新增反例覆盖禁止 savepoint、缺少 active generation fence、exact generation 传递和 production
composition 选用专用 UOW。PostgreSQL finalizer 节点在本机因未启用专用 disposable PostgreSQL 环境而 `1 skipped`，不计为通过，
必须由提交后的 exact-SHA Publication PostgreSQL workflow 实际执行。

未验证风险与停止线：`3c75e9677` 后本节文档提交形成的最终 SHA 尚未取得五组 exact-SHA CI；真实 PostgreSQL 节点、全新 S6、
同镜像部署均未执行。旧 `0fc273d790` receipt、镜像与失败任务只能作为根因证据，禁止复用为新候选放行。生产第二次全市场
刷新没有现存授权；即使修复候选完成 CI、S6 与部署，也必须等待用户新的明确授权后才能投递。不得重跑 task
`4e80d16a-391a-472e-9374-f91146a179aa`，不得扩大 timeout/retry、放宽 freshness/coverage/audit/source/15:00 close 或
`SIGNAL_WEAK`，不得写死证券或伪造 financial owner approval。

下一片是否可开始：可以提交本节台账、push 最终 SHA 并启动五组 exact-SHA CI。五组全绿后才可从最新生产只读快照创建全新
S6；S6 十阶段通过后只部署其 receipt 绑定的同 SHA 预构建镜像并复核运行身份。部署完成后停止在生产刷新授权门前，等待新的
显式授权；获得授权后才能执行一次新任务并继续正式 Publication、decision runtime、Alpha、API/SDK/MCP、普通用户页面与只读
零副作用联合验收。

#### 2026-10-06 outer-fence CI 门禁反馈与测试隔离

`7dbcdac1545f716d2c0eb08c871d5c179aa25e40` 的 Architecture run `37395053012` 与 Security run
`37395052936` 通过；其余三组门禁暴露出三个独立问题，未执行盲目重跑。Consistency run `37395053059` 因
`governance/data_center_architecture_inventory.json` 未随 current surface 变化重新生成而失败。Fast Feedback run
`37395053482` 因 `account_authority_shadow_scanner.py` 从 957 增长到 1,034 个非空行、超过 1,000 行硬阈值而失败。
Publication PostgreSQL run `37395053097` 的 Account final-revalidation job 本身通过，但把 production checkpoint 探针加入
共用 `_PostgresCompleteGraphReader` 后，使 5,001 member activation soak 的查询数从硬上限 35 增为 36，publication suite
以 1 failed、41 passed 失败。文件阈值和查询阈值均未提高。

完成项（`aea21b0a6`）：generation-fenced Authority repository 已拆为独立 Infrastructure 模块，scanner 降至 980 个非空行；
module map 由生成器更新为 Account Infrastructure 141 个模块。Data Center architecture inventory 同样由唯一生成器更新，
current references 为 5,389、cross-app ORM imports 48、外部直连 0。共用 complete-graph reader 恢复为原有查询形状，避免测试
探针污染 publication soak 的生产查询预算；新增独立 PostgreSQL node
`tests/component/account/test_account_authority_final_revalidator_v3_postgres.py::test_postgres_generation_fenced_graph_uow_reuses_outer_transaction`
直接在 finalizer 的真实 outer fence 内进入生产用 generation-fenced repository 与 actor bundle `_snapshot()`，硬断言
`atomic_blocks==1`、read scope 不具备 private append UOW、退出后 repository 与 transaction 均清理。该 node 取代旧泛化节点
进入 S6 `REQUIRED_POSTGRESQL_TESTS`，workflow 对 Account final-revalidation JUnit 的期望计数由 7 增为 8；缺失、跳过或失败仍
必须阻断。

测试计数：Account graph/finalizer 单元回归 `62 passed`；Account、release validator 与 evidence collector 组合回归
`177 passed`。新增 PostgreSQL node、既有 complete-fence node 与 5,001 member soak 在本机均因未启用 disposable PostgreSQL
而 `3 skipped`，不计为通过，必须由新 SHA 的 Publication PostgreSQL CI 补齐。两个生产文件的文件规模门禁通过；current-data
72 surfaces、module map 44 modules/210 edges、Data Center architecture inventory、增量 mypy 3 个生产文件 0 regression、
全仓 debt ceiling `0 errors in 0 files`、Black、isort、Ruff 与 `git diff --check` 均通过。

未验证风险与停止线：`aea21b0a6` 及本节文档提交形成的新最终 SHA 尚未取得五组 exact-SHA CI。必须确认新的
Publication PostgreSQL artifact 含上述独立 node 且该节点无 skipped/failure/error，同时 5,001 member soak 保持查询数不超过
35。CI 全绿前不得启动新 S6；S6、同镜像部署完成后仍须停在第二次生产全市场刷新授权门前。旧失败任务、receipt 与镜像禁止
复用；不得扩大 timeout/retry、文件或查询阈值，不得放宽 freshness/coverage/audit/source/15:00 close/`SIGNAL_WEAK`，不得
写死证券或伪造 financial owner approval。

下一片是否可开始：可以提交本节台账并 push 新最终 SHA，启动五组 exact-SHA CI；只有五组全绿后才可从最新生产只读快照创建
全新 S6 attempt。

#### 2026-10-06 outer-fence 最终候选 S6、同镜像部署与刷新授权停止线

最终候选 `66f7d37077b239bd96cdd0aba1d185dcbc60cc5f` 的五组 exact-SHA CI 已全部通过：Architecture
`37397578370`、Security `37397578910`、Consistency `37397578591`、Fast Feedback `37397579029`、
Publication PostgreSQL `37397578493`。PostgreSQL artifact 中 Account final-revalidation JUnit 为
`8 tests / 0 skipped / 0 failure / 0 error`，包含
`test_postgres_generation_fenced_graph_uow_reuses_outer_transaction`；Publication JUnit 为
`42 tests / 0 skipped / 0 failure / 0 error`，5,001-member activation soak 通过且查询硬上限仍为 35。

第一次 fresh S6 attempt `5087833f22cc410eabd7be3dbfaa510d` 在 `build_only` 前由
`REHEARSAL_BUILD_DISK_HEADROOM_INSUFFICIENT` 正确失败关闭：`/var/lib/docker` 可用 4.4 GiB，低于 12 GiB
硬门槛，没有构建、部署或生产写。保留该 attempt 根目录与诊断后，只清理已确认无活动构建的 Docker build cache，以及已完成或
失败 attempt 的 disposable PostgreSQL、Redis、network 和 volume；没有提高磁盘门槛。随后由 planner 原子预留 fresh attempt
`cb86c74e64c14b06b5e8b47985e2b575`，从当时生产重新导出 provider settings、3 个完整 identities、5,572 个动态 universe
成员与最新只读 PostgreSQL 快照，冻结策略的 `provider_policy_and_routes` preflight 为 pass、无 blocked codes。该 attempt
禁止 `--resume` 执行完整十阶段，最终 outcome 为 `success_evidence`、runner exit 0。handoff receipt SHA-256 为
`cb5d4c36809e4ebc051bd75ab3cd147f9d778ead7711aad145bfc078deb75b60`，manifest SHA-256 为
`f09431cb7cb639825976ee80850e9295c5dce48e37595de57a68afaceb3be34a`，release tag 为 `20261006041252`，
预构建镜像为 `sha256:1e10ffd7972bc5559a60741f47ae96852776054b022d06b199a7041330aa76c9`，OCI revision 精确等于
候选 SHA。

用户授权部署后，生产严格复用上述 receipt 绑定的同一预构建镜像，没有重建或替换镜像。部署进程 exit 0，`current` 为
`/opt/agomtradepro/releases/source-20261006041252`；部署报告位于
`/opt/agomtradepro/rehearsals/s6-66f7d37077-cb86c74e64c14b06b5e8b47985e2b575/deploy-report/remote-build-report-20261006041252-6e9892f7c78cd57f173f58793d6da395.json`，
SHA-256 为 `8bb8201b5a04470aeff2348b34f6d5ea6f9ef795ea965ca3afa0d150990911a7`。Web 与三个 Celery 容器的
image ID 和 OCI revision 均与 receipt 一致；526 条 migration 已应用、0 条未应用；Web、PostgreSQL、Redis、Prometheus、
RSSHub 健康，`/api/health/` 为 200，服务 `/api/ready/` 为 200。生产 provider 路由预检仍为 pass、无 blocked codes；
PostgreSQL `log_statement/log_min_duration_statement/log_min_duration_sample` 为 `none/-1/-1`。部署后清理本次 S6 disposable
资源与 6.082 GB build cache，保留 receipt、manifest、报告和运行镜像，磁盘可用空间恢复到约 13 GiB。

部署未隐式投递全市场刷新：复核时 full-market lease 为 false，Task Monitor 没有部署后新记录，Celery
active/reserved/scheduled 均为 0。完成度审计进一步发现 `full-market-current-publications` 仍启用并计划在工作日
17:05 Asia/Shanghai 自动触发，这会绕过“第二次刷新须单独授权”的停止线；因此在无任务、无 lease、无队列项的前提下，使用既有
管理命令原子禁用 `full-market-current-publications` 与 `financial-current-publication-refresh`，复核两者均为
`enabled=false`。该操作只关闭自动入口，没有创建业务任务或改写正式 Publication。

完成项：outer-fence 最终候选的五组 CI、真实 PostgreSQL node、5,001-member soak、fresh S6、receipt 绑定同镜像部署、生产
身份/迁移/健康/provider/statement logging 复核以及部署后只读零副作用检查全部完成；自动周期入口已在授权门前失败关闭。

测试计数：本节代码候选证据为 Account final-revalidation `8 passed`、Publication PostgreSQL `42 passed`，均零跳过/失败/错误；
S6 十阶段全部通过，release validator exit 0；生产 migration 为 `526 applied / 0 unapplied`。本节后续仅追加运行证据文档，
提交前运行 `git diff --check`，不以文档提交替代已部署候选的 exact-SHA 证据。

未验证风险与剩余停止线：正式 Publication 仍未恢复，`/api/decision-ready/` 继续以稳定码
`decision_runtime_blocked` 返回 503；这是安全保护的预期状态，禁止直接关闭。旧失败 task
`4e80d16a-391a-472e-9374-f91146a179aa` 禁止重跑。第二次生产全市场刷新尚无用户明确授权，因此尚无新任务的规范业务
`outcome` 与 `requested/succeeded/failed/stored`，也尚未完成 Publication ID/hash/source time、decision runtime、Alpha、
API/SDK/MCP、普通用户页面和只读零副作用联合验收。生产仍缺普通角色测试账户；财报 source-time owner approval 仍不得伪造；
receipt-only 单一部署入口继续作为生产联合验收后的独立整改项。

下一片是否可开始：只能等待用户对“一次新的显式生产全市场刷新”的明确授权。授权前保持两个周期入口禁用，不得投递或重跑；
授权后先重新执行只读 preflight、lease/队列/authority/目标交易日复核，只允许一次新 task，终态必须按业务 outcome 而非 Celery
状态验收。成功后继续正式 Publication、decision runtime、Alpha、API/SDK/MCP、普通用户页面和只读零副作用联合验收；任何失败
先保存安全诊断并修根因，不盲目重跑或放宽 freshness、coverage、audit、source、15:00 close、`SIGNAL_WEAK` 及既有规模/锁阈值。

#### 2026-10-06 正式全市场发布恢复与财报双原件生产链路根因

用户授权后只投递了一次新的显式全市场刷新：task `bcb3e00f-538e-420d-b179-428c40082f43`、attempt
`709a571d92f7474f8bc001268bd59050`。该任务已取得规范业务成功终态：
`outcome=success`、`requested/succeeded/failed/stored=5572/5572/0/11144`，publication 为 `1/1`，
`published_members=16705`，run ID 为 `aebb0da7-5336-4460-8fff-e4aa0f0317a7`。price、quote、valuation 三个
current pointer 由同一 activation `19d9a93e-55b6-5b8e-882d-8f3160f560dc` 原子切换；没有局部 pointer 或旧候选
混入。终态业务证据位于
`/opt/agomtradepro/rehearsals/production-refresh-bcb3e00f-538e-420d-b179-428c40082f43/evidence/terminal/business-result.json`，
SHA-256 为 `9436a5dc3469c9fde12457425af05033ad32359083bac90ca469cc789154a719`。该任务禁止再次投递或重跑；
`full-market-current-publications` 与 `financial-current-publication-refresh` 继续保持 disabled。

decision runtime guarded activation dry-run 没有写状态并继续失败关闭。`core_coverage` 与 `provider_capabilities` 的共同阻断来自
financial：旧 current publication `c8741812-cf01-512f-8d1c-91c0e6549f42` 使用 legacy `1.0:1.0` policy identity，
当前 active policy 为 version 3，报告 `canonical_publication_policy_version_mismatch` 且 `member_bound_count=0`。生产只读盘点
确认 487,624 条既有 AKShare 财务事实没有 decision evidence、source record、raw payload hash 或 announced_at；105,606 条仅有
available_at。source-time audit claim、source-time RawAudit 和 retained body 均为 0。旧事实不能用 report date、抓取时间或当前
审批洗白，也不能原地补造 provenance。

owner approval 本身有效：活动 registry 精确绑定 AKShare contract
`akshare.financial-main-data.notice-date@2026-10-04.v1`、parser
`akshare-eastmoney-main-financial-data.v1`、contract SHA-256
`a3b0057315a41f0b8df514fc7aaf5030916927a0cf3f39358a20d39b669eeaf1`，审批人为 `guiyinan`，审批时间
`2026-10-04T15:31:50Z`，receipt SHA-256 为
`ee7741d99d654cacb2f6480adb1de1ad52a1d1c3121d4425728c4d23eeb3ba69`。真正缺口是生产者：AKShare adapter
仍通过 SDK 取得 DataFrame，未保留供应商原始 bytes，未生成 financial/source-time 两个独立 capture、RawAudit claim 与
`FinancialFactDecisionEvidence`；既有 matcher 只能复核已经携带 witness 的 evidence。另一方面，disabled 周期任务仍配置
`source=tushare`，而当前唯一 owner-approved source-time contract 是 AKShare。直接刷新会在 provider/evidence 门失败，不能作为
恢复手段。

完成项（`645bc5b7b8e343de2525cea3c5b6de0550b60fc3`）：为
`AkshareNoticeDateSourceTimeMatcher` 增加首次 witness 构造入口。producer 可以在尚无 claimed witness 时，以精确合同、财务响应
artifact、独立 source-time artifact 和两份哈希匹配的真实 body 构造确定性 witness；read-only verifier 仍通过原 `match()` 路径
从 claimed artifact reference 独立重算并要求完全相等。构造入口拒绝复用 capture identity、body hash/size 漂移、provider/dataset/
asset/announcement-date 不一致和任何 contract drift；没有修改 owner approval、contract digest、日期精度或 availability 规则。

测试计数：提交前 matcher 单文件回归为 `24 passed`；随后新增首次构造、body 漂移/capture 复用故障注入与 verifier 重算三个
定点节点为 `3 passed`。生产文件增量 mypy 为 0 regression，全仓 mypy debt ceiling 为 `0 errors in 0 files`；Black、isort、
Ruff 与 `git diff --check` 通过。该切片只建立 witness 构造能力，不声称双原件 producer 已完成。

未验证风险与停止线：AKShare 两次独立真实 response capture、加密留存、RawAudit/claim、orphan 协调和 adapter fact evidence 尚未
接通；周期 task/source/provider capability preflight 尚未收紧。提交 `645bc5b7b` 尚未 push 或取得 exact-SHA CI。不得调用
provider 验证本切片，不得部署或投递 financial refresh；旧 financial publication 保持阻断。普通用户角色没有现成 active token，
因此外部 API/SDK/MCP 与普通页面验收仍缺合法只读会话，不能创建持久 token 或把匿名/管理员结果当作普通用户证据。

下一片是否可开始：可以独立实现 AKShare 双 raw-body capture 与 retention composition，并用 fake transport、append 失败和 orphan
故障注入证明任何不完整证据都零事实写入。完成后再独立把 typed witness 接入 adapter facts，最后收紧 task/schedule 的显式 source、
精确 provider identity 与 active contract/capture capability preflight。四片全部通过本地门禁、exact-SHA CI、fresh S6 和同镜像部署前，
不得请求或投递 financial refresh；即使部署完成，生产财报刷新仍需用户新的明确授权。

##### 财报整改第②片：AKShare 双原件捕获与留存组合

完成项（`3f01a2a1f`）：新增 AKShare financial capture gateway，由内部按已批准合同生成固定 EastMoney endpoint 和有界请求参数，
在 egress 前校验 logical source type、active provider row ID、精确 owner-approved contract identity 与 1～200 行上限。每个单证券、
单公告日请求使用两个不同 capture UUID，分别以 financial/source-time dataset scope 获取 transport 原始 bytes；只有两份响应均通过
body hash/size、provider success、asset/date、row count 与 provider-derived scope 校验后才开始加密留存。financial 与 source-time
body 使用不同 envelope/location namespace，RawAudit 均绑定同一真实 provider ID；没有把 DataFrame 或重新序列化 JSON 冒充原件。
本片不调用 AKShare DataFrame adapter、不构造 witness、不写 FinancialFact，也不改 task/schedule。

测试计数：新增 capture 故障注入 `13 passed`；matcher/egress/source-time retention 组合回归 `43 passed`；另行执行包含 capture、
retention 与两个 body store 的组合回归 `58 passed`。反例覆盖空 body、provider rejection、重复 capture UUID、超 200 行、provider
source/active/ID 无效、registry mismatch、source-time audit 重复，以及 financial/source-time 两侧 audit append 失败后的 orphan
可检查性。Black、isort、Ruff、生产文件增量 mypy、debt ceiling、current-data 72 surfaces、module map 44 modules/210 edges、Data
Center architecture inventory 与 `git diff --check` 均通过；三个治理投影均由生成器或其契约更新，没有手工伪造生成结果。

未验证风险与停止线：全部 provider 行为使用 fake egress；真实 EastMoney 对组合 `SECUCODE+NOTICE_DATE` filter 的接受性尚未通过
受控 dry-run 证明。`FinancialSourceTimeArtifactRef` 绑定单一公告日，所以当前 primitive 每证券/每公告日需要一对响应；禁止把一份
body 复制为多个 capture 或跨日期共享 reference。全市场接入前必须先完成真实小规模 provider contract test、1+N 或 2N 请求模型的
规模/配额/耗时测算，并在不放宽 timeout/retry 的前提下形成硬门禁。文件留存与数据库 RawAudit 不能跨介质原子提交；append 失败
会留下显式 orphan，现有检查可识别但自动对账/清理尚未实现。现有 verifier 仍错误地把 ProviderConfig.name 展示名与 logical
provider name 比较，必须在下一片独立修复并保留 provider ID 审计绑定。提交尚未 push、取得 exact-SHA CI 或进入 S6；不得部署、
启用周期入口或投递 financial refresh。

下一片是否可开始：可以修复 verifier 的 logical source/provider-row 身份契约，并将 capture pair、首次 witness 构造和 typed
FinancialFact evidence 接入 AKShare adapter；必须先补真实格式 fake-transport 组件测试和任何失败零事实写入反例。请求规模、真实
provider dry-run、task/source preflight 与周期配置继续作为后续独立停止线，不能在 adapter 接线时顺手放宽或启用。

##### 财报整改第③片：provider 身份、AKShare 单公告日事实证据接线

完成项（`dde104918`）：`verify_provider_financial_source_time_evidence` 现在用 `ProviderConfig.source_type` 校验 logical
provider，并将 active provider row 的 ID 继续交给 financial/source-time 两份 RawAudit link verifier 精确比较。展示名
`AKShare Public` 被正向覆盖；错误 source type、停用 row 与错误 provider ID 均失败关闭。AKShare capture gateway 新增 retained
双 body 精确回读与两份 RawAudit provider ID 复核，并要求每个响应行都满足单证券、单公告日期范围。adapter 增加显式
`fetch_financials_for_announcement_date` 路径：只从双份保留的原始 EastMoney bytes 解析指标，逐行先构造首次 witness，再生成
typed `FinancialFactSourceEvidence` / `FinancialFactDecisionEvidence`；只有整批所有解析与证据均通过后才返回 facts。旧 DataFrame
入口、通用 sync 用例、task/schedule 和 provider routing 均未改动，因此这个新路径尚未接入任何生产任务。

验证：fake-transport adapter/capture、matcher、verifier、financial write-count/probe 与 publication sync 合并回归
`81 passed`，另有 Data Center architecture guard `5 passed`。Black、isort、Ruff、`git diff --check` 通过；生产文件增量 mypy
为 `0 regression`，债务上限为 `0 errors in 0 files`；
current-data 为 `72 surfaces`，module map 为 `44 modules / 210 edges`，Data Center architecture inventory 已由唯一生成器
`--write` 刷新并通过无写入核对。故障注入验证来源行不匹配时 adapter 不返回任何 fact，调用方的假写入集合保持为空；现有测试还覆盖
provider rejection、空 body、重复 capture/audit claim 及 financial/source-time audit append 失败和 orphan 可识别性。

未验证风险与停止线：没有调用真实 provider、生产数据库或生产写路径。组合 filter `SECUCODE+NOTICE_DATE` 尚未通过真实
EastMoney 受控验证；当前路径每证券/公告日两次请求，仍须在任何广泛接入前完成 1+N / 2N 容量、频率、耗时与配额测算。跨文件系统
body store 与数据库 RawAudit 不是原子提交；失败 orphan 可检查但尚无自动对账/清理流程。新 adapter 方法目前只是显式的单证券/单公告日
入口，通用任务仍走原路径；不得将其接入生产 schedule、启动 financial refresh、扩大 timeout/retry 或放宽 evidence/freshness
约束。需要先由根代理审阅本地 diff，再独立处理受控 sync/provider source 路由和规模硬门禁。

##### 财报整改第④片：显式 AKShare 切片 sync 与请求规模硬门禁

完成项（`fdbc52919`）：基于 clean HEAD `820bdc73c` 新增一个受控 Application UseCase 和公开 composition builder。请求必须显式携带
`source="akshare"`、正数 `provider_id`、规范资产代码、单一公告日的 tuple 切片和有限 `period_limit`；缺少 source/ID、错误
source、错误/停用 provider row、adapter row ID 漂移、财务能力不存在、owner-approved contract 或 retained-body capability
不可用时均在 provider egress 前 `blocked`，不回退默认 provider、不经过旧 DataFrame 财报入口。gateway 组合继续复用已批准合同、
现有 Data Center egress、双体留存和 RawAudit verifier。

新增 `governance/financial_sync_request_budgets.json` 作为 fail-closed 执行 ceiling，并由严格 loader 同时绑定 AKShare matcher
contract id/version/SHA、每切片两次独立 logical capture 和既有 200 行上限。当前 ceiling 为一次最多 1 个资产/公告日切片，
`N` 个切片先按 `2N` 计算 logical provider request 数并在读取 provider row 或创建 gateway 前拒绝超限；当前 policy 因而允许最多
2 次 logical request。egress 的现有单请求最多两次 transport attempt 没有改动，所以最坏网络 attempt 上界为 `4N`；该上界不代表
真实 provider 配额或生产 refresh 授权。任何扩大 ceiling 都需要独立的容量证据与 governance review。

UseCase 会检查返回事实的 typed source/decision evidence、精确资产/公告日/page scope、body hash/native row identity、保留的双
capture 引用及 owner contract/audit verifier。只在请求切片全部通过后，附加现有 publication transport metadata，并将完整 facts
以单次 `FinancialFactRepository.bulk_upsert` 写入；repository 对 FinancialFact 数据库批次使用 `transaction.atomic`。任一 provider、
解析、evidence 或审计失败都不调用事实 writer；多切片部分失败返回 `partial` 且 `stored=0`。body store 与数据库 RawAudit 仍不是
跨介质原子事务，失败时可留下既有可识别 orphan。

验证：根代理补充零写入 `noop` 原因契约后，17 个 AKShare/source-time/evidence/financial write/publication 回归文件为 `224 passed`；
受控 sync 单文件为 `29 passed`，组件覆盖缺省/错误 source、
错误 provider row/ID、审批或 capture capability 缺失、超过上限 `2N=4`、fake-transport 正常双体路径、evidence rejection 和后续
provider 失败时零 FinancialFact 写入。Data Center architecture inventory/guard `10 passed`；Black、isort、Ruff、增量 mypy、debt
ceiling、current-data `72 surfaces`、module map `44 modules / 210 edges` 与 architecture inventory projection 生成核对通过。
本片没有触碰 Celery task/schedule，也没有 provider 调用、生产写入、deploy 或 refresh。

未验证风险与停止线：EastMoney `SECUCODE+NOTICE_DATE` 真实 filter 合法性、provider 的 2N/4N 配额/频率/耗时、生产文件留存
目录权限与 RawAudit orphan 自动修复均未验证。当前一对 capture 仍只适用于单个证券/公告日；owner contract 与 ceiling 不授权生产
刷新。不得连接周期入口、扩展 timeout/retry、放宽 source-time/freshness/evidence 检查，或把旧 financial facts 补成有 provenance。

##### 财报整改第④片补充：真实 provider 组合 filter dry-run

2026-10-07 00:10（Asia/Shanghai）对 EastMoney 公开只读 endpoint 做了单证券、小规模契约验证，没有经过生产数据库、留存目录、
task 或 schedule。先以 `000001.SZ` 的资产过滤读取 5 行，provider 返回 HTTP 200、业务 `success=true/code=0`，发现真实
`NOTICE_DATE=2026-08-15`。随后按原实现的双引号日期组合 filter 请求，HTTP 虽为 200，但 provider 业务返回
`success=false/code=9501`、`filter字段中日期参数格式错误`、0 行；这证明 HTTP 200 不能替代 provider 业务契约验收。

根因是 EastMoney 日期 filter 值要求 SQL 风格单引号；证券代码字符串仍接受双引号。将日期序列化修为
`(SECUCODE="000001.SZ")(NOTICE_DATE='2026-08-15')` 后，单引号日期与单引号 midnight timestamp 两个有限探针均返回
`success=true/code=0`、1 行，资产与公告日全部精确匹配。修复提交为 `a50c444ec`。随后通过 Django 初始化直接调用生产
`_akshare_request_params` 再验：HTTP 200、业务 code 0、1 行、349.2ms、body SHA256
`f788505c39fbbccfc7406cb0ab8ef43438a22757433a2e8afa1f4f4120cd5a2b`；修改后的 capture/sync 单文件回归
`29 passed`，Black、Ruff 与增量 mypy 通过。

本次仅证明真实 provider 接受修正后的单资产/单公告日请求格式。两个成功有限探针分别约 358.0ms 与 349.2ms，不能外推为
全市场容量、频率或 SLA 结论，也没有验证生产 egress、加密留存、RawAudit、orphan 对账和事实写入。`N<=1/2N<=2` ceiling
继续保持；在 exact-SHA CI、fresh S6 隔离存储与同镜像部署证据完成前，不得扩大 ceiling、接 task/schedule 或请求 financial refresh。

首次推送候选 `bcd9732d4fa4a1d844bc110eb49c7e3dc8b0c8af` 后，Architecture Layer Guard
`37493723256` 正确阻断了 `application/interface_services_decision_sync.py` 对同 App infrastructure fetcher/budget loader 的直接
import；boundary 为 0，但 audit rule `apps_application_no_same_app_infrastructure_imports_except_repository_provider` 报 1。修复
`13d7be3bf` 删除 Application 层组装和 facade 暴露，将 provider repository、registry、fact repository、fetcher 与 budget 的装配移到
`apps/data_center/akshare_financial_slice_sync_composition.py` composition root。根代理按同一 base
`80c3cfc8e9941b1a1705edf0f1272c91b37e1ee8` 复跑 architecture delta：9 个变更文件、1851 新增行、7 条 boundary 和
20 条 audit 规则均为 0 violation；相关 capture/composition 与 architecture inventory 回归 `33 passed`，增量 mypy、Black、isort、
Ruff、module map、current-data 和 architecture inventory 无写检查通过。原失败 run 不重跑，后续只接受新 exact-SHA CI 证据。

第二轮候选 `c06f373f8ec568f26d25119420ff242ef0bd3b2d` 的 Architecture、Security 与 Publication PostgreSQL 已通过，
Consistency `37495542861` 和 Fast Feedback `37495542870` 暴露两个治理遗漏。其一是新增 current-data source file 后
`governance/data_center_entrypoints.json` 未由唯一生成器刷新；其二是把 sibling helper 加入 `sync_use_cases.__all__`，触发 legacy
export 结构测试要求 `application.use_cases` 同名重导出。修复 `ec0b7ce90` 重新生成 entrypoint inventory，并把 helper 保持为模块内
显式 import 能力而不扩张 legacy public export。根代理复跑 no-database fast suite为 `4045 passed`、61.62s（120s 预算），
entrypoint inventory 无写核对通过；Black、isort、Ruff、增量 mypy 与 `git diff --check` 通过。两个旧失败 run 均不得重跑，后续仍只
接受包含这些修复的新 exact-SHA 五组 CI。

#### 2026-10-07 全面 E2E UAT 复验、用户反馈与最终候选门禁

本轮 UAT 以业务结果为准，没有把 HTTP 200、Celery `SUCCESS` 或服务健康等同于业务恢复。生产正式全市场任务
`bcb3e00f-538e-420d-b179-428c40082f43` 的既有终态证据继续有效：`outcome=success`，
`requested/succeeded/failed/stored=5572/5572/0/11144`，publication `1/1`，price、quote、valuation 三个 current pointer
由同一 activation 原子切换；该任务禁止再次投递或重跑。两个周期入口 `full-market-current-publications` 与
`financial-current-publication-refresh` 继续作为部署后必须实时复核的 disabled 停止线。

全面只读复验确认 signal API 的默认查询、`offset=0`、分页、状态、证券过滤及空列表契约均正常；SDK 与 MCP 对空结果不再按
执行失败处理。Regime、估值、财报和政策读取保留稳定业务码、中文原因、数据时间与 `must_not_use_for_decision`，PX 待分类与人工
复核要求没有被压成无条件 `neutral`。生产 `dashboard.read.alpha_history` 暴露 SDK 把已解包 list 当作 dict 的错误，提交
`dfedaad3b` 统一 list response；对应生产部署后仍须复验。Task Monitor 的业务 outcome、四项统计和 API/MCP owner 契约回归为
`72 passed`；signal/SDK 定向回归为 `44 passed`，SDK/MCP policy/signal 回归为 `43 passed`，TUI/workbench/terminal/SSL 组合
回归为 `379 passed`。只读生产对账没有新增 refresh、建议或业务任务；观测到的 TaskExecution 增量来自既有周期任务，MCP READ
只增加读取审计。部署后仍须以同一时间窗再次对账，不能以本轮旧生产结果替代新候选证据。

生产 `/api/ready/` 的 8 秒超时被分解到旧 Qlib freshness probe 与市场日历冷启动。提交 `c9509c930` 改为读取同一
`provider_uri/calendars/day.txt`，对文件行数和字节数设置硬上限并严格校验递增日期；缺失或损坏继续 fail closed，不缓存、不删除
任何 readiness 检查。生产只读模拟中 database 约 0.8ms、critical data 约 22.1ms、decision data 约 3.78s、decision runtime
约 6.3ms、Alpha cold/warm 约 358/203ms；它只证明新算法的量级，不能代替部署后真实 `/api/ready/` 复验。相关回归
`46 passed`，增量 mypy、debt ceiling、current-data、Black、isort、Ruff 通过。

Classic Alpha 页面提交 `be8e367f0` 将“本次运行”和“最近完成结果”分开显示，使用 Asia/Shanghai 时间，呈现阶段、业务 outcome、
`requested/succeeded/failed/stored`、中文统计口径、稳定错误码与安全 trace；原始 UTC 和机器字段仍保留在数据契约中。显式刷新
在 15 秒反馈预算后提示状态未确认，重复点击被抑制，重试按钮只做 GET 状态读取，不再次 POST。重复 Alpha GET 保持
`allow_refresh=false/persist_history=false`，刷新端点拒绝 GET；候选研究详情在决策阻断下仍可读，Workspace 深链携带证券、账户、
动作和来源。Classic pytest `21 passed`、Node 浏览器 harness `2 passed`，增量 mypy、debt ceiling、Black、isort、Ruff 与
Web migration inventory 均通过。当前没有合法普通用户生产会话，生产普通角色的权限隔离、账户切换、候选深链和响应时间仍是
明确未完成项；不得用匿名重定向或管理员会话冒充普通用户证据。

财报链路提交 `4748d4940` 把受控 AKShare `N=1`、精确 `2N=2` logical request、双 raw body、两份 RawAudit、真实 provider row、
owner-approved contract、typed evidence、单批 atomic fact write 与零写失败反例接入 S6，仍保持请求 ceiling，不连接周期任务。
本地目标回归为 `254 passed / 2 skipped`；两个 skip 仅为 Windows 目录符号链接能力，必须由 Linux fresh S6 补齐。旧候选
`4748d49405d75143f31a69546cf2a61dc19cee58` 的 Architecture `37520075048`、Security `37520075039` 和 Publication
PostgreSQL `37520075062` 通过；Consistency `37520075097` 因 architecture inventory 未生成而失败，Fast Feedback
`37520075294` 暴露 verifier 默认调用兼容和 release evidence fixture 没有包含第六 required report。没有重跑旧 run。

提交 `f5c271f65` 仅在显式 S6 artifact root 时向 verifier 传递该参数，并让 collector 测试从治理定义读取完整 required schemas；
validator、报告身份和 S6 证据要求均未放宽。相关回归 `39 passed / 1 skipped`，增量 mypy、debt ceiling、Black、isort、Ruff
通过。提交 `32b708dda` 随后用唯一生成器重建 `governance/data_center_architecture_inventory.json`；inventory 单测
`4 passed`，生成后 current surface 为 5,390、cross-app ORM imports 为 48、所有 Data Center 外部直连计数保持 0。

完成项：行情/估值正式发布与全市场业务 outcome 已有生产证据；API/SDK/MCP 契约、只读零副作用、任务业务统计、Alpha 页面反馈、
readiness 有界探针和 S6 财报 N=1 生产预演代码均已完成本地/历史生产分层验收。`SIGNAL_WEAK=0.6000` 没有降低，空信号与零候选
没有造数；15:00 close、freshness、coverage、audit、source、请求/查询/文件阈值均未放宽。

未验证风险与停止线：`32b708dda` 之后还须追加本节台账提交，只有该最终 exact SHA 的 Architecture、Security、Consistency、Fast
Feedback、Publication PostgreSQL 五组 CI 全绿，且 PostgreSQL artifact 精确包含 financial slice sync 与 account outer-fence/5,001
member soak 节点并零跳过/失败，才能从最新生产只读快照创建 fresh S6。S6 必须禁止 `--resume`，重新导出 provider settings、完整
identities、动态 universe 与 unit contract，在隔离 PostgreSQL/Redis 和真实 provider 下完成十阶段、财报 N=1 双原件/审计/零写反例及
release validator；随后只部署 receipt 绑定的同 SHA 预构建镜像。部署后必须复核 revision/image/receipt、migration、健康/readiness
耗时、provider route、statement logging、两个周期入口 disabled、API/SDK/MCP 与只读零副作用。

Financial current publication 仍为 legacy policy identity 且无 member-bound provenance，decision runtime 继续正确 fail closed；不能把三类
行情/估值发布写成四类发布全部恢复。生产 financial refresh 仍需要用户新的明确授权，且当前 ceiling 只授权受控 `N<=1/2N<=2`，
不能外推为全市场容量。普通用户生产 UAT 需要已有合法普通角色会话；不得创建持久 token、复用已暴露凭据或以管理员替代。上述任一
停止线未满足时，E2E 总结必须标为“部分通过/仍有阻断”，不能宣称全面恢复。

下一片是否可开始：可以提交本节台账并把新 HEAD 作为唯一最终候选，启动五组 exact-SHA CI；CI 全绿后执行 fresh S6 与 receipt-only
同镜像部署。部署完成后继续只读联合 UAT并停在 financial refresh 与普通用户生产身份两个授权/输入门前。

##### 2026-10-07 fresh S6 CI 证据只读挂载权限整改

候选 `33f8c5a42b650ccf5342cf91e27d9572a87661b2` 的五组 exact-SHA CI 已全部通过：Architecture
`37555464821`、Security `37555464829`、Consistency `37555464786`、Fast Feedback `37555464778`、Publication
PostgreSQL `37555497546`。PostgreSQL artifact 已核对 financial slice sync 为 `8 passed / 0 skipped / 0 failed / 0 error`，
Account outer-fence 为 `8/0/0/0`，Publication 为 `42/0/0/0`，并包含 5,001-member soak 节点。随后创建的 fresh S6 attempt
`72de41d46b7242de9789cc0f8ce9d32c` 使用最新生产只读 PostgreSQL 快照、4 个完整 provider identities、5,572 动态 universe、
隔离 PostgreSQL/Redis 和 exact-SHA 预构建镜像；build、image identity、provider probe、response replay、full-universe capacity、
production-policy parity、isolated PostgreSQL write 与 GitHub CI evidence 八段均完成，未部署。

该 attempt 在 `akshare_financial_slice` 以稳定码 `REHEARSAL_FINANCIAL_SLICE_FAILED` fail closed。隔离库取证确认失败时间窗内
`SyncItemAttempt`、`RawAudit`、`FinancialFact` 和 source-time audit claim 的新增数均为 0，因而没有 provider 结果、审计或事实的
部分写入。逐段只读复现进一步定位到 candidate regression evidence 读取：宿主 collector 生成的 `github-ci-evidence` 目录为
`0700 root:root`，JSON/XML 文件为 `0600 root:root`，而 candidate stage 使用非 root 用户；readonly bind mount 保留上述 mode，
容器在 provider 调用前即收到 `PermissionError`。失败 attempt、镜像和诊断继续保留，禁止 `--resume` 或把其八段前缀当成完整 S6。

完成项（`1113724d95db3023d1ce3f2603e94f671b20d404`）：CI 证据完成身份校验后，checkpoint 文件系统边界递归拒绝 symlink 与特殊文件，
使用候选镜像实测 primary GID 通过 descriptor-based `fchown/fchmod` 把目录封为 `0550`、文件封为 `0440`；逐项复核 inode、GID
和 mode 后才允许 financial stage 挂载。容器只有组读取/遍历权限，宿主后续 checkpoint hash 与 bundle build 仍可读，未赋予写权限，
也没有放宽 provider、请求、timeout、retry 或财报证据门槛。Windows 本地采用只读 `0555/0444` 投影。runner 非空行数保持
`2177 -> 2177`，未规避 1,000 行增量门禁；Data Center entrypoint projection 由唯一生成器重建并与全新输出逐字节一致，共
1,297 条。

测试计数：S6 runner、candidate regression collector 与 release validator 组合回归为 `204 passed / 2 skipped`；两个 skip 均为
Windows 本机不支持相应 symlink 故障注入，Linux CI 必须执行且不得跳过。新增正向反例从 `0700/0600` 输入开始，要求 financial
container 启动前精确变为候选组 `0550/0440` 并可读；反向用例要求嵌套 symlink 以
`S6_CONTAINER_INPUT_TREE_INVALID` 失败关闭。两个生产文件增量 mypy 为 0 regression，全仓 debt ceiling 为
`0 errors in 0 files`；Black、isort、Ruff、`git diff --check`、governance consistency（0 violation）、Data Center architecture
inventory（5,390 current surfaces、48 cross-app ORM imports、外部直连 0）均通过。

未验证风险与剩余停止线：`1113724d9` 尚未 push，尚无包含本修复和本节台账的最终 exact-SHA 五组 CI，也没有新的 fresh S6、
handoff receipt、同镜像部署或部署后只读 UAT。任何新 S6 必须重新预留 attempt、重新导出生产 provider settings/完整 identities/
动态 universe/unit contract、从最新只读快照开始并禁止 `--resume`；不得复用 attempt `72de41d...` 的镜像或阶段前缀。生产任务
`bcb3e00f-538e-420d-b179-428c40082f43` 禁止再次投递或重跑，生产 financial refresh 仍未授权，两个周期入口必须保持 disabled。
普通用户生产会话仍未提供，禁止创建持久 token 或用管理员会话替代。

下一片是否可开始：可以把本节台账提交后的 HEAD 作为唯一新候选，push 后绑定新的五组 exact-SHA CI。只有五组全绿且 Linux
权限反例、financial slice、outer-fence 与 5,001-member soak 节点均零跳过/零失败，才可创建全新 S6；S6 十阶段、财报 N=1
双原件/双 RawAudit/typed evidence/单批原子写/零写失败反例和 release validator 全部通过后，才可部署 receipt 绑定的同 SHA 镜像。

##### 2026-10-07 fresh S6 财报出网路由契约整改

最终候选 `e6aac397a625e8eddf8b4453331bda810a69e7d1` 的五组 exact-SHA CI 已全部通过：Architecture
`37565456573`、Security `37565456549`、Consistency `37565456562`、Fast Feedback `37565456524`、Publication
PostgreSQL `37565480146`。PostgreSQL artifact 已复核 financial slice sync `8/0/0/0`、Account outer-fence
`8/0/0/0`、Publication `42/0/0/0`，并包含 5,001-member soak。首次新 attempt
`ebe16fb787094b45957b16e17dfd771a` 在候选阶段开始前因远程 prepare wrapper 含 CR 字节退出 127；真实输入导出和只读快照恢复虽已
完成，但没有启动候选阶段、provider 请求、部署或生产写。根目录和 `prepare-failure-diagnostic.json` 保留，隔离资源在精确身份检查后
清理，禁止 resume。

第二个 fresh attempt `5caf4f22e0264b3f9a9d67a06432f655` 重新导出 4 个完整 identities、5,572 动态 universe、provider
settings 和最新生产只读 PostgreSQL 快照，隔离 PostgreSQL/Redis、候选 SHA、526 migrations、磁盘门槛与冻结 settings preflight
均通过；候选 CI evidence 在非 root 容器中实读成功，证明 `1113724d9` 权限整改有效。该 attempt 完成至 GitHub CI evidence 后在
`akshare_financial_slice` fail closed，未生成 receipt、未部署。隔离库时间窗对账为新增 `RawAudit=0`、source-time claim `=0`、
`FinancialFact=0`、`SyncItemAttempt=0`，不存在部分写入。

根因证据：无 provider 请求的真实组合诊断确认 provider row `3`、AKShare adapter、owner-approved contract、原件加密配置、请求
ceiling 与 request seed 均有效；随后严格限制为两个 dataset 各最多一次 transport attempt 的隔离诊断在网络发送前分别返回
`EGRESS_FINANCIAL_ROUTE_REQUIRED`，实际 provider 请求数仍为 0。生产快照的两条历史规则只覆盖 provider `2/4` 与
`demo.agomtrade.pro`，没有 provider `3` 到 `datacenter.eastmoney.com` 的 `equity.financial.fact` 和
`equity.financial.source-time` 规则。既有 `provider_policy_and_routes` 只检查全市场 model-market 批量路由，不能证明财报双原件
路由，因此此前 pass 不构成该能力证据。

完成项（`eab049b26`）：财报 S6 在任何 provider egress 前对两个精确 dataset、provider row、目标 host 和当前 deployment region
分别执行持久化路由 preview，任一 rule 缺失即以 `REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED` fail closed；成功报告新增两条
去敏路由证据，release validator 强制校验 dataset 集合、正数 rule ID、strategy、目标 host、candidate count 与 region。UseCase 的
安全 failure reason 映射为稳定 rehearsal code，management command 只透传 `REHEARSAL_FINANCIAL_SLICE_*` allowlist，其他异常继续
压缩为通用码，不泄露 provider 响应或凭据。deployment-region 解析被提升为同一公开 helper，route preflight 与实际 gateway 不再使用
两套 region 逻辑。

测试计数：财报 capture/sync/rehearsal、release evidence 和完整 release validator 合并回归 `155 passed`；更窄的财报切片与双原件
回归 `39 passed`。三个生产文件增量 mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、
`git diff --check`、module map `44 modules / 210 edges` 通过。Data Center entrypoint inventory 由唯一生成器重建，仍为 1,297 条且无
投影差异。

未验证风险与停止线：生产尚未登记上述两条精确出网规则，新候选也尚未重新绑定五组 CI；attempt `5caf4f22...` 禁止 resume，其镜像
不得部署。下一次 S6 前须通过现有 Domain/Repository 在事务内登记两条精确、可回滚规则，并保存 before/after、provider ID、dataset、
host、region、rule ID 与内容 SHA；该配置写入不授权 financial refresh。生产任务 `bcb3e00f-538e-420d-b179-428c40082f43`
仍禁止重跑，两个周期入口继续 disabled，financial refresh 仍须用户新的明确授权；不得扩大 timeout/retry/request ceiling 或用通配
dataset/domain 代替精确规则。普通用户生产会话仍未提供。

下一片是否可开始：可以提交本节台账、push 新 exact SHA 并启动五组 CI；CI 全绿且 PostgreSQL artifact 节点满足原硬门槛后，先原子
登记并只读复核两条精确生产路由，再从该最新生产快照创建全新 S6，禁止 resume。S6 十阶段与 release validator 全通过后才可部署
receipt 绑定镜像；部署后继续只读 UAT并停在 financial refresh 与普通用户会话停止线前。

##### 2026-10-07 fresh S6 opaque 财报原件位置整改

最终候选 `a16155cd3ec95d2fc321d54b80c2cb192b20f8c6` 的五组 exact-SHA CI 已全部通过：Architecture
`37573469062`、Security `37573469022`、Consistency `37573469018`、Fast Feedback `37573469092`、Publication
PostgreSQL `37573469083`。PostgreSQL artifact 已复核 financial slice sync `8/0/0/0`、Account outer-fence
`8/0/0/0`、Publication `42/0/0/0`，包含 5,001-member soak 和 valuation lineage 节点。生产以现有 Domain/Repository 原子登记
provider `3` 到 `datacenter.eastmoney.com` 的 financial fact/source-time 两条精确规则，配置 receipt SHA256 为
`48e6bc592ebba1bd738599f4665b30fdef24e09fe62e6dcdad853fbe06a1da78`；没有 provider 调用或 refresh，两个周期入口保持 disabled。

fresh S6 attempt `aecd32f2c6494292b904f7f3f9776717` 从最新生产只读快照开始，重新导出 provider settings、4 个完整 identities、5,572
动态 universe 和 unit contract，在隔离 PostgreSQL/Redis 中完成到 GitHub CI evidence；financial route preflight 和两个真实 provider
请求均成功，生成两个不同 capture UUID、两份成功 RawAudit 和 typed evidence。该 attempt 随后在财报报告组装阶段以
`REHEARSAL_FINANCIAL_SLICE_FAILED` fail closed，未生成 handoff receipt、未部署。安全诊断文件
`financial-failure-state.json` SHA256 为 `dd3eee736985236c5d6476fee0293bc3b2314bde44de1d50bc63a0b92b7d9982`；进一步只读对账
证明两份原件 hash/size、provider ID、audit link、availability 顺序、registry 和 request scope 均有效，对账报告 SHA256 为
`332ff998d5e8e0a0c10ff7c847bf3dfee5d0910e77a897094841419f5a2eee56`。失败 attempt 禁止 resume 或部署。

根因是报告层把 `FinancialResponseArtifactRef.location` 的 opaque URI（`financial-response:///...`）再次拼到本地目录并执行
`is_file()`；而 Domain 合同明确禁止对该 location 作路径假设，正文在此前已由各自 BodyStore 完成解密、hash、size 和 RawAudit
认证。URI 被错误解释为路径后抛出 `ValueError`，management command 按设计压缩为通用稳定码，因此真实 provider 和持久化证据成功
仍不能生成 S6 report。

完成项（`ac4b2fd0a`）：`_verify_artifact_bytes` 在两份 BodyStore 原件、hash/size 和精确 RawAudit provider link 全部通过后返回认证
capture UUID 集合；typed persisted pair 携带该集合，报告层只核对它与当前 financial/source-time 两个 UUID 精确相等，不再解析或访问
opaque location。缺少任一认证 capture 时继续以 `REHEARSAL_FINANCIAL_SLICE_BODY_INVALID` fail closed，没有放宽正文、审计、provider、
request ceiling、timeout 或 retry 门槛。

测试计数：财报 capture 与 rehearsal 合并回归 `41 passed`；加入完整 release validator 后为 `142 passed`。新增行为测试使用真实
`financial-response:///...` 引用证明报告可生成，并以缺少一个认证 UUID 的故障注入证明零容忍。生产文件增量 mypy 为
`0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff 和 `git diff --check` 全部通过。

未验证风险与停止线：`ac4b2fd0a` 尚未与本节台账一起 push，也没有新 exact-SHA 五组 CI、fresh S6、receipt、同镜像部署或部署后只读
UAT。下一次 S6 必须重新预留 attempt、重新导出全部输入、从最新生产只读快照开始并禁止 `--resume`；不得复用
`aecd32f2...` 的镜像或阶段前缀。生产 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，financial refresh
仍未授权，两个周期入口必须保持 disabled；普通用户生产会话仍未提供。

下一片是否可开始：可以把本节台账提交后的 HEAD 作为唯一最终候选并 push，重新绑定五组 exact-SHA CI。只有五组全绿且
financial slice、outer-fence、5,001-member soak 全部零跳过/零失败后才可创建全新 S6；S6 十阶段、真实 provider N=1 双原件/双
RawAudit/typed evidence/单批原子写/零写失败反例和 release validator 全通过后，才可部署 receipt 绑定的同 SHA 镜像。

##### 2026-10-07 S6 阶段环境契约审计与统一 preflight

完成项：提交 `7191ddcf294c545c58b1023fcdf2a5c05a9deb85` 新增
`docs/development/s6-stage-environment-contract.md`，把现有 11 个 S6 阶段逐一映射到文件系统、传输编码、网络出口、身份与密钥、
资源与时间、外部状态六类环境假设；每格均区分已有断言与缺口，并记录历史 attempt `72de41d4...`、`ebe16fb7...`、
`5caf4f22...` 的只读取证。统一 stage environment preflight 在候选 build 前和各阶段起跑前执行只读断言，聚合全部缺口后一次性
fail closed；稳定错误码均使用 `REHEARSAL_*` allowlist，不记录 secret 值或 provider 响应。权限复核复用 descriptor-based 密封，
路由复核复用持久化 preview 与同一公开 deployment-region helper，没有创建第二套权限、路由或 region 规则。新阶段如果没有登记完整
六类矩阵，runner 拒绝排期；preflight 不排队业务任务、不写建议，也不改变普通 GET 或只读 MCP 的行为。

提交 `160494570d975e7f6ed9508bbd0eb1e8bf389981` 把 prebuild 与最终 stage-environment 报告列为 release rehearsal 第七类必需
证据，并绑定 manifest、release validator 与 handoff receipt；validator 强制复核完整阶段/类别矩阵、报告身份、内容 hash、磁盘与内存
硬阈值。提交 `3528c01b6eca63ad3f7862f205483ffc71b2d8f0` 把可移植的环境契约投影纳入
`governance/release_rehearsal_policy.json`，validator 从治理真源读取投影，不再依赖 repository import path；独立临时目录中的 CI
collector/validator 仍可运行。测试同时断言治理投影与运行时 registry 的 6 类、11 阶段和资源阈值逐项一致，防止形成第二真源。

测试计数：最终实现 exact SHA `3528c01b6eca63ad3f7862f205483ffc71b2d8f0` 的 Architecture `37592421057`、Security
`37592421131`、Consistency `37592421083`、Fast Feedback `37592421129`、Publication PostgreSQL `37592577981` 全部通过。
PostgreSQL artifact 共 7 份 JUnit、`73 passed / 0 skipped / 0 failure / 0 error`：Account outer-fence `8/0/0/0` 并包含
`test_postgres_generation_fenced_graph_uow_reuses_outer_transaction`，financial slice sync `8/0/0/0` 并包含
`test_akshare_financial_slice_sync_uses_exact_approved_route_and_one_atomic_write`，Publication `42/0/0/0` 并包含
`test_activation_5001_members_has_fixed_queries_locks_and_retry`。本地统一 preflight、runner、collector、validator 组合回归为
`308 passed / 4 skipped`；更早的完整目标组合为 `292 passed / 4 skipped`，可移植性定向回归为 `21 passed`，治理投影回归为
`27 passed`。4 个 skip 均为 Windows 无法真实提供的 POSIX mode、symlink/descriptor 或非 root 容器边界，未计作通过。
两个生产 Python 文件增量 mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、
`git diff --check`、完整架构扫描与增量架构扫描均通过，1,000 行文件门槛未放宽。module map 为 `44 modules / 210 edges`，
Data Center entrypoint inventory 为 1,299 条，均由唯一生成器重建并通过检查。

未验证风险与停止线：本门禁尚未在任何 fresh S6 中实证；正在准备或已经结束的历史 attempt 均不能作为本提交证据，也不得 resume。
Windows 跳过的 POSIX 权限、symlink/descriptor 和非 root 容器反例必须由下一轮 Linux CI 与 fresh S6 补齐。统一 preflight 覆盖当前已知
六类环境假设，但不能证明环境类别已经穷尽；runner 启动前的 SSH/DNS/host-key、远端 shell/bootstrap 以及未来新型外部依赖仍可能形成
未知类别，发现后必须登记矩阵和补门禁，不得静默跳过或收窄断言。此切片没有启动 S6、部署、生产全市场或 financial refresh，也没有
修改生产路由、周期入口或凭据。full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 继续禁止重跑，financial refresh 仍需用户
新的明确授权，两个周期入口继续 disabled；普通用户生产会话仍未提供。

下一片是否可开始：本切片代码和 exact-SHA 五组 CI 已满足进入下一候选准备阶段的代码门槛；实际运行只允许在后续新候选上创建全新
fresh S6，从最新生产只读快照重新导出 provider settings、完整 identities、动态 universe 与 unit contract，禁止 `--resume`，并要求
prebuild 与全部阶段环境报告进入 manifest、release validator 和 handoff receipt。fresh S6 未完整通过前，不得把本门禁表述为已在真实
环境验证，也不得进入 receipt-only 部署。

##### 2026-10-07 Data Center 入口投影稳定身份整改

完成项：提交 `b794a0be7d8c6757ef3c4ecda06ab8476805f07e` 将 Data Center 入口投影中的源码位置与治理身份分离。
所有原先使用 `line:<n>` 的入口统一按 `category + path + symbol + target` 形成稳定语义身份；同一路径内完全相同的真实入口仅用确定性
`occurrence` 序号消歧。GitHub Actions workflow step 不再以可变的展示名作为身份，而以实际数据库操作 target 作为身份。插入空行、
移动代码或重命名 step 不再改变投影；新增、删除或更换真实数据库操作仍会改变条目和 ID，扫描范围、治理状态与 fail-closed 行为没有
缩减。validator 新增反例，任何生成结果残留 `line:` locator 均以 `entry_locator_volatile` 拒绝。

本地提交链路新增 `pre-push` 只读门禁，直接运行唯一生成器 `python scripts/data_center_entrypoint_inventory.py`；它不自动改写工作树，发现
真实入口变化时要求显式执行 `--write` 并审阅、提交投影。工程护栏文档已更新安装命令，Consistency 与 Fast Feedback 继续执行同一
生成器校验，未修改扫描规则或跳过失败组。投影由唯一生成器重建为 `1,298` 条，其中 `322` 条使用稳定语义 locator，重复 ID 为 `0`，
workflow step `11` 条。

测试计数：Data Center entrypoint inventory 专项 `26 passed`，包含无语义 workflow 标签/行移动不变、真实 dispatch 变更必变、重复语义
入口稳定消歧三个新增用例；唯一生成器 stale check 通过。生产脚本增量 mypy 为 `0 regression`，全仓 debt ceiling 为
`0 errors in 0 files`；Black、isort、Ruff、`git diff --check`、governance consistency `0 violation`、pre-commit YAML 解析均通过。
本机基础 Python 未安装 `pre_commit` 包，无法运行其框架级 `validate-config`；门禁实际 entry command 已独立运行通过，配置仍须由新的
exact-SHA CI 与安装了 pre-commit 的开发环境继续验证。

未验证风险与停止线：稳定身份消除了已知的行号和 workflow 展示名漂移，但不能证明未来不会出现新的非语义字段；新增扫描类别必须用
语义字段并继续接受 `entry_locator_volatile` 反例。当前提交尚未 push，也未绑定新的五组 exact-SHA CI，尚未创建 fresh S6、handoff
receipt、同镜像部署或部署后只读 UAT。生产 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 继续禁止重跑，生产 financial
refresh 未获授权，两个周期入口保持 disabled；普通用户生产会话仍未提供。

下一片是否可开始：可以提交本节台账并 push 新 HEAD，重新绑定五组 exact-SHA CI。只有五组全绿且 Publication PostgreSQL artifact
中的 financial slice、Account outer-fence 与 5,001-member soak 节点零跳过/零失败后，才可从最新生产只读快照创建 fresh S6；禁止
`--resume` 或复用旧 receipt/镜像。

##### 2026-10-07 S6 runner 运维依赖契约整改

完成项：fresh attempt `2ef31abad54c455aa051388a73ed37b5` 的生产只读快照、4 个完整 provider identities、5,572 个动态
证券、unit contract、526 migrations、隔离 PostgreSQL/Redis 及两层只读路由门禁均通过，但宿主启动 wrapper 调用不存在的
`python`，在候选 runner 启动前 exit 127；诊断 SHA256 为
`1e28d050315d04cff8f6b25c116392874f50f7774ec8a7feccfca2767f138f02`。该 attempt 没有 S6 stage、构建、provider 请求或生产写，
根目录与诊断保留，精确匹配的 disposable 隔离资源已清理，禁止 resume。

第二个 fresh attempt `d130ee2d5b514092bad8fd3d05173542` 使用实际存在的 `python3` 启动 runner，prebuild 环境矩阵通过，随后
`build_only` 在 1 秒内以 `S6_STAGE_COMMAND_FAILED` 阻断。安全复核确认 Docker/network/隔离服务门禁均通过，但 VPS 的
`/usr/bin/python3` 无 `paramiko`，而 `remote_build_deploy_vps.py` 在 SSH 前需要该模块；远端构建报告、候选镜像、provider 请求、
生产写与 handoff receipt 均为 0。稳定诊断 `REHEARSAL_STAGE_RUNNER_DEPENDENCY_MISSING` 的 SHA256 为
`44f1397410403f2fe7263f7adee01811877a6756c71b91ef9bb2b51c3a2c851c`；失败 attempt 完整保留，隔离资源按 plan 身份清理，禁止
resume。

根因不是单次 VPS 漏装包，而是 operational entrypoint 的运行时依赖没有进入 `pyproject.toml` 真源，既有统一 preflight 也没有在
远端构建前检查它。提交 `3c2576949` 最初新增精确 `paramiko==4.0.0` 的 `ops/dev/all` 依赖，唯一生成器新增最小
`requirements-ops.txt` 投影；S6 prebuild 和最终环境报告都检查 remote builder 依赖可导入，缺失时仅在 `build_only` 单元格以
`REHEARSAL_STAGE_RUNNER_DEPENDENCY_MISSING` fail closed，不泄露模块名或解释器路径。quick reference 统一要求 attempt 私有 venv
从 `requirements-ops.txt` 安装，避免修改系统 Python 或依赖人工遗留环境。

exact-SHA Security `37619267722` 随即正确阻断 Paramiko 4.0.0 的 `CVE-2026-44405 / PYSEC-2026-2858`；Safety 与
pip-audit 均各报告 1 个漏洞，其他 npm、Bandit 与 gitleaks 节点通过。整改没有新增 ignore 或放宽扫描门槛：`ops/dev/all`
经提交 `e8e90db0f` 统一改为上游已删除 RSA/SHA-1 支持的不可变提交
`a4489456b6f65281e172380cc4826cee5e851dbb`，其构建元数据版本为
`5.0.0`；投影仍只由 `sync_dependency_projections.py` 生成。runner 现在同时验证模块存在和版本精确为 `5.0.0`，错误版本与
缺失模块使用同一不泄露依赖细节的稳定业务码失败关闭；guardrail 固定上游 commit，防止回退到已知脆弱 release。

测试计数：runner、六类环境矩阵、远端构建器、planner、manifest、validator 与依赖投影组合更新为
`314 passed / 6 skipped`；全新私有 venv 已从上游固定 commit 构建
`paramiko 5.0.0`，运行时 `RSAKey.HASHES` 仅保留 `rsa-sha2-256/512` 及证书变体，Safety 为 `0`、pip-audit 为 `0`。
此前 runner、六类环境矩阵与依赖真源组合为 `111 passed / 3 skipped`；加入 release validator 的组合为
`215 passed / 3 skipped`。本次 6 个 skip 均为 Windows 无法提供的 POSIX symlink/ownership、descriptor 或非 root 容器边界，
未计作通过。三个生产/运维 Python
文件增量 mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、`git diff --check`、依赖投影
check、Data Center entrypoint inventory `1,298` 条、module map `44 modules / 210 edges` 和 governance consistency `0 violation`
均通过。

未验证风险与停止线：`e8e90db0f` 与本节更新尚未 push，也未绑定新的五组 exact-SHA CI；attempt 私有 ops venv 尚未在 fresh S6
实证。宿主 shell/SSH/DNS/host-key 仍位于 runner 自检之前，未知环境类别风险继续保留。生产 full-market task
`bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，生产 financial refresh 未获授权，两个周期入口保持 disabled；普通用户生产
会话仍未提供。

下一片是否可开始：可以提交本节台账、push 新 exact SHA 并启动五组 CI。五组全绿且 Publication PostgreSQL artifact 的 financial
slice、Account outer-fence 与 5,001-member soak 节点零跳过/零失败后，才能用 `requirements-ops.txt` 创建 attempt 私有 runner venv，
从最新生产只读快照创建全新 S6，禁止 `--resume` 或复用上述失败 attempt 的输入、镜像和阶段证据。

##### 2026-10-07 S6 构建后资源保留与动态报告传输契约整改

完成项：候选 `c3e1527bd31d7067c732cdcc9ae395cf9c5ce80a` 的五组 exact-SHA CI 和 PostgreSQL artifact 均通过后，fresh S6
attempt `98c8bcbe3bb34f2e9c6c56fb68504bf0` 从最新生产只读快照完成 prepare、`build_only` 和 `docker_identity`，但统一
`stage_environment_preflight` 以 `REHEARSAL_STAGE_ENVIRONMENT_PREFLIGHT_FAILED` 正确阻断。终态同时列出
`REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT` 与 `REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID`，当时可用空间为
`5,254,950,912` bytes；没有 provider 请求、生产写或 handoff receipt。失败诊断 SHA256 为
`70623dc0d36ba52de16143dd1e21e7af37e3339c13d60b2b2c2e15a192781029`，attempt 根目录与诊断保留，隔离
PostgreSQL/Redis/network/volume 已按精确身份清理，禁止 resume。

根因有两项。第一，prebuild 与构建后阶段共用 12 GiB 门槛，prebuild 只证明起跑时有 12 GiB，没有为镜像、tar、runtime zip 和
build cache 保留构建工作集，导致昂贵构建完成后才发现后续证据阶段余量不足。第二，候选 management command 输出本身是合法 JSON，
但镜像 entrypoint 在 stdout 先写入 Redis/PostgreSQL readiness 三行；runner 错把整段 stdout 当成一个 JSON 文档。只读复现为 exit 0、
stdout 末行合法 `release.s6-stage-environment-preflight.v1`，证明不是动态探针业务失败。

完成项（`dcb8b6151`）：release policy 新增 24 GiB 构建前最低空间，其中 12 GiB 是构建保留量，后续阶段原 12 GiB 硬门槛保持不变；
prebuild 报告显式记录本次适用的最低空间，validator 分别按 24/12 GiB 对账，低于 24 GiB 时在 `build_only` 前失败关闭。动态探针改为
在候选容器的绑定 evidence 目录排他写入 regular JSON 文件，宿主只读取有界文件并校验 schema、阶段和稳定码 allowlist；entrypoint、
readiness 和框架 stdout 不再属于结构化传输契约。输出已存在、畸形、缺失或命令失败均保持 fail closed；没有清全局 cache、降低阈值、
扩大 timeout/retry 或增加 provider/业务写副作用。

测试计数：统一环境、候选命令、runner 与 validator 组合为 `221 passed / 3 skipped`；remote builder、attempt planner 和 manifest 组合为
`95 passed / 3 skipped`，合计 `316 passed / 6 skipped`。6 个 skip 均为 Windows 无法提供的 POSIX 权限、symlink/descriptor 或非 root
容器边界，未计作通过。新增反例覆盖 24 GiB 前置不足在构建前阻断、stdout readiness 噪声不影响文件报告、畸形绑定报告拒绝、既有
输出不覆盖。四个生产/运维 Python 文件增量 mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、
Ruff、`git diff --check`、Data Center entrypoint inventory `1,298`、module map `44/210`、governance consistency `0 violation` 全部通过。

未验证风险与停止线：24 GiB 门槛按当前构建工作集保留 12 GiB，但不能证明未来镜像增长永远不超过该保留量；后续如增长必须先扩容或形成
新的容量证据，不得降低后续阶段 12 GiB。`dcb8b6151` 尚未 push 或绑定新 exact-SHA 五组 CI，也尚未在 fresh S6 验证文件报告和
24 GiB 门槛。生产 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，两个周期入口保持 disabled；普通用户生产
会话仍未提供。Financial 正式发布已获用户授权，但 N<=1/2N<=2 治理上限继续有效，不能用循环小批次规避容量评估。

下一片是否可开始：可以提交本节台账并 push 新 exact SHA，重新运行五组 CI。五组全绿后须先把 VPS 可用空间恢复到至少 24 GiB，且仅清理
无引用、无 active build 的可回收资源；随后从最新生产只读快照创建全新 S6，重新导出全部输入并禁止 `--resume`。完整十阶段、财报
N=1 双原件、release validator 与 receipt 通过后，才可部署同 SHA 预构建镜像。

##### 2026-10-07 Data Center architecture 投影稳定语义整改

根因证据：候选 `2d5a8e7de8b607b329a3b1cccb78e3d3a42365e8` 的 Architecture `37637504112` 与 Security
`37637505122` 已通过，但 Consistency `37637504311` 在 `Enforce deterministic Data Center architecture inventory`
正确失败。S6 preflight management command 仅新增一个标准库 import，使两个未变更的 current-surface 引用从 48/49 行移动到
49/50 行；旧 architecture projection 把 AST/源码行号写入治理 JSON 并做字节级 stale check，因而把非语义行移动误判为治理事实变化。
旧 run 禁止重跑；其余旧 SHA 结果不能作为新候选证据。

完成项（`841f6733c2e8646ac8d6090a7357e9971f94253d`）：architecture inventory schema 升为 `2.0`，唯一生成器在全部 import、
legacy fact、current surface 与 Celery task 引用进入投影前统一删除易变 `line`，按路径和语义内容的规范 JSON 确定性排序，并保留重复
语义引用及全部原有计数。插入空行、注释或整体移动未变引用不再改变投影；provider、路径、引用文本等真实语义变化仍改变投影。
扫描范围、规则和 fail-closed 条件没有缩减。pre-push 新增 architecture inventory 只读检查，并与既有 entrypoint inventory 门禁并列；
CI 的 Consistency/Fast Feedback 检查继续保留。投影由唯一生成器重建，条目计数保持 current surface `5,392`、cross-app ORM
`48`、Celery task `65`、runtime parameter `56`、批准的非数据 HTTP `5`，provider/直接 Data Center/待复核 HTTP/legacy 引用均为 0。

测试计数：architecture inventory 专项 `7 passed`，包含完整 `build_inventory()` 的抗空行/注释回归和真实 provider 引用变化反例；
唯一 architecture/entrypoint 生成器检查通过，entrypoint 总数保持 `1,298`。生产脚本增量 mypy 为 `0 regression`，全仓 debt ceiling
为 `0 errors in 0 files`；Black、isort、Ruff、`git diff --check`、module map `44/210`、governance consistency `0 violation`
全部通过。

未验证风险与停止线：schema 2.0 的一次性生成投影差异较大，新的 exact-SHA 五组 CI 尚未运行；pre-push 仅在开发者安装相应 hook
后执行，CI fail-closed 仍是强制真源。删除源码行号后，人工定位依赖路径与语义内容搜索；重复引用仍保留但不提供展示行号。稳定语义覆盖
已知 architecture/entrypoint 两类投影，不能证明仓库其他或未来投影没有易变字段；新增投影类别必须增加相同的非语义移动正向测试和
真实语义变化反例。fresh S6 尚未开始，生产 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 继续禁止重跑，两个周期入口
保持 disabled；普通用户生产会话仍未提供。Financial 正式发布授权继续受 N<=1/2N<=2 治理上限约束。

下一片是否可开始：可以提交本节台账并 push 新 exact SHA，重新绑定五组 CI。只有五组全绿且 Publication PostgreSQL artifact 的
financial slice、Account outer-fence 与 5,001-member soak 节点零跳过/零失败，才可从最新生产只读快照创建新的 fresh S6；禁止
`--resume` 或复用失败 attempt 的镜像、输入和阶段证据。

##### 2026-10-08 stable projection 候选部署与 readiness 慢路径整改

完成项：architecture stable projection 候选 `43dbd8345bc0a2df3200c8bbea43b5e63bbf9098` 的五组 exact-SHA CI 全绿：
Architecture `37640822538`、Security `37640822558`、Consistency `37640822708`、Fast Feedback `37640822670`、
Publication PostgreSQL `37640893754`。PostgreSQL artifact 已复核 financial slice sync `8/0/0/0`、Account outer-fence
`8/0/0/0`、Publication `42/0/0/0`，包含 AKShare 原子写、generation-fenced graph UOW 和 5,001-member soak 固定节点，
零跳过、零失败、零 error。

fresh S6 attempt `c3971ca6bc82420fb80c43c1475a8085` 从最新生产只读快照重新导出 4 个完整 provider identities、
provider settings、5,572 个动态 universe 成员及 unit contract，使用隔离 PostgreSQL/Redis、禁止 `--resume` 完成完整十阶段、
财报 AKShare N=1/2N=2、统一环境 preflight 与 release validator，outcome=`success_evidence`、runner exit 0。handoff receipt
SHA256 为 `ee2e2d926cf01926b911d4a268396691ba44bfc7b3e249e1330144cbb49a4124`，manifest SHA256 为
`a09d77a26fc26843035e4442db832dc9191f6d8349daaa92242f07815bf10384`，release tag 为 `20261007172022`，预构建镜像为
`sha256:41e5b6c4d26f94aac0410c8fcaa463543b97e718bb936ef0b6033b025678a88c`。生产严格复用该镜像部署，report SHA256 为
`cc7b59007051716775e51b04c66eaacf38e8642a251e01660dc30faf671cd83c`；current、运行 Web/三个 Celery image 与 OCI revision
均绑定候选，526 migrations applied / 0 unapplied，health、PostgreSQL、Redis、Prometheus 与 RSSHub 正常，statement logging
为 `none/-1/-1`。部署没有投递 full-market 或 financial refresh，两个受保护周期入口继续 `enabled=false`。

只读生产对账确认 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 仍为业务 success，
`requested/succeeded/failed/stored=5572/5572/0/11144`、`published_members=16705`、publication run
`aebb0da7-5336-4460-8fff-e4aa0f0317a7`；quote/price/valuation 三个 current pointer 仍以同一 activation
`19d9a93e-55b6-5b8e-882d-8f3160f560dc` 指向已发布、未阻断且带有效 policy version/source time 的 Publication。
full-market lease=false。`/api/health/` 为 200/0.056 秒，`/api/decision-ready/` 为 503/0.115 秒并保留
`must_not_use_for_decision=true`；`/api/ready/` 虽为 200/degraded，却实测 25.881 秒，因此不能视为 UAT 通过。

readiness 分段剖析将慢路径精确定位为 `alpha_workspace_consistency=19.862s`、Celery ping `3.637s`、decision data
`2.374s`。Alpha 一致性只消费 Qlib 状态，却调用全部 provider 深度检查；其中 qlib `0.211s`、cache `0.012s`、simple
`27.148s`、ETF `0.012s`。Simple 慢路径又由 publication-bound quote payload 读取贡献 `20.881s`，不是网络 timeout。
提交 `7540dd9f4` 为 Alpha provider status 增加显式 provider-name scope，一致性只探测实际消费的 qlib；同时在全局决策门已
阻断时让 service readiness 保留 `decision_readiness_blocked` 稳定投影并跳过重复的 decision-data/Alpha 深诊断。正式 Publication
member bound、freshness、coverage、source 与 provider 深度诊断入口均未放宽。

测试计数：受影响 health/Alpha consistency/provider 组件与 guardrail 回归 `68 passed`，其中新增四个红绿契约验证全局阻断短路、
开放状态仍保留一致性结果、仅探测 qlib、未选 provider 零调用；三个生产文件增量 mypy 为 `0 regression`，全仓 debt ceiling 为
`0 errors in 0 files`。Black、isort、Ruff、`git diff --check`、entrypoint inventory `1,298`、architecture inventory
`5,392/48/65/56/5`、module map `44/210`、governance consistency `0 violation` 全部通过。

未验证风险与停止线：`7540dd9f4` 之后还包含并发完成的 CI 成本整改 `76b5dcc24`，两者均晚于已部署的 `43dbd8345`；必须把本节
台账提交后的新 HEAD 作为新的 exact-SHA 候选重新跑五组 CI、fresh S6 与同镜像部署，才能复测 `/api/ready/` 真实延迟，禁止把旧
部署当作新修复证据。Simple provider 的全量 status 诊断仍会执行严格 publication-bound 读取，尚未做查询优化；本切片只消除 readiness
对无关 provider 的隐式调用。生产 full-market task 禁止重跑，两个周期入口保持 disabled；Financial 正式发布授权仍受 N<=1/2N<=2
治理上限约束，普通用户生产会话仍未提供，API/SDK/MCP 与普通用户主流程联合 UAT 尚未完成。

下一片是否可开始：可以提交并 push 本节台账，绑定新 HEAD 的 Architecture、Security、Consistency、Fast Feedback 与 Publication
PostgreSQL。五组全绿且固定 PostgreSQL 节点零跳过/零失败后才能从最新生产只读快照创建新的 fresh S6，禁止 `--resume`；S6 全部
通过后只部署 receipt 绑定的同 SHA 镜像，再复测 readiness 时延并继续 signal API/SDK/MCP、Alpha、业务阻断语义和零副作用 UAT。

##### 2026-10-08 最终候选 S6、同镜像部署与只读联合 UAT

完成项：最终候选 `1d52b12a17ebcb087bdf1ddcdef28b72481fb91c` 的五组 exact-SHA CI 全绿：Architecture
`37656854621`、Security `37656854464`、Consistency `37656854465`、Fast Feedback `37656854522`、Publication
PostgreSQL `37656960713`。PostgreSQL artifact 已复核 Account final revalidation `8/0/0/0` 并包含
`test_postgres_generation_fenced_graph_uow_reuses_outer_transaction`，financial slice sync `8/0/0/0` 并包含
`test_akshare_financial_slice_sync_uses_exact_approved_route_and_one_atomic_write`，Publication `42/0/0/0` 并包含
`test_activation_5001_members_has_fixed_queries_locks_and_retry`；固定节点零跳过、零失败、零 error，5,001-member 查询硬阈值未放宽。

fresh S6 attempt `f06cac3ffd73410589b1c1f1ee851fd2` 从最新生产只读快照重新导出 provider settings、4 个完整 identities、
5,572 个动态 universe 成员与 unit contract，在隔离 PostgreSQL/Redis、真实 provider、禁止 `--resume` 的条件下完成十阶段、统一
stage environment preflight、财报 AKShare N=1/2N=2 双原件/双 RawAudit/typed evidence/单批原子写/零写失败反例和 release
validator，outcome=`success_evidence`、exit 0。handoff receipt SHA256 为
`e65e9c4373c080b1a0c348e0a193806449894da8f7ba820ab06eaee29b0f7c20`，manifest SHA256 为
`d465c77765a0b34d6cba2f095cfad30bb2b623e558a0ecab89098a3fc1b1e084`，release tag 为 `20261007193250`，预构建镜像为
`sha256:73e8005aeead0891560b022b3f13322694e622eb9a433ec59cf4f639ba1fce46`。生产严格复用该 receipt 绑定镜像部署成功，
current=`/opt/agomtradepro/releases/source-20261007193250`，部署 report SHA256 为
`1b05ff9765676bbba5122131dc03d00294d110e4c36cb614da851e7b19e404ff`；运行 Web/Celery OCI revision 与候选一致，526
migrations applied / 0 unapplied，服务健康，provider route preflight 通过，statement logging 为 `none/-1/-1`。部署未投递
full-market 或 financial refresh，`full-market-current-publications` 与 `financial-current-publication-refresh` 均保持
`enabled=false`。

只读正式发布对账确认 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 仍为业务 success，
`requested/succeeded/failed/stored=5572/5572/0/11144`、`publication_updated=true`、run
`aebb0da7-5336-4460-8fff-e4aa0f0317a7`。price/quote/valuation 三个 current pointer 仍由 activation
`19d9a93e-55b6-5b8e-882d-8f3160f560dc` 原子绑定：price `5561` members、quote `5572`、valuation `5572`，各自
Publication ID/hash/policy version/source/as-of 完整，`must_not_use_for_decision=false`。`/api/health/` 为 200/21.756ms，
`/api/ready/` 为 200/degraded/3175.104ms，已从旧部署的 25.881s 慢路径恢复到团队响应目标内；`/api/decision-ready/` 为
503/blocked/42.534ms 且 `must_not_use_for_decision=true`，继续诚实反映财报正式发布未恢复。

API/SDK/MCP 只读联合 UAT 使用既有 privileged read-only operator token，没有创建、轮换或暴露凭据。signal 默认查询、显式
`offset=0`、分页、状态过滤、证券过滤、组合过滤和确定为空的列表在三层均正常完成；当前真实结果为 0 条，没有造数，MCP 返回
`status=completed` 和空数组。Policy 三层一致保留 `PX`、中文“待分类”、`policy_unclassified_manual_review`、
`requires_manual_approval=true`、`must_not_use_for_decision=true` 与观测日期。Regime、动态选取 current valuation member 的估值分析、
财报历史在 API 503、SDK typed `ServerError`、MCP error envelope 三层均保留 `decision_runtime_blocked`、中文原因、changed-at、
责任角色和 `must_not_use_for_decision=true`，未压缩为 `capability_execution_failed`。`dashboard.read.alpha_history` 对真实 50 条 list
响应在 API/SDK/MCP 三层内容一致；Task Monitor 三层一致返回上述业务 outcome、四项统计、目标交易日与 publication run ID。

零副作用对账在每组 API/SDK/MCP 探针前后分别验证 TaskExecution、Alpha cache、decision snapshot、recommendation 与 token 数量完全
不变。覆盖整个只读窗口的 PostgreSQL read-only/repeatable-read 聚合快照进一步证明 Alpha candidate/run/snapshot、Alpha cache、
decision input/feature、valuation snapshot、investment/unified recommendation 与 signal 的 count 和内容 digest 均未改变；只允许 MCP
READ 审计追加。TaskExecution 在长窗口净增 119 条，逐项归因为已有分钟级监控、agent-runtime maintenance、audit authority、storage
budget、policy SLA/gate 与 realtime/broker maintenance 周期任务；没有 full-market、financial refresh、Alpha inference 或建议生成任务。
证据已密封到
`/opt/agomtradepro/rehearsals/s6-1d52b12a17-f06cac3ffd73410589b1c1f1ee851fd2/evidence/postdeploy-uat`，manifest
SHA256 为 `c889cb4a12fc91e13536b7630f964cc34c11423d667768fa64090027ee13488a`，六份子证据逐文件 SHA256 由 manifest 绑定。

测试计数：五组 CI 全绿；固定 PostgreSQL JUnit 合计 `58 passed / 0 skipped / 0 failure / 0 error`；fresh S6 `10/10` 阶段和
release validator 全部通过；signal/policy/regime MCP 共 `10` 次 read capability 调用完成，估值/财报/Alpha history/Task Monitor
另 `4` 次 read capability 调用按各自正常或稳定阻断契约通过。两组 bounded business-count 对账均为 before=after；长窗口除允许审计与
已分类的后台 TaskExecution 外，`10` 类禁止写入业务模型 count/digest 精确不变。

未完成项、未验证风险与停止线：财报 current publication `c8741812-cf01-512f-8d1c-91c0e6549f42` 仍是 legacy policy
`1.0:1.0`、as-of `2026-04-29`、80 members；当前治理 policy version 为 3，decision runtime 因
`canonical_publication_policy_version_mismatch` 正确 fail closed。不得把三类行情/估值发布写成四类全部恢复；生产 financial refresh
仍需用户新的明确授权，N<=1/2N<=2 的 S6 ceiling 不能外推为全市场容量，禁止伪造 owner approval。生产 full-market task
`bcb3e00f-538e-420d-b179-428c40082f43` 继续禁止重跑。普通用户 active token 为 0，用户也未提供已有合法普通角色浏览器会话；本轮
只能提供 privileged read-only operator 的 API/SDK/MCP 证据，不能冒充普通用户完成候选详情、账户选择和页面主流程，因此普通用户
生产页面 UAT 明确未完成。长窗口存在正常后台任务并发，虽然逐组 bounded 对账证明本次 GET/MCP 没有产生任务，聚合窗口不能把所有
TaskExecution 行级变化表述为全局静止。结论为“部分通过/仍有阻断”，不能宣称全面恢复。

下一片是否可开始：代码、CI、fresh S6、同镜像部署、正式行情/报价/估值发布与 privileged read-only 联合 UAT 已收口。后续只允许在
用户新授权后设计并执行生产 financial refresh；在合法普通用户会话可用后补普通用户页面主流程。两项停止线未解除前，保持两个受保护
周期入口 disabled，不投递任何 full-market/financial refresh，也不解除 decision runtime 保护。

##### 2026-10-08 普通用户生产 UAT 基线与阻断 Alpha 读取有界化整改

完成项：按用户明确授权创建/重置生产普通用户 `user`，保持 `is_staff=false`、`is_superuser=false`、active，未创建 API/MCP token、未伪造协议或风险确认；该用户拥有独立模拟账户与实盘账户。使用真实普通用户浏览器会话完成登录、账户读取、Dashboard 候选到 Workspace Step 4 的动态证券/账户跳转、研究详情和阻断解释复验；Admin 明确拒绝访问，ops Task Monitor 返回 403。Workspace 对候选 `688011.SH` 正确绑定模拟账户并在正式决策链路仍阻断时展示研究详情、零建议和解释，没有自动刷新或生成建议。

生产基线显示 Alpha GET 为 29.542 秒、Dashboard 为 44.838 秒、候选 Workspace 为 12.339 秒。分段只读剖析定位为四类重复成本：被 `must_not_use_for_decision` 阻断的 Alpha 仍校验 price/financial/valuation/quote 完整发布图；5,572 证券 scope 已超过 simple provider 上限却在 admission 前运行深度 health check；最新 full-market 已业务成功仍为旧失败执行三套 Publication 恢复证明；公共 meta 回传完整 5,572 个证券代码。读取窗口前后业务模型 count/digest 保持不变；新增 TaskExecution 均来自既有周期任务，没有 full-market、financial refresh、Alpha inference 或建议生成。

整改提交 `c349bd5d3` 将上述四类按契约收口：阻断或通用研究结果只读取 canonical asset master，决策可用结果仍保留完整 Publication/quote 校验；simple provider 用既有同步 pool ceiling 在 health I/O 前拒绝不支持 scope；只有最新 full-market 终态是失败/部分完成时才执行 Publication 恢复证明；公共 scope metadata 只保留 pool size/hash/universe 等摘要，任务、缓存与持久化仍使用完整 scope。完整 stock context 仅在本地主数据 name/sector/market 全缺失时逐资产 fallback，未放宽 freshness、coverage、source、audit 或 `SIGNAL_WEAK=0.6000`。

测试计数：相关 Alpha provider/domain、Dashboard runtime/repository/refresh notice/read-only 契约共 `116 passed`；格式化后的核心子集复跑 `73 passed`。9 个生产文件增量 mypy 为 `0 regression`，补充 gateway 增量 mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、`git diff --check`、governance consistency `0 violation`、module map `44/210` 均通过。Data Center entrypoint 唯一生成器仍为 `1,298` 条、architecture inventory 保持 `5,392/48/65/56/5`，本次生产代码行移动没有产生治理投影差异，证明稳定语义整改已覆盖本次场景。

未验证风险与停止线：`c349bd5d3` 尚未 push、未绑定 exact-SHA 五组 CI，未经过 fresh S6、同 SHA 镜像部署和部署后普通用户延迟复测；当前只能证明本地契约与生产慢路径根因。静态资源 `echarts.min.js`、`mermaid.min.js` 曾出现 `ERR_CONNECTION_CLOSED`，需在部署后浏览器 UAT 复测。Financial current publication 仍为 legacy policy 且全市场容量没有合格证据；N<=1/2N<=2 不能外推，禁止生产 financial refresh、伪造 owner approval 或解除 decision runtime。full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，两个周期入口保持 disabled。

下一片是否可开始：可以提交本节台账并 push 新 HEAD，启动五组 exact-SHA CI。五组全绿且固定 PostgreSQL artifact 节点零跳过/零失败后，才可从最新生产只读快照创建 fresh S6，禁止 `--resume`；S6 与 release validator 通过后只部署 receipt 绑定镜像，再用同一普通用户复测 Alpha GET、Dashboard、候选 Workspace、权限隔离、静态资源与零副作用。

##### 2026-10-08 普通用户生产 UAT、当前 SDK/MCP 复验与证据链收口

完成项：Alpha 阻断读取有界化最终候选 `d3fdbd6f1ce8a1b77c4ba4fec923d651f4a2b7df` 的五组 exact-SHA CI
全部通过：Architecture `37718839202`、Security `37718839203`、Consistency `37718839256`、Fast Feedback
`37718839297`、Publication PostgreSQL `37718898033`。PostgreSQL artifact 中 Account outer-fence `8/0/0/0`、
financial slice `8/0/0/0`、Publication `42/0/0/0`，包含 generation-fenced graph UOW、AKShare 单批原子写与
5,001-member soak 固定节点，零跳过、零失败、零 error。

fresh S6 attempt `dd545cdd59bd4e7683e52df6ee700fbf` 从最新生产只读快照重新导出 provider settings、4 个完整
identities、5,572 个动态 universe 成员与 unit contract，在隔离 PostgreSQL/Redis、真实 provider、禁止 `--resume` 的
条件下完成十阶段、统一环境 preflight、财报 AKShare N=1/2N=2 双原件/双 RawAudit/typed evidence/单批原子写/零写
失败反例和 release validator，outcome=`success_evidence`、exit 0。handoff receipt SHA256 为
`2585d32289a35a727e3c16867065053ecbcd48a107fd48c7454586092c259212`，manifest SHA256 为
`c058a6182956fd98e27b952024d7de8588114126da7bf8549aa4d67f4f1afeab`，release tag 为 `20261008050500`，
预构建镜像为 `sha256:da482ea1210f0b486852e97b83eb7437577aa957efb872b1f06e8c5c725b1996`。生产严格复用该
receipt 绑定镜像部署成功，current=`/opt/agomtradepro/releases/source-20261008050500`，部署 report SHA256 为
`50bec407407f44e1a2ed3ae63ce775162ccb5e7ad817e1c0982f20661db22011`；运行 Web/三个 Celery 容器的 OCI
revision 与候选一致，526 migrations applied / 0 unapplied，provider preflight 通过，statement logging 为
`none/-1/-1`。两个受保护周期入口继续 `enabled=false`，full-market lease=false。S6 成功和 receipt 存在性复核后，仅删除该
attempt 的精确隔离 PostgreSQL/Redis/network/volume；生产容器及候选镜像未变化，attempt 根目录和全部证据保留。

按用户明确授权创建/重置普通用户 `user`，保持 active、`is_staff=false`、`is_superuser=false`，关联独立实盘和模拟账户；没有为该
用户创建 API/MCP Token，UAT 结束后 active token 仍为 0。真实普通用户浏览器会话完成登录、Dashboard 候选、账户选择和
`688011.SH` Workspace Step 4 跳转：模拟账户绑定正确，研究详情和阻断解释可见，建议数为 0，页面只提供显式刷新动作；Admin 重定向
到管理员登录，ops Task Monitor 返回 403。Dashboard 服务端实测 7.387 秒，候选 Workspace 导航 3.892 秒；Alpha API 冷读
4.488 秒、同会话热读 0.485 秒，相比整改前的 44.838/12.339/29.542 秒慢路径已恢复。ECharts 和 Mermaid 静态资源均为
200，大小分别为 1,024,695 与 2,963,890 bytes，浏览器 console error 为 0。

普通用户 API 复验覆盖 signal 默认、显式 `offset=0`、分页、状态、证券、组合过滤及确定为空列表，全部 200 且返回规范空数组；
Alpha 返回 10 个研究候选、`must_not_use_for_decision=true`、`async_refresh_queued=false`、空 task ID，不回传完整
instrument code scope。普通用户 Alpha history 返回其账号范围内的规范空列表；账户 API 返回 2 个账户。Regime、估值、财报均返回
503、稳定码 `decision_runtime_blocked`、`changed_at` 与 `must_not_use_for_decision=true`；decision-ready 同样诚实返回
503/blocked。普通用户访问 Task Monitor API 为 403，符合最小权限。最新外部探针为 health 200/54.648ms、ready
200/degraded/3446.805ms、decision-ready 503/168.627ms，ready 保持团队响应目标内。

当前精确候选的 SDK/MCP 使用既有管理员 read-only operator Token；没有创建、轮换、持久化或输出凭据。SDK 与 MCP 的 signal 七种
查询全部正常完成并返回 0 条，MCP `status=completed`。Policy 两层均保留 `PX`、中文“待分类”、
`requires_manual_approval=true`、`policy_unclassified_manual_review`、`must_not_use_for_decision=true` 和观测时间。
SDK 的 Regime/估值/财报返回 typed `ServerError`，MCP 返回 error envelope；两层均保留 `decision_runtime_blocked`、中文原因、
`changed_at` 和决策禁用标记，没有压缩为 `capability_execution_failed`。Alpha history 两层均为 50 条；Task Monitor 两层一致
返回 full-market 业务 `outcome=success`、`requested/succeeded/failed/stored=5572/5572/0/11144`、
`publication_updated=true`、目标交易日 `2026-09-30` 和 run `aebb0da7-5336-4460-8fff-e4aa0f0317a7`。

零副作用对账对 10 类 Alpha cache、recommendation、decision snapshot、valuation snapshot 与 signal 模型执行调用前后完整内容
SHA256，count/digest 精确不变。普通用户浏览器/API 窗口后的 TaskExecution 增量全部归因为既有 Alpha monitor、agent-runtime
maintenance、audit authority、storage budget、policy gate/SLA、realtime、regime health 与 broker maintenance；
`data_center.refresh_full_market_publications`、`data_center.refresh_financial_publications_batch`、非 monitor Alpha 任务和
recommendation 任务增量均为 0。MCP 只新增 13 条 `MCP_CALL/READ` 审计。密封证据位于
`/opt/agomtradepro/rehearsals/s6-d3fdbd6f1c-dd545cdd59bd4e7683e52df6ee700fbf/evidence/postdeploy-ordinary-uat`，
manifest SHA256 为 `6ccb5729efe6af9719322da300b927050dbdf1fee741a24d40dfe080702fa360`。

测试计数：五组 exact-SHA CI 全绿；固定 PostgreSQL JUnit 合计 `58 passed / 0 skipped / 0 failure / 0 error`；fresh S6
`10/10` 阶段与 release validator 全部通过。普通用户 signal API 7 个查询、账户/Alpha/Alpha history/health/ready/
decision-ready/Regime/Policy/估值/财报/Task Monitor 与 2 个静态资源均完成契约核对；当前候选 SDK 13 组、MCP 13 组读取完成，
其中三类决策接口按稳定阻断契约通过。普通用户页面、普通用户 API、SDK/MCP 三组 bounded 对账的 10 类业务模型均 before=after。

未完成项、未验证风险与停止线：Financial current publication 仍是 legacy policy identity，正式全市场容量没有合格证据；S6
N<=1/2N<=2 不能外推为全市场容量，未执行生产 financial refresh、未伪造 owner approval，也未解除 decision runtime。
Task Monitor 仍保留历史任务 `51cc8472-6963-4e63-aaf5-3253853b027f` 的 `started` 行：它绑定已退出的旧 worker、无
finished/result/exception，当前 active/reserved/scheduled 队列和 financial lease 均无对应任务；现有 retention policy 只在 7 天后将
stale active 标记 timeout，本轮不提前伪造终态。生产 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，
两个周期入口保持 disabled。结论为“部分通过/仍有阻断”，不得宣称四类正式发布或 decision runtime 已全面恢复。

下一片是否可开始：普通用户页面主流程、API/SDK/MCP 契约、性能、权限隔离和零副作用 UAT 已收口。只有先形成 production financial
全市场容量/请求预算/owner approval 的合格证据并获得用户新的明确授权，才能投递一次 production financial refresh；在此之前保持
财报与 decision runtime fail closed。历史 stale Task Monitor 行只能由现有 7 日 retention/reconciliation 规则产生可追踪终态，不得
人工改写或借此重跑财报任务。

##### 2026-10-08 Financial 正式发布容量与 owner approval 根因整改

根因：现有财报链路只有 S6 的单资产 `N=1 / 2N=2` 资格证据，没有覆盖生产 5,572 资产工作量的真实 provider 容量测量、精确请求预算、
全量 manifest 绑定和独立 owner approval。legacy financial current publication 因而仍使用 policy `1.0:1.0`，无法满足当前 policy v3 的
member-bound provenance，decision runtime 报 `canonical_publication_policy_version_mismatch` 是正确的 fail-closed 结果。直接循环
N=1 或复用旧批量任务无法证明全市场容量，也不能作为 owner approval。

完成项：提交 `92d308d48` 将 AKShare 双原件、双 RawAudit、typed source-time、事实写入和 request accounting 绑定到同一 capacity
run/slice lineage；逻辑请求与物理 transport attempt 分开计数，provider 发送前原子预留预算，超限在零业务写入下返回稳定码。提交
`af49dfc6e` 新增三阶段工作流：`qualification` 仅用于隔离 N=1 契约验证；`capacity_rehearsal` 仅在隔离环境按完整 active universe、
精确 2N 请求 ceiling 与双人治理事件测量真实规模；`formal` 仅接受 manifest/build/provider/policy/region 全绑定的成功 rehearsal receipt、
独立生产 ceiling 和已认证 owner approval。审批、撤销和 receipt 均为数据库不可变记录，审批人与录入人必须分离，撤销不可逆，审批与
receipt 只能消费一次；legacy `refresh_financial_publications_batch` 在参数校验后、provider 出网前以
`financial_capacity_receipt_required` 阻断。正式 activation 使用 candidate staging、pointer CAS、audit/outbox 原子切换，并覆盖 commit
unknown 恢复。持久化采用 compact checkpoint、immutable manifest item 和 append-only evidence ledger；每个 slice 的 manifest 复核、
证据追加与 checkpoint CAS 在同一事务内完成，避免把 5,572 项数组重复写入 checkpoint。typed evidence 全局扫描硬上限为 600,000 行，
依据生产只读快照 487,624 行校准，超限继续 fail closed。提交 `c113d6f64` 将 stage/activation commit-unknown、audit rollback、并发 CAS
单赢家、5,572 manifest subquery 与 full-scope 阶段门禁加入 Publication PostgreSQL workflow 和 release validator；提交
`f614619ef` 仅用唯一生成器重建 Celery/current-data/module/architecture/entrypoint 治理投影，没有修改扫描规则。

测试计数：容量/governance/manifest/lease 契约在排除规模节点时 `107 passed / 2 deselected`；独立 5,572 规模节点 `1 passed`，观测
总 SQL `50,183`、业务 ORM `27,891`、写入 `16,746`、checkpoint `5,045 bytes`、source freeze `2` 次，分别满足 `9N+64`、
`5N+64`、`3N+64`、16 KiB 和 2 次硬阈值。AKShare capture、egress、financial sync/source-time、release validator 组合
`186 passed`。`makemigrations --check --dry-run` 无变化；current-data `73` surfaces、Celery `95` tasks/`21` exemptions/
`24` governed files、module map `44/210`、entrypoint `1,303`、governance consistency `0 violation`。38 个生产 Python 文件增量
mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；54 个 Python 文件 Black、isort、Ruff 和 `git diff --check`
通过。

未验证风险与停止线：上述提交尚未 push，也未绑定最终 exact-SHA 五组 CI；新增 PostgreSQL 故障注入和 5,572 查询节点尚需由 Linux
CI artifact 证明零跳过/零失败。真实生产已有 legacy facts 不等于具备完整 typed source-time evidence；全量 manifest 可能在演练起点
因缺证而正确阻断。当前不存在可消费的 full-scope rehearsal ceiling、成功 receipt 或 production owner approval，禁止创建虚假记录，
也禁止把本地 5,572 数据库规模测试表述为真实 provider 容量通过。尚未执行 fresh S6、同镜像部署或 production financial refresh；
`bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，两个受保护周期入口保持 disabled，decision runtime 继续 fail closed。结论仍是
“部分通过/仍有阻断”，不能宣称四类正式发布全部恢复。

下一片是否可开始：可以提交本节台账、push 最终 exact SHA 并运行 Architecture、Security、Consistency、Fast Feedback、
Publication PostgreSQL 五组 CI。五组全绿且固定 PostgreSQL 节点零跳过/零失败后，才可从最新生产只读快照创建 fresh S6，禁止
`--resume`；S6 先验证 N=1、零出网失败反例与 release validator。完整 full-universe capacity rehearsal 必须另有真实 workload owner
提供精确 ceiling 和独立认证 approval；没有这些外部治理事实时应停在授权门前，不得执行 production financial refresh。

##### 2026-10-08 Financial capacity Architecture 门禁修复

完成项：首个候选 `ee3c5816ee62d356fa5a1fa6d1c993ab8f8fbc6d` 的 Architecture run `37780825408` 在两个 Python
版本均由 `apps_no_app_root_model_shim_imports_outside_admin` 正确阻断；两个新增 management command 经
`apps.data_center.models` 根 shim 读取 capacity governance model，产生 2 个 audit violation，boundary violation 为 0。旧 run 未重跑。
提交 `a725bc79c` 将两处导入改为本 App 的 `infrastructure.models`，没有放宽架构规则或增加例外。相同 base 的完整 architecture delta
复跑为 `0 boundary / 0 audit violation`，governance command 契约 `25 passed`；两个生产文件增量 mypy、全仓 debt ceiling、Black、
isort、Ruff、architecture/entrypoint/module/governance 检查和 `git diff --check` 通过，生成投影无差异。

未验证风险与停止线：`a725bc79c` 及本节台账形成的新 HEAD 尚未绑定新的五组 exact-SHA CI，旧候选其余 run 即使成功也不能拼接使用。
生产与授权停止线不变：没有 full-scope capacity rehearsal receipt 和独立 owner approval 时不得执行 production financial refresh。

下一片是否可开始：可以提交并 push 本节台账，以新 HEAD 重新运行全部五组 CI；只有同一 SHA 五组全绿并满足 PostgreSQL artifact 固定
节点要求后，才能进入 fresh S6。

##### 2026-10-08 Financial capacity PostgreSQL settings 门禁修复

完成项：候选 `b3be8977aceaaf6486d252fd15fb538398de994a` 的 Architecture `37781926128` 与 Security
`37781926135` 已通过，但 Publication PostgreSQL `37781926083` 在新增 capacity crash-recovery/CAS 节点正确失败；五个固定用例均在
真实 AKShare capture 的 owner-approved contract 读取前因专用 `tests.settings_data_center_sync_identity` 缺少 `BASE_DIR` 而停止，未进入
stage/activation/CAS 查询断言。提交 `8363baf9e` 在该隔离 settings 中将 `BASE_DIR` 显式绑定仓库根，保留真实 contract registry 校验，
没有 monkeypatch 或绕过生产契约。路径探针确认批准契约文件存在；Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：本地没有运行中的 Docker/PostgreSQL，因此五个节点只能得到环境门禁 skip，不能计作通过；必须由新 exact-SHA 的
Publication PostgreSQL Linux runner 证明五个节点零跳过/零失败。旧候选的其他 CI 结果不得拼接。生产 financial refresh 和既有停止线
没有变化。

下一片是否可开始：可以提交本节台账并 push 新 HEAD，重新运行同一 SHA 五组 CI；Publication PostgreSQL 必须实际进入五个新增节点，
随后继续完成其余固定节点和 artifact validator，才可进入 fresh S6。

##### 2026-10-08 Financial capacity PostgreSQL transport budget 门禁修复

完成项：候选 `455e72b46b4b2b87186a575a6aef77a4c07f9069` 的 Architecture `37782627726` 与 Security
`37782627697` 已通过；Publication PostgreSQL `37782627612` 已越过 contract registry 路径，但五个 capacity 节点在 test-only
capture runner 不接受新增 `attempt_budget` 参数时失败。提交 `bdefd1e04` 使 PostgreSQL seam 与生产 capture protocol 同签名，并在每次
模拟 transport send 前真实调用 `reserve()`；缺少 budget 或超限均失败，测试不再绕过物理请求计数。相关双 capture/单 route budget
契约 `3 passed`，Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：本地无 PostgreSQL，新增五节点仍必须在新 Linux CI 中实证；旧 run 未重跑，其余旧 SHA 结果不复用。所有生产刷新、
审批与周期入口停止线不变。

下一片是否可开始：可以提交台账并 push 新 HEAD，重新绑定五组 exact-SHA CI；只有 PostgreSQL 节点继续越过 test seam 并完成真实事务
断言，才可将本次修复计作通过。

##### 2026-10-08 Financial candidate 多指标 coverage 根因整改

完成项：候选 `4017b58ff40485298135fdc6719362847b998dca` 的 Architecture `37783337795`、Security
`37783337327`、Consistency `37783337130` 已通过；Publication PostgreSQL `37783337582` 已完成双 capture 和事实落库，随后暴露
生产 validator 把 financial candidate 的 `coverage.requested_count/eligible_count` 错当证券数。通用 candidate 对无 scope block 的财报
按 metric member 计 coverage，一个证券包含多个指标，因此任何真实候选都会被误判为
`financial_capacity_atomic_activation_incomplete`。提交 `a20809d62` 将 coverage 三项与精确 members 数量绑定，同时继续用 member natural
key 的资产前缀集合与完整 `asset_codes` 做精确证券范围校验；没有放宽 member/source/run/policy/hash 校验。5,572 manifest PostgreSQL 用例
同时补齐明确 `environment=production`，保持环境绑定 fail closed。生产文件增量 mypy、全仓 debt ceiling、Black、isort、Ruff、
current-data/architecture/entrypoint/module/governance 检查和 `git diff --check` 通过，治理投影无差异。

未验证风险与停止线：本地无 PostgreSQL，真实多指标 candidate staging、commit-unknown、audit rollback、并发 CAS 与 5,572 subquery 仍须
由新 CI 实证；旧 run 未重跑。生产 financial refresh、owner approval 与周期入口停止线不变。

下一片是否可开始：可以提交台账并 push 新 HEAD，重新绑定五组 CI；Publication PostgreSQL 的五个 capacity 节点必须零跳过、零失败，
并继续完成后续 control-plane、financial slice 和 evidence validator 节点后，才可进入 fresh S6。

##### 2026-10-08 DATA-02 audit seam 兼容性整改

完成项：候选 `6d0caa771180f415123bec56a6a9282957229376` 的 Architecture `37784250317`、Security
`37784250440`、Consistency `37784250341` 已通过；Publication PostgreSQL `37784250308` 的新增 capacity crash-recovery/CAS
阶段已整体通过，证明五个固定节点越过了 capture、candidate、activation 与 5,572 manifest 查询断言。后续既有 backfill control-plane
节点因 `tasks.audit_integration` 属性缺失而在 fixture setup 失败：authority 实现已移入共享 `data02_task_authority`，但历史组件和单元测试仍
通过 tasks 公开模块 seam patch 同一 audit module。提交 `1d85f0857` 恢复该公开模块别名；底层与共享 authority helper 引用同一个 Python
module object，因此 patch 仍作用于真实读取边界，没有增加第二套 authority 逻辑或关闭保护。core backfill 契约 `40 passed`；生产文件增量
mypy、全仓 debt ceiling、Black、isort、Ruff、architecture/entrypoint/module/current-data/Celery/governance 检查和
`git diff --check` 通过，生成投影无差异。

未验证风险与停止线：旧 PostgreSQL run 在 backfill 节点停止，后续 financial slice、maintenance、migration、SQLite 与 artifact validator
没有执行；必须以新 SHA 完整通过，不能只引用已通过的 capacity step。生产停止线不变。

下一片是否可开始：可以提交台账并 push 新 HEAD，重绑五组 CI；Publication PostgreSQL 需从头完成全部步骤且 artifact 零跳过/零失败，
才可进入 fresh S6。

##### 2026-10-08 Financial evidence Fast Feedback 契约替身整改

完成项：候选 `2b309a6fa6b3dbe280f7c554a148ffea7384feb4` 的 Architecture `37786031836`、Security
`37786031809`、Consistency `37786031865` 与 Publication PostgreSQL `37786031849` 已通过。Publication PostgreSQL 从头完成
financial capacity crash recovery/CAS、Account authority generation/final fence、真实 publication locks、control-plane、AKShare financial
slice、statement logging、migration、SQLite reconciliation 与 evidence validator，全部步骤 success。Fast Feedback `37786031847` 的 Python
3.11/3.13 各仅有相同 3 个旧测试替身失败：egress 测试仍要求 transport capture 对象原样返回，没有核对新增的规范化
`physical_request_attempts`；两个 source-time composition fake 没有接受并核对新增的 `expected_run_id`。提交 `8316420a0` 将测试改为核对
payload/evidence/raw body/精确物理请求次数，并要求两个 fake 接受且在普通读取场景收到空 run ID；生产实现、请求 ceiling 和 fail-closed
规则均未修改，旧 Fast Feedback run 未重跑。

测试计数：两份直接相关测试文件 `34 passed`；与 Fast Feedback 相同的 14 组本地目标 `3004 passed / 70 skipped`，包含 API、component、
critical、guardrail、migration、全部 data_center unit 与 Tushare client。两个测试文件 Black、isort、Ruff 和 `git diff --check` 通过。

未验证风险与停止线：`8316420a0` 及本节台账组成的新 HEAD 尚未绑定新一轮五组 exact-SHA CI；本地仅使用 Python 3.11，Python 3.13
由 Fast Feedback runner 复核。上一候选四组成功结果和 PostgreSQL artifact 不能与新 SHA 拼接为最终门禁。生产 financial refresh、
full-market 重跑、owner approval 和两个周期入口的停止线不变；不存在可消费的 full-scope rehearsal receipt 时必须继续 fail closed。

下一片是否可开始：可以提交并 push 本节台账，以新 exact SHA 重跑五组 CI。只有五组同 SHA 全绿且 Publication PostgreSQL artifact
固定节点零跳过、零失败、零 error，才可从最新生产只读快照创建 fresh S6；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-08 fresh S6 候选迁移与发布证据门禁

现状：fresh S6 的只读数据库 preflight 在 `REHEARSAL_WRITE_MIGRATIONS_PENDING` 阻断；输入快照已到 `data_center.0089`，候选含
`data_center.0090`–`0093`。该 preflight 先于 provider stage 且在只读事务中运行，因此本次阻断不能被当作迁移已完成或正式发布证据。

本切片将隔离候选迁移报告纳入 release manifest 和 validator，固定 schema 为
`release.isolated-database-migrations.v1`，evidence mode 为 `isolated_postgresql_migrations`。报告绑定 candidate SHA、candidate image、
disposable database name/host/port/container ID、固定 migrator 命令与 `agomtradepro_migrator` 角色，并列出排序后的
`database_address` 必须由 Docker network inspect 取得并通过严格 IP 解析；报告身份绑定 database name/host/address/port/container ID。迁移清单包括
`pending_before`、`applied_migrations`、`pending_after`。validator 只接受 `pending_after=[]` 且 `applied_migrations` 与
`pending_before` 完全相同；`[]/[]/[]` 是合法 noop。schema 不允许 URL、密码或额外 secret 字段。required report 和环境阶段顺序由
`governance/release_rehearsal_policy.json` 同时约束，迁移报告随其他报告进入 bundle 的 hash graph。

实施边界：迁移只能由候选 image 对精确 disposable PostgreSQL 使用 migrator URL 执行；迁后必须用 runtime URL 立即运行只读 preflight，
验证同一个 database/container/image 且没有 pending migrations 后才开始 provider stages。迁移命令启动后若 timeout、进程中断或提交状态未知，
必须阻断该 attempt，不能 `--resume` 重放；保留旧的 pending attempt，下一次使用新的 disposable DB 与 fresh attempt。此整改没有授权直接修改
production migrations，也没有执行 production migration 或旧 attempt resume。

完成项：提交 `d044defd8d2e66e53ec2c743e4ff911b7187daf9` 增加 `isolated_database_migrations` 阶段，并将其排在全部
provider stage 之前。runner 同时校验 runtime/migrator URL 的 host、database 与 port、Docker network 中精确 PostgreSQL container/IP、
candidate image/SHA、migrator session/current role，以及迁前/迁后 migration graph。迁移命令只接受
`python -m scripts.manage_vps_migrations migrate --noinput`；`pending_before`、实际 applied delta 与 `pending_after` 必须精确对账。迁移启动前
持久化 unknown-commit marker；只有 secret-free report 与 checkpoint 均 fsync 完成后才清除 marker，失败、超时或中断均保留阻断，同 attempt
不得重放。release manifest、validator、policy required reports、test selector、环境契约与恢复手册已同步。migrator 私有 `0400` env 只允许
隔离 DB identity、Django `SECRET_KEY` 与历史加密数据 migration 可能需要的 `AGOMTRADEPRO_ENCRYPTION_KEY`；provider/API、Sentry、SMTP、
broker 与 MCP 凭据不会进入 stage env，任何 secret 都不会进入 argv、报告、诊断或 release bundle。两个应用密钥属于高敏迁移授权，用于保证
从含历史密文的生产克隆演练时与真实数据一致，不能外推为 provider 授权。

测试计数：迁移 runner/manager、manifest/validator、环境矩阵、selector 与 PostgreSQL role contract 聚焦回归
`358 passed / 4 skipped`；4 个 skip 是本地 Windows 无 Docker/PostgreSQL 的既有环境门禁，不能计作 Linux 实证。生产文件增量 mypy
`0 regressions`，全仓 mypy debt ceiling `0 errors`；Black、isort、Ruff、module map（44 modules/210 edges）、current-data（73 surfaces）、
Celery contracts（95 tasks）、governance consistency（0 violations）、Data Center entrypoint 唯一生成投影（1,306 entries，
candidate-review=0）及 `git diff --check` 全部通过。

未验证风险与停止线：本地测试不能证明候选容器真实连到 disposable endpoint，也不能证明同一候选在 Linux 下完成 0090–0093 后继续通过十阶段、
release validator 与 receipt handoff；迁移 stage 复用的 Docker network 不是 internal network，虽然没有注入 provider env/路由，但尚无物理层零外网
证明。exact-SHA 五组 CI、Publication PostgreSQL artifact、fresh S6、同镜像部署和部署后只读 UAT 均未执行。旧 attempt、旧 receipt、旧 image
不可补记或复用；生产 full-market 禁止重跑，两个周期入口保持 disabled，production financial refresh 仍需 full-scope capacity receipt、独立
owner approval 与用户新的明确授权。

下一片是否可开始：可以提交本节台账并 push 新 HEAD，绑定同一 exact SHA 的 Architecture、Security、Consistency、Fast Feedback 与
Publication PostgreSQL。五组全绿且 PostgreSQL artifact 固定节点零跳过/零失败后，才可从最新生产只读快照创建 fresh S6，禁止
`--resume`；S6 必须实际应用隔离 migrations、完成十阶段与 release validator，之后只能部署 receipt 绑定的同 SHA 预构建镜像。

##### 2026-10-09 migration evidence collector fixture 收口

完成项：候选 `abc35c73fea4a27665ce91385f98dfadafc029ca` 的 Architecture `37811451997`、Security `37811452073`、
Consistency `37811452042` 与 Publication PostgreSQL `37811452076` 通过；Fast Feedback `37811452215` 在 Python 3.11/3.13 的同一
collector 组合测试失败。根因是 `test_collector_report_satisfies_bundle_identity_contract` 继续用带通用 `artifact` 字段的最小 report
代替所有 required reports，而新 migration report 的严格 schema 正确拒绝额外字段并要求完整 disposable database identity。提交
`b3df5a264c6aecd7063463520a55cc754ad3546a` 仅把该测试替身改为真实 `release.isolated-database-migrations.v1` 字段集，覆盖
candidate/image、database host/address/port/container、固定命令/role 与合法 noop `[]/[]/[]`；生产 builder/validator、请求门槛和
迁移行为均未修改。旧失败 run 未重跑，旧 SHA 的四组成功结果不得与新 SHA 拼接。

测试计数：collector + builder + validator 聚焦回归 `155 passed / 1 skipped`；与失败 Fast Feedback 相同的 21 个选择目标在本地
`595 passed / 8 skipped`，其中 skip 均为 Windows 缺少 Linux/Docker/PostgreSQL 的环境门禁。Black、isort、Ruff、Data Center
entrypoint 唯一生成投影（1,306 entries，candidate-review=0）、governance consistency（0 violations）与 `git diff --check` 通过。

未验证风险与停止线：Python 3.13 和 Linux 能力仍须由新 Fast Feedback 验证；新最终 SHA 尚未绑定五组 exact-SHA CI。旧
Publication PostgreSQL 虽通过，也不能作为新 SHA 证据。fresh S6、同镜像部署和部署后 UAT 均未开始，全部生产刷新与审批停止线不变。

下一片是否可开始：可以提交台账并 push，以新 HEAD 从头绑定五组 CI；只有同一 SHA 五组全绿并核验 Publication PostgreSQL artifact
固定节点零跳过/零失败后，才可准备新的 disposable database 和 fresh S6 attempt。

##### 2026-10-09 S6 隔离迁移数据库地址类型契约整改

完成项：候选 `271151cd02408cd3855c5d7fbce7ae1f37efe53c` 的五组 exact-SHA CI 与 Publication PostgreSQL 固定
节点已全部通过；fresh S6 attempt `d34c9831322f4b23ba72506d1f0d9ca6` 完成候选镜像构建、镜像 revision、环境 preflight 后，
在 `isolated_database_migrations` 阶段于任何候选 migration 执行前 fail closed。安全诊断和隔离 PostgreSQL 只读查询确认 Docker
identity 为 `172.19.0.2`，而 `SELECT inet_server_addr()::text` 返回 PostgreSQL `inet` 的 CIDR 文本 `172.19.0.2/32`；
严格 `ipaddress.ip_address()` 因而正确拒绝，但查询端违反了既定的纯 host address 类型契约。数据库中 `data_center.0090`–`0093`
迁移记录为 0，失败 attempt 的 unknown-commit marker、runner 状态和证据均保留，禁止 resume 或复用其镜像/receipt。

提交 `2aa13fdc1` 将 migration helper 改为 PostgreSQL 原生 `host(inet_server_addr())`，仍由 Python 严格解析单 IP 并逐项比对 Docker
地址和端口；没有在 Python 中裁剪前缀，也没有放宽 database name/host/container/role/command/opt-in 校验。单元反例覆盖 CIDR、地址
不一致、端口不一致，以及 scope 失败时不得读取 migration state、不得调用 migrate、不得生成结果文件。现有 Publication PostgreSQL
必需节点 `test_connected_database_identity_returns_real_postgres_address_without_cidr` 同时调用真实 migration helper，避免只由 fake cursor
证明 PostgreSQL 类型语义，也没有新增第二套 REQUIRED test identity 或改变固定 JUnit 节点数。

测试计数：migration/role/runner/validator/collector 聚焦回归 `278 passed / 3 skipped`；3 个 skip 为本地 Windows 缺少 Linux
Docker/PostgreSQL 的既有环境门禁。真实 PostgreSQL 节点本地按约定 `1 skipped`，必须由新 Publication PostgreSQL CI 实证。
生产文件增量 mypy `0 regressions`，全仓 debt ceiling `0 errors`；Black、isort、Ruff、module map `44/210`、current-data
`73 surfaces`、Celery contracts `95 tasks / 21 exemptions / 24 governed files`、Data Center entrypoint 唯一投影 `1,306 entries`
和 `git diff --check` 全部通过，治理投影无差异。

未验证风险与停止线：修复后的真实 PostgreSQL migration helper、0090–0093 隔离迁移、后续十阶段与 release validator 尚未由新
exact-SHA CI/fresh S6 证明。失败 attempt 必须保留诊断并删除其 disposable runtime 后再创建全新 attempt；不得 `--resume`、复用旧
receipt/image 或重跑旧 CI。生产 full-market 任务禁止重跑，两个周期入口保持 disabled；production financial refresh 仍需 full-scope
capacity receipt、独立 owner approval 和用户新的明确授权，不得由本次迁移修复越过。

下一片是否可开始：可以提交本节台账、push 最终 SHA，并从头运行 Architecture、Security、Consistency、Fast Feedback 与
Publication PostgreSQL。五组同 SHA 全绿且固定 PostgreSQL 节点零跳过/零失败后，才可从最新生产只读快照创建新的 disposable
PostgreSQL/Redis 和 fresh S6 attempt；完整通过后只能部署 receipt 绑定的同 SHA 预构建镜像，再执行只读 UAT。

##### 2026-10-09 Financial capacity PostgreSQL 官方证据投影整改

完成项：候选 `36cfd0d722fb60d46913aba62da7bb0328d9aa7f` 的五组 exact-SHA CI 全绿，Publication PostgreSQL artifact
包含 migration helper 真实地址节点、Account outer-fence 和 5,001 member soak，均零跳过、零失败。fresh S6 attempt
`0bf34cbf3eb243d18d4dd86d0707ccf0` 随后实际完成 `data_center.0090`–`0093` 的隔离迁移并通过前八个阶段，证明数据库地址修复、
候选镜像和迁移图有效；但 `github_ci_evidence` 以 `REHEARSAL_REQUIRED_TEST_MISSING` fail closed。根因是 workflow 已单独执行五个
financial capacity PostgreSQL crash-recovery/CAS/5,572 manifest 节点，却没有为该 pytest 调用生成 JUnit；主 publication XML 又明确
以 `-k "not financial_capacity"` 排除这些节点，因此官方 artifact 无法证明五个必需测试的身份和结果。失败 attempt、checkpoint、
runner 终态与安全诊断均保留，未使用 `--resume`，也未部署或产生生产写。

提交 `7256bf6ef` 为五个节点增加独立 `financial-capacity-postgres.xml`，workflow 在上传前校验精确五项身份集合并把它们纳入
skip/failure/error 扫描，artifact upload 与 release validator 的官方 JUnit 文件全集同步增加该文件。validator/collector 测试替身不再
使用位置切片，而是按测试语义建立互斥分区并验证并集覆盖全部 50 个 required identities；反例覆盖新 XML 缺失时
`REHEARSAL_GITHUB_ARTIFACT_INCOMPLETE`、必需节点缺失和 skipped/failure 的既有 fail-closed 路径。没有删减
`REQUIRED_POSTGRESQL_TESTS`、修改测试扫描规则或把五个节点并入会被其他 pytest 调用覆盖的旧 XML。

测试计数：validator 与官方 evidence collector 聚焦回归 `139 passed`；生产 validator 增量 mypy `0 regressions`，全仓 debt ceiling
`0 errors`；Black、isort、Ruff、workflow YAML 解析、module map `44/210`、Data Center entrypoint 唯一生成投影 `1,306 entries` 和
`git diff --check` 全部通过，治理投影无差异。Luna Max 红队只读复核确认独立 JUnit、精确身份集合、官方文件全集和负向证据边界完整。

未验证风险与停止线：`7256bf6ef` 与本节台账组成的新 HEAD 尚未绑定新的五组 exact-SHA CI；新
`financial-capacity-postgres.xml` 必须由 Linux Publication PostgreSQL run 实际生成，并证明 `5 tests / 0 skipped / 0 failure /
0 error`。旧候选的五组成功和失败 S6 的前八阶段不能与新 SHA 拼接。当前 S6 attempt 不得 resume，旧 receipt/image 不得复用；
生产 full-market 任务禁止重跑，两个周期入口保持 disabled，production financial refresh 仍需 full-scope capacity receipt、独立
authenticated owner approval 和用户新的明确授权。

下一片是否可开始：可以提交并 push 本节台账，以新 exact SHA 从头运行五组 CI。五组全绿且官方 artifact 同时包含
`financial-capacity-postgres.xml` 的精确五节点、publication 42、financial slice 12、Account final revalidation 8 及 5,001 member soak
后，才可清理失败 attempt 的 disposable runtime 并从最新生产只读快照创建 fresh S6；禁止 `--resume`。

##### 2026-10-09 S6 Docker 29.3.0 BuildKit panic guard

完成项：fresh S6 attempt `46709ac27e654b1f8fd84feb10e1906c` 在 `build_only` 触发 Docker Engine 29.3.0 内置 BuildKit 的
`ListenBuildHistory` nil-pointer panic，导致 dockerd 被 systemd 重启并停止生产及隔离容器。该 attempt 已由操作员终止，生产旧版本已恢复；
原始事故证据保留在远端 `evidence/incident-dockerd-panic`，本切片未修改证据、未 resume、未部署或运行 S6。堆栈与
[Moby issue #52257](https://github.com/moby/moby/issues/52257) 一致；[PR #52230](https://github.com/moby/moby/pull/52230)
升级 bundled BuildKit，修复版本下限为 Engine 29.3.2。代码提交 `14ef9a4e0197236d67800df91caaed286eb208f4` 将构建模式和
Docker endpoint/version 纳入治理 policy；在任何构建前核验默认 context、Unix socket 和 client/server 版本，拒绝 Engine 29.3.0/29.3.1；
用 `DOCKER_BUILDKIT=0 docker --context default build` 显式走 legacy builder，并核对输出标记，不再发送 inline-cache 参数或尝试默认
BuildKit 回退。远端 build 和含预构建镜像的 deploy 都有相应的 Engine preflight，错误使用稳定码且诊断不暴露 endpoint/version。

测试计数：4 个聚焦单元模块 `380 passed / 4 skipped`，包括 fake-Docker 故障注入及生成 shell 语法检查；变更生产文件增量 mypy
`0 regressions`。Black、isort、Ruff、py_compile、governance consistency（0 violations）和 `git diff --check` 通过。全仓 mypy debt ceiling
未通过：并行 financial scope 切片在 4 个未提交 Data Center 文件引入 13 条新增诊断；该切片未被本提交暂存或修改，错误清单已交回主任务处理。

未验证风险与停止线：目标生产 VPS 升级后 Engine `>=29.3.2` 的只读核验、该 SHA 的 CI、Docker 29.3.2 实际 legacy build 及完整 fresh S6 均未执行；
因此本地故障注入不能证明生产环境已经安全。旧 attempt 不得恢复或补记，生产部署需待主任务执行主机升级与只读核验后单独推进。Docker CLI policy
当前限定在 `29.3.2 <= client < 30.0.0`；升级 CLI 前须验证并治理替代 builder 路径。

下一片是否可开始：否。先修复并通过全仓 mypy debt ceiling，再由主任务完成目标 VPS Engine `>=29.3.2` 只读核验和新 exact-SHA CI；条件满足后只可从
最新生产只读快照启动全新的 S6 attempt，禁止 resume 事故 attempt。部署仍须等 fresh S6 完整通过及相应授权。

##### 2026-10-09 Financial capacity 已验证导入的一次性消费门禁

完成项：提交 `e3d746e48` 将 production formal financial workflow 收紧为只接受已持久化的 verified capacity import ID；调用方不能提供或覆盖
import record hash。新增 append-only consumption ledger 和 `data_center.0097`，以 import 唯一约束阻止不同 workflow 重放；checkpoint repository
在同一 `transaction.atomic()` 内锁定并重读 import authority，写入 consumption、formal workflow 与 manifest，任一写入失败整体回滚。start、
in-flight claim、resume、slice 和 activation 均重新校验 consumed import 与当前 owner/reviewer/ceiling、candidate、provider、universe 和 source revision
绑定；同 workflow 的 commit-unknown 通过精确 read-back 对账，不重复消费或发起 provider 请求。production composition 与 Celery task 只传持久化
import ID，裸 receipt 稳定返回 `financial_capacity_scope_import_required`。

Luna Max 红队发现反向可空 revocation 关系上的 `LEFT OUTER JOIN + FOR UPDATE` 会被 PostgreSQL 拒绝。提交 `0b0226c82` 将 importer 与 formal
authority 两处锁限定为 `select_for_update(of=("self",))`，只锁 governance 主表；新增真实 PostgreSQL 节点覆盖 nullable join、真实 import/pointer/
review/ceiling authority、审批撤销、ceiling 漂移、import digest 篡改、candidate/provider/universe 漂移，以及事务已提交后客户端收到
`DatabaseError` 的同 workflow read-back。Publication PostgreSQL 的 `financial-capacity-postgres.xml` 精确集合由 5 扩为 13 个节点，workflow
校验 exact identities 与 `0 skipped / 0 failure / 0 error`，`validate_release_rehearsal.py::REQUIRED_POSTGRESQL_TESTS` 同步登记。提交
`cc1703a96` 仅由唯一生成器更新 module map、Data Center architecture inventory 与 entrypoint inventory；检查结果为 module map
`44 modules / 210 edges`、entrypoint `1,310 records`（833 active_public、337 adjacent_operational、138 compatibility、2 candidate-review），
architecture inventory 统计一致。

提交 `ae00c0306` 另行收口 Celery 合约的 5 个历史 selector：legacy `sync_financial_data_task` 已永久改为 capacity fail-closed，
治理清单却仍引用旧 all-success、partial、complete-failure 与 zero-output 行为测试。整改没有修改 checker 或恢复旧行为，只保留该兼容入口仍可发生的
`invalid_input` 与 `blocked` 契约；blocked 反例同时覆盖默认全集和显式证券范围，成功与部分失败行为继续归受控新任务。`check_celery_task_contracts.py`
通过，guardrail/checker `13 passed`、估值任务 `11 passed`、注册契约套件 `279 passed`，Black、isort、Ruff 与 diff 检查通过。

测试计数：financial capacity workflow `64 passed`，production pointer/replay 精确节点 `1 passed`，capacity import `17 passed / 1 skipped`，release
validator `140 passed`，新增 PostgreSQL 节点本机因未配置专用 loopback PostgreSQL 明确 `4 skipped`，全文件 `44 collected`；这 4 项不能计作通过。
17 个生产 Python 文件增量 mypy 为 `0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、migration dry-run、三份生成
投影 check 与 `git diff --check` 通过。Luna Max 对 `0b0226c82` 最终只读红队复核未发现 P0/P1。

未验证风险与停止线：最终候选尚未 push，13 个 financial-capacity PostgreSQL 节点必须由同一 exact SHA 的 Linux Publication PostgreSQL
artifact 证明零跳过/零失败；authority PG 节点使用稳定替身提供 provider binding snapshot 与 typed-source manifest freeze，这部分仍需既有独立
PostgreSQL 测试和 fresh S6 的真实 provider/full-scope 阶段共同证明。尚未执行 fresh S6、同镜像部署或 production financial refresh。聊天授权不能
替代系统内 data_owner 与 independent_reviewer 的两个独立认证事件，也不能替代未撤销、未过期的 production ceiling；缺少任一事实时 formal refresh
必须 fail closed。生产全市场任务 `bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，两个受保护周期入口保持 disabled。

下一片是否可开始：可以提交本节台账并形成最终候选 SHA。只有同一
SHA 的 Architecture、Security、Consistency、Fast Feedback 与 Publication PostgreSQL 五组全部通过，并确认 13 个 financial-capacity 节点、
financial slice、Account outer-fence 与 5,001 member soak 零跳过/零失败后，才可从最新生产只读快照创建 fresh S6；禁止 `--resume` 或复用旧
receipt/image。fresh S6 全部通过并同镜像部署后仍须停在 production financial refresh 的系统 owner approval/ceiling 门前。

##### 2026-10-09 最终治理与 Qlib 停牌范围门禁收口

完成项：最终治理复核发现 current-data contract 仍引用 financial capacity checkpoint v5、legacy financial sync 的旧决策证据 marker 与已删除的成功
测试 selector。提交 `700b2a487` 只更新 `governance/current_data_contracts.json`：checkpoint marker 提升为 v6，legacy sync 改为
`FINANCIAL_CAPACITY_RECEIPT_REQUIRED` 与全 scope fail-closed 契约，required selector 指向现有容量阻断测试；scanner、freshness 和 production 行为未改。
批量回归同时暴露 pytest 插件导入顺序：owner evidence 模块先作为 helper 被导入、后声明 `pytest_plugins`，导致首批收集缺少现有
`owner_physical_alias` fixture。提交 `40db1f37d` 在 research `conftest.py` 提前注册同一个 Account PostgreSQL contract plugin，并删除迟到的模块声明；
没有复制 fixture 或新增 skip。

Qlib 回归进一步发现生产正确性问题：部分证券有停牌证据、其余证券仅未知缺行时，旧逻辑会错误返回 `MODEL_MARKET_SUSPENDED`；存在部分行情时也可能
静默遗漏未知成员。提交 `1f99739ee` 在任何日历或特征写入前要求冻结请求范围精确满足
`requested = observed_with_rows ∪ verified_suspended`。未知缺失稳定返回 `MODEL_MARKET_SCOPE_INCOMPLETE`，details 只列资产代码；只有全部请求证券
都有精确停牌证据且无行情时才返回 `MODEL_MARKET_SUSPENDED`。没有降低停牌证据、freshness、coverage 或来源阈值。

测试计数：current-data checker `73 surfaces`，Qlib builder `29 passed`，owner v2/evidence `20 passed / 8 skipped`；完整 current-data registered runner
四批共 `1,048 passed / 43 skipped / 0 failed`，skip 为当前 Windows/Linux/PostgreSQL 能力门禁，未计作通过。Qlib 生产文件增量 mypy 为
`0 regression`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff 和 `git diff --check` 通过。

未验证风险与停止线：owner evidence 与 financial capacity 的专用 PostgreSQL 节点仍须由 Linux Publication PostgreSQL CI 证明实际执行且零 skip；
本地 Windows 的通过不能替代真实 PostgreSQL 锁、事务和权限链路。尚未执行 final exact-SHA 五组 CI、fresh S6、同镜像部署或 production financial
refresh。生产全市场任务、owner approval、capacity ceiling 与两个周期入口停止线保持不变。

下一片是否可开始：可以提交本节台账、push 最终 SHA 并启动五组 exact-SHA CI。五组同 SHA 全绿且官方 PostgreSQL artifact 固定节点全部零跳过/
零失败后，才可进入 fresh S6；后续生产 financial refresh 仍必须等待完整 receipt import、两个独立认证 owner/reviewer 事件和有效 ceiling。

##### 2026-10-09 Financial 最终候选 CI 失败根因整改与入口投影收口

完成项：候选 `bd395da7565985a180c844a662c435d9355ddacd` 的 Architecture `37885865994` 与 Security
`37885865977` 通过，但该 SHA 不是最终候选，结果不得复用。Consistency `37885865918` 因两份 release rehearsal 脚本缺少
operational lifecycle 登记而失败；Fast Feedback `37885865976` 因 `apps/data_center/application/tasks.py` 与
`apps/data_center/composition.py` 超出 changed-file 1,000 行增量门禁而失败；Publication PostgreSQL `37885865951` 因七个新 capacity
fixture 未满足真实模型字段与隔离 build identity 契约而失败。旧 run 均未重跑。

提交 `a7b21c5ee` 仅修复 PostgreSQL fixture：使用完整 `FinancialFactModel` 字段，并生成 schema-valid、与候选绑定的隔离 build identity；
13 个 official financial capacity test identities 未删减。提交 `c4896eda9` 将 financial capacity task gate 组装拆到独立模块，由 runtime
持有具体 port/workflow assembly，`tasks.py` 收敛到 985 行，`composition.py` 收敛到 1,109 行且低于其比较基线；没有提高文件门槛。
提交 `071f56863` 使用唯一 entrypoint generator 与 operational manifest 精确登记
`scripts/build_release_rehearsal_manifest.py` 和 `scripts/validate_release_rehearsal.py`。生成投影从 1,310 增至 1,312 条，新增的两条
`active_public operational_script` 与原有两条 `candidate-review script` 并存，保留 import review；legacy checker、扫描规则与 compatibility
清单未修改，也没有通配放行。

测试计数：financial capacity workflow `64 passed`，task/composition 聚焦回归 `3 passed`；PostgreSQL 七个目标在本机成功收集，但因未配置专用
loopback PostgreSQL 明确 skipped，不能计作通过。entrypoint/legacy suite `32 passed`，新增语义正反例 `3 passed`；entrypoint stale-check
为 1,312 entries、34 operational scripts、2 candidate-review，legacy checker 为 0 direct/0 wrappers。changed-file headroom、生产文件增量
mypy、全仓 debt ceiling、Black、isort、Ruff、module map `44 modules / 210 edges`、Architecture inventory、current-data `73 surfaces`、
Celery contracts `95 tasks`、governance consistency `0 violations` 与 `git diff --check` 均通过。

未验证风险与停止线：上述三个整改提交组成的新 HEAD 尚未由同一 exact SHA 的五组 CI 验证；本地 Windows 无法证明真实 PostgreSQL 锁、
事务、nullable relation 与 build identity 行为。两份 release script 的 import surface 仍保留 candidate-review，后续 architecture review 可独立处理，
本次不能用 lifecycle 登记伪装为 import review 完成。尚未执行 fresh S6、同镜像部署、production financial refresh 或普通用户 UAT；生产
full-market 任务禁止重跑，两个周期入口保持 disabled，系统内 data_owner/independent_reviewer/ceiling 停止线不变。

下一片是否可开始：可以以本节台账提交形成新最终候选并 push，从头绑定 Architecture、Security、Consistency、Fast Feedback 与
Publication PostgreSQL。只有五组同 SHA 全绿且 official artifact 证明 13 个 financial capacity 节点、financial slice、Account outer-fence
与 5,001 member soak 零跳过、零失败、零 error，才可从最新生产只读快照创建 fresh S6；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-09 最终候选 Linux descriptor 与 commit-unknown 故障注入整改

完成项：候选 `c8fd5a92170e5bdd85d959a3591c91a95b5cc765` 的 Architecture `37889036254`、Security
`37889036284`、Consistency `37889036282` 通过；Fast Feedback `37889036293` 与 Publication PostgreSQL `37889036296` 失败，因此
该 SHA 不可进入 S6，三组成功也不得与后续 SHA 拼接。Fast Feedback 的 Python 3.11/3.13 均只在
`test_rejects_fifo_swapped_between_stat_and_open` 失败：测试替换 `os.open` 后，运行时再次用被替换函数查询 `os.supports_dir_fd`，错误选择
path fallback，实际没有执行 stat/open 间 FIFO 替换。提交 `c3ff57631` 在模块导入时冻结原生 descriptor 能力；真实 open 调用仍动态解析，
Linux 故障注入可拦截，descriptor identity、`O_NOFOLLOW`、`O_NONBLOCK`、regular-file 与前后 inode/mode/size/mtime 校验均未放宽。

Publication PostgreSQL 的失败步骤为 `49 passed / 1 failed / 6 deselected`，唯一失败是 formal scope import 的 commit-unknown read-back。
根因不是生产 outer UOW：测试 monkeypatch 了共享 `transaction.atomic`，而 `bulk_create()` 内部也会进入一个 atomic/savepoint；旧替身在第一个
内层 atomic 退出时即抛出“确认丢失”，外层 formal-start UOW 因而正确回滚，read-back 也正确返回空。提交 `46129a2f6` 将注入条件绑定为
`not connection.in_atomic_block` 且 autocommit 已恢复，只在最外层提交已经完成后模拟确认丢失；生产 repository、事务和 read-back equality 均未修改。

测试计数：financial workflow unit suite `65 passed`；file reader 本地 `2 passed / 3 skipped`，三个 skip 是 Windows 无 FIFO/symlink 能力，不能计作
Linux 实证。PostgreSQL 精确节点本机成功收集但因专用 loopback PostgreSQL 未启用而 skipped，不能计作通过。两个切片的 Black、isort、Ruff、
`git diff --check` 通过；file reader 生产文件增量 mypy 与全仓 debt ceiling 为 0 errors。

未验证风险与停止线：新的 Linux descriptor 路径及正确的最外层 commit-unknown 注入仍须由新 exact-SHA Fast Feedback 和 Publication PostgreSQL
实证。失败 PostgreSQL run 的后续 financial capacity CAS、financial slice、statement logging、migration、SQLite reconciliation 与 artifact
validator 因前序失败未完成，不能引用其部分结果。fresh S6、同镜像部署、production financial refresh 与普通用户 UAT 尚未执行；其余生产停止线不变。

下一片是否可开始：可以提交本节台账并 push 新最终 SHA，从头运行五组 CI。只有同一 SHA 五组全绿、Fast Feedback 两个 Python 版本的 FIFO
race 反例通过，且 Publication PostgreSQL official artifact 固定节点全部零 skip/failure/error，才可进入 fresh S6。

##### 2026-10-09 Financial capacity 双审批测试时钟稳定化

完成项：候选 `364b1f44c128df52e293080e5cf51b6ac2e5ae6d` 的 Architecture `37891194121`、Security
`37891194042`、Consistency `37891194030` 与 Fast Feedback `37891194133` 通过；Fast Feedback 在 Python 3.11/3.13 的
FIFO stat/open 竞态反例、targeted pytest、RTM 与静态检查均通过，证明 descriptor 修复有效。Publication PostgreSQL
`37891194024` 在 financial-capacity 阶段为 `12 passed / 1 failed`，唯一失败是 5,572 资产 manifest 的双审批被稳定码
`FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED` 拒绝。根因是测试先捕获校验时点 `now`，helper 随后分别调用更晚的
`timezone.now()` 写入两条 `approved_at`，生产 domain 校验正确拒绝 `approved_at > now`；该失败不属于容量、审批或生产事务规则缺陷。

提交 `3acaf8093` 只让 PostgreSQL 测试 helper 接收调用方捕获的同一个 aware `now`，并将两条独立 owner/reviewer 记录的
`approved_at` 绑定到该时点、`expires_at` 绑定到 `now + 1 day`。生产审批校验、双人角色、有效期、5,572 scope、capacity ceiling、
CAS 与事务实现均未修改或放宽。旧失败 run 未重跑，其四组成功结果不得与新 SHA 拼接。

测试计数：修复前 CI 的 financial-capacity 官方节点为 `12 passed / 1 failed`；修复后精确 5,572 PostgreSQL 节点在本地成功收集，
但因未启用专用 disposable loopback PostgreSQL 明确 `1 skipped`，不能计作通过。Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：修复后的 13 个 financial-capacity PostgreSQL 节点及后续 financial slice、Account outer-fence、5,001 member soak
仍须由新 exact-SHA official artifact 证明零 skip/failure/error。fresh S6、同镜像部署、production financial refresh 与普通用户 UAT 均未开始；
生产 full-market 任务禁止重跑，两个周期入口保持 disabled。聊天授权不能替代系统内 data_owner、independent_reviewer 与有效 production ceiling。

下一片是否可开始：可以提交本节台账、push 新最终 SHA，并从头绑定五组 CI。只有同一 SHA 五组全绿且 Publication PostgreSQL
artifact 的全部必需节点通过后，才可从最新生产只读快照创建 fresh S6；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-09 Financial authority PostgreSQL 统一测试时钟整改

完成项：候选 `0e591960606de381c32a7e91ea06107eb90feb23` 的 Architecture `37892171171`、Security
`37892171178`、Consistency `37892171151` 与 Fast Feedback `37892171177` 通过；Fast Feedback 的 Python 3.11/3.13
FIFO、targeted pytest、RTM 和静态检查均通过。Publication PostgreSQL `37892171210` 在 real publication locks/frozen facts
阶段为 `47 passed / 3 failed`，三个失败均在真实 formal scope import authority 测试，稳定返回
`financial_capacity_scope_import_review_or_pointer_drift`；后续 capacity 与完整 artifact 校验按 fail-closed 跳过。

根因是测试 authority seed 将 report/pointer/review 时钟设为 wall clock 加 60 秒，而 formal checkpoint helper 随后重新读取当前 wall clock。
两条真实 review 因 `approved_at > checkpoint.started_at/consume now` 被生产校验正确拒绝，candidate/provider/universe drift 测试也因此无法进入
预期的后续分支。提交 `65e9a2aad` 仅使这些 PostgreSQL fixture 显式共享同一个 UTC `now`：candidate generated_at 为 `now - 5 minutes`，
owner/reviewer approved_at、pointer now 与 checkpoint/consume now 均绑定该时点。所有其他 formal checkpoint 调用点也显式传入捕获时钟；生产
review/pointer/import 校验、错误码和阈值未改。

测试计数：失败 CI 的目标阶段为 `47 passed / 3 failed`；修复后三个精确节点本地收集为 `3 skipped`，原因是未启用专用 disposable
loopback PostgreSQL，不能计作通过。Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：统一时钟修复必须由新 exact-SHA Publication PostgreSQL 实证；旧 SHA 的四组成功不得拼接。官方 artifact 尚未证明
13 个 financial-capacity 节点、financial slice、Account outer-fence 与 5,001 member soak 全部零 skip/failure/error。VPS 上另有旧 SHA
`c35df0dd18b4577f80bfc62e7f8623d6f6a26b3a` attempt 的历史 `run-status=running`，新 S6 前必须确认无实际 runner/资源并按证据保留规则处理，
不得 resume 或误用其状态。生产 full-market、financial refresh、双 owner/reviewer、ceiling 与两个周期入口停止线不变。

下一片是否可开始：可以提交本节台账、push 新最终 SHA 并从头运行五组 CI。只有同一 SHA 五组全绿、完整 PostgreSQL artifact 验证通过，
且 VPS 无活动 rehearsal 资源后，才可由 planner 原子预留全新 S6 attempt；禁止复用历史 run、receipt 或 image。

##### 2026-10-09 Core backfill 发布证据测试契约同步

完成项：候选 `6128a82f18da2042376bb5aed2f741fd93d2ace8` 的 Architecture `37893185300`、Security
`37893185246`、Consistency `37893185269` 与 Fast Feedback `37893185179` 通过；Fast Feedback 的 Python 3.11/3.13
FIFO/special-file、targeted pytest、RTM 和静态检查均通过。Publication PostgreSQL `37893185280` 已越过前述双审批时钟、真实
publication locks、financial-capacity crash recovery/CAS，在 control plane/valuation lineage 阶段的 3 个节点中 `1 passed / 2 failed`。

第一项失败由 component 测试替身仍声明 quote/price/valuation/financial 四类通用 Publication 且缺少 `deferred_publications` 引起；当前生产
契约要求三类通用 Publication，并以 `financial_capacity_receipt_required`、`attempted=false` 的 deferred financial lane 明确阻断财报。
第二项失败是 partial provider-domain 测试仍期望兼容字段 `success=true`，而任务最低契约只允许 SUCCESS/NOOP 为 true，规范 `partial`
必须返回 false。提交 `90d0022a8` 仅同步测试替身和断言：generic published 从 4 改为 3，四个同步域实际 `stored=4` 保持不变；partial 的
`outcome=partial`、失败域与错误明细断言全部保留。生产任务、发布证据哈希、财报阻断和 Celery outcome 逻辑均未修改。

测试计数：该 component 文件非 PostgreSQL 用例 `2 passed / 2 deselected`；失败 CI JUnit 为 `1 passed / 2 failed / 0 skipped / 0 error`。
Black、isort、Ruff 与 `git diff --check` 通过；两个真实 PostgreSQL 节点仍须由新 CI 实证。

未验证风险与停止线：旧 SHA 的四组成功不得拼接。Publication PostgreSQL 后续 financial slice、statement logging、migration、SQLite
reconciliation 与完整 artifact validator 因前序失败未执行；13 个 financial-capacity、Account outer-fence 与 5,001 member soak 的完整官方证据
仍须新 run 一次性验证。fresh S6、部署、production financial refresh 与普通用户 UAT 未开始；全部生产停止线保持不变。

下一片是否可开始：可以提交本节台账、push 新最终 SHA 并重新绑定五组 CI。只有同一 SHA 五组全绿且完整 artifact 零
skip/failure/error，才可进入 fresh S6。

##### 2026-10-09 Publication PostgreSQL 官方证据身份门禁去计数化

完成项：候选 `695087ebb8ab4fb029ef563c029d0fde10d02279` 的 Architecture `37894259503`、Security
`37894259487`、Consistency `37894259373` 与 Fast Feedback `37894259477` 通过；Publication PostgreSQL `37894259379`
的全部功能阶段也通过，包括 13 个 financial-capacity、12 个 financial slice、8 个 Account final-revalidation/outer-fence、
5,001 member soak、控制面、角色迁移、statement logging 与 SQLite 快照。官方 artifact `11600261047`（API SHA-256
`1f2a952ac2e8b01c64c90f9a7daf57b8cc72bfdd0de2aba8269a41e1f7f2f324`）共 98 个 testcase，全部零 skip/failure/error；
SQLite source/serialized/fixture 均为 291 行且 mismatches 为空。run 仅在最终 evidence guard 失败，因为 workflow 将
`publication-postgres.xml` 总数硬编码为 42，而实际随测试新增已为 50。

提交 `fb62856f8` 将门禁从易漂移的 suite 总数改为业务不变量：八个官方 JUnit 文件必须逐个存在、非空并包含 testcase；聚合后任何
skip/failure/error 都拒绝；全部 `scripts.validate_release_rehearsal.REQUIRED_POSTGRESQL_TESTS` 身份必须出现。删除 42/2/9/1/8/3/13/12
等重复总数和 workflow 内第二份 financial-capacity 身份清单；critical identity 的单一真源及集合没有删减。新增测试解析 workflow 的嵌入
Python 与 artifact 清单，禁止恢复硬编码 case 总数，并证明新增额外 testcase 在所有 required identities 齐全时不会造成假失败。

测试计数：workflow contract `2 passed`，release validator `140 passed`，合计 `142 passed`；修改后的门禁已对上述真实官方 artifact
离线执行通过。PyYAML、Black、isort、Ruff 与 `git diff --check` 通过；本机没有 `actionlint`，因此 GitHub workflow 的平台级解析仍由新 CI
验证，未以未报错替代。

未验证风险与停止线：workflow 逻辑变化后的新 exact-SHA Publication PostgreSQL 必须自身成功并重新产生 official artifact；不能把旧 artifact
功能全绿与新 workflow 拼接。门禁只证明已知 `REQUIRED_POSTGRESQL_TESTS` 和八个官方 suite，不能证明未知环境类别已穷尽。fresh S6、同镜像部署、
production financial authority/refresh 与普通用户 UAT 均未开始，全部生产停止线保持不变。

下一片是否可开始：可以提交本节台账、push 新最终 SHA，并从头绑定五组 CI。只有同一 SHA 五组全绿并核验新 artifact 后，才可启动 fresh S6。

##### 2026-10-09 PostgreSQL 证据测试治理登记与唯一投影收口

完成项：候选 `cee373b2663453414666922c171984b407e35f4f` 的 Architecture `37896359441`、Security
`37896359427` 与 Publication PostgreSQL `37896359436` 通过；新的 required-identity evidence gate 自身通过，证明去计数化实现可在真实
artifact 上运行。Fast Feedback `37896359438` 的 Python 3.11/3.13 测试任务和 FIFO guard 均通过，但其 incremental quality gate 与
Consistency `37896359417` 同时因 Data Center entrypoint projection stale 失败。根因是新建的 workflow contract 测试属于 operational
test evidence，却未在同一提交登记治理 lifecycle 并重建唯一投影；生产、PostgreSQL 与 workflow 功能没有失败。

提交 `a8c765c19` 将 `tests/unit/ci/test_publication_postgres_workflow.py` 精确登记为 active public test evidence，测试读取共享 required
inventory 时改为 AST 读取 literal，避免直接导入 operational script；随后只用 `scripts/data_center_entrypoint_inventory.py --write` 重建
`governance/data_center_entrypoints.json`。投影现为 1,313 entries：active_public 836、adjacent_operational 337、candidate-review 2、
compatibility 138；没有修改 scanner、状态语义或容许 stale projection。

测试计数：entrypoint inventory 与 workflow contract 聚焦回归 `30 passed`；workflow contract 独立 `2 passed`。生成器连续写入/检查摘要一致，
Black、isort、Ruff 与 `git diff --check` 通过。仓库已有 pre-push inventory hook，但当前执行环境未安装/触发该 hook，故此次遗漏仍由远端 CI
发现；这项主机级安装风险保留在交接，不以修改扫描器消除。

未验证风险与停止线：治理登记后的新 exact SHA 尚未五组全绿；上一 SHA 的成功 Publication PostgreSQL 不得拼接使用。candidate-review
仍有既有 2 项，本切片未伪装为清零。fresh S6、部署、production financial refresh 与普通用户 UAT 未开始；生产停止线不变。

下一片是否可开始：可以提交台账并 push，以新 exact SHA 从头运行五组 CI。五组与 official artifact 全部通过后才可进入 fresh S6。

##### 2026-10-10 最终候选架构投影与失败 S6 资源收口

完成项：候选 `ef5a0e148ecce8d971d85a29510deb64fc2f0723` 的 Architecture `37946712919`、Security
`37946713189` 与 Publication PostgreSQL `37946713051` 通过；Consistency `37946713117` 和 Fast Feedback
`37946713014` 的代码测试通过，但都在 `Enforce deterministic Data Center architecture inventory` 阻断，因此该 SHA 不得与后续
结果拼接。根因是 `b94625377` 已移除 Account position repository 对 Signal infrastructure model 的跨 App ORM 导入，生成投影仍保留旧引用。
提交 `1efb65b370abba0b4f19492a731cb233dd817977` 只运行唯一生成器
`scripts/data_center_architecture_inventory.py --write` 并提交 `governance/data_center_architecture_inventory.json`：
`cross_app_orm_imports` 从 48 降至 47，其余计数不变；扫描器、边界规则与 allowlist 均未修改。

失败 S6 attempt `a99d27730f014e9a9c3a78ac3f7b9e0b` 的 `run-status=blocked`、
`REHEARSAL_STAGE_ENVIRONMENT_PREFLIGHT_FAILED`、runner exit 2 和完整 evidence 目录继续保留；确认 runner PID `49364` 与历史 PID
`49548` 均已退出且不存在 active build marker 后，在共享 artifact lock 下只删除该 attempt 的 disposable PostgreSQL、Redis、network、
volume、未被容器引用的候选镜像 `agomtradepro-web:20261009163425` 及其 image tar。`/var/lib/docker` 可用空间从 19 GiB 恢复到
25 GiB，超过既有 24 GiB prebuild 门槛；没有删除 attempt root、降低磁盘门槛或触碰生产容器/数据。

测试计数：架构投影生成器 check 通过，`tests/unit/test_data_center_architecture_inventory.py` 为 `7 passed`，
`git diff --check` 通过。失败 S6 清理前后均验证 evidence 目录与终态文件存在；清理后只移除精确命名的 disposable runtime 与构建产物。

未验证风险与停止线：包含本节台账的新 HEAD 尚未由同一 exact SHA 的五组 CI 验证；上一 SHA 的三组成功不得复用。新的 official
PostgreSQL artifact 仍须证明 13 个 financial-capacity、financial slice、Account outer-fence 与 5,001 member soak 节点零
skip/failure/error。生产 full-market task `bcb3e00f-538e-420d-b179-428c40082f43` 禁止重跑，两个周期入口保持 disabled；
production financial refresh 仍须系统内两个独立认证 owner/reviewer 事件和有效 full-scope ceiling，聊天授权不替代这些事实。

下一片是否可开始：可以提交本节台账并 push 新 exact SHA，从头绑定五组 CI。五组全绿且 official artifact 身份完整后，才可从最新生产
只读快照原子预留 fresh S6，重新导出全部输入并禁止 `--resume`；完整十阶段与 release validator 通过后只能部署 receipt 绑定的同 SHA
预构建镜像。

##### 2026-10-10 S6 pre-runner candidate source 权限与身份门禁

完成项：fresh S6 attempt `e6e6d5962d9443e19b90b4b7614c95ee` 在 runner 启动前失败；候选 exporter 读取
root-owned `0700` workspace 时触发 `PermissionError`，随后远端 wrapper 在 `set -u` 下将 `$mode_FAILED` 解释为不存在的
`mode_FAILED` 变量，遮蔽原始稳定码。该 attempt 未启动 runner、未创建隔离 PostgreSQL/Redis、未构建或部署，原目录和诊断继续保留，
禁止 `--resume`。提交 `eb3e95dcb` 将 attempt plan 升为 v2：fresh `--reserve` 必须提供 exact clean workspace 与 candidate GID，
planner 从 candidate commit 的 Git blobs 创建独立 source snapshot，拒绝 symlink/gitlink/特殊项、ignored/untracked 与脏工作区，
只对快照复用 descriptor-based `seal_container_input_tree` 密封 `0550/0440`，不递归修改原 clone。每次 exporter 前重新核对
candidate/tree/receipt/GID/mode、精确 candidate image、非 root UID:GID 和唯一 `/candidate-src:ro` mount；Docker 参数只允许出现在
image 之前，拒绝 `--mount` 和未登记 option。shell 兼容路径复用受测 helper 返回大写稳定码，不再自行拼接变量名。

测试计数：planner、candidate-source 与 test-selection 聚焦回归 `86 passed / 5 skipped`；5 个 skip 均为 Windows 无法提供的 POSIX
mode/symlink/fchown/bash 实证，未计作通过。修改的 3 个生产 Python 文件增量 mypy 为 0 regressions，全仓 mypy debt ceiling 为
`0 errors in 0 files`；Black、isort、Ruff、`git diff --check`、module map `44 modules / 210 edges` 均通过。Data Center inventory
stale-check 保持 `1,313 entries`，未修改 scanner、治理规则或生成投影；该 S6 工具不被伪装为 Data Center entrypoint。

未验证风险与停止线：本地 Windows 未证明 root-owned `0700` clone 到非 root container 的真实跨 UID/GID读取、descriptor group seal、
Linux symlink/special-file 故障注入或 bash helper；必须由新 exact-SHA Linux CI 与 fresh S6 实证。receipt 是 candidate/tree/permission
的防漂移绑定，不能对抗拥有 attempt root 写权限的 root 主机管理员；attempt root 的主机权限和不可变证据链仍是信任边界。新 HEAD 尚未
五组 CI 全绿，不能引用旧 SHA 的成功结果。生产 full-market task 禁止重跑，两个周期入口保持 disabled；production financial refresh
仍须系统内两个独立认证 owner/reviewer 事件和有效 full-scope ceiling，聊天授权不替代这些事实。

下一片是否可开始：可以提交本节台账并 push 新 exact SHA，从头绑定 Architecture、Security、Consistency、Fast Feedback 与
Publication PostgreSQL。只有同一 SHA 五组全绿、official artifact 所有必需节点零 skip/failure/error，才可用 planner v2 预留全新
attempt，并以 tracked exporter 跑完整 fresh S6；禁止复用旧 receipt/image 或 `--resume`。

##### 2026-10-10 发布证据采集器可移植性与 manifest 契约同步

完成项：候选 `62fad0029e515a44677d0139c256259008313244` 的 Architecture `38012120114`、Security
`38012120040`、Consistency `38012120029` 与 Publication PostgreSQL `38012182166` 通过，但 Fast Feedback
`38012120112` 在 Python 3.11/3.13 同时以相同两项失败，故该 SHA 不得进入 S6。根因一是 `build_manifest` 已要求
`release_tag/image_tag` 和冻结 universe/provider identity 图，跨模块 collector 契约测试仍构造旧形态 fixture；根因二是 validator
后来新增共享 stage-environment 依赖后，collector 仍在 argparse 之前导入完整 validator，使隔离目录中的 `--help` 因缺少
`shared` 包而失败。提交 `0fda9b76a` 补齐完整冻结身份 fixture，并将 validator 动态导入延迟到参数解析后的真实采集入口；
`--help` 保持无运行时副作用，真实采集和直接函数调用仍加载同一个严格 validator，加载或校验失败继续返回稳定 blocked 结果。
独立审计后，提交 `51e88d64f` 又在 `--help` 子进程启动前删除沙箱中的 sibling validator，直接证明帮助路径不加载该模块，
避免未来 validator 重新具备独立可移植性时出现假绿。

测试计数：collector 与 manifest 聚焦回归 `34 passed / 1 skipped`，其中 1 个 skip 是 Windows 无法执行的 POSIX 文件模式反例，
未计作通过；collector 独立回归 `16 passed`。完整 no-database Fast suite 为 `4,041 passed`，耗时 44.74 秒，低于 120 秒预算。
修改的生产 Python 文件增量 mypy 为 0 regressions，全仓 mypy debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff 与
`git diff --check` 通过。

未验证风险与停止线：延迟导入与 fixture 同步必须由包含本节台账的新 exact SHA Linux Fast Feedback 实证；上一 SHA 的四组成功和
Publication PostgreSQL artifact 不得拼接。新的 Publication PostgreSQL 仍须重新证明 required financial-capacity、financial slice、
Account outer-fence 与 5,001 member soak 身份全部零 skip/failure/error。fresh S6、同镜像部署、只读联合 UAT 与普通用户流程尚未开始；
生产 full-market 禁止重跑、两个周期入口保持 disabled，financial refresh 仍须系统内双审批和有效 full-scope ceiling。

下一片是否可开始：可以提交本节台账并 push 新最终 SHA，从头绑定五组 CI。只有同一 SHA 五组全绿并核验官方 PostgreSQL artifact
后，才可由 planner v2 从最新生产只读快照创建 fresh S6；禁止复用旧 run、receipt、image 或 `--resume`。

##### 2026-10-10 Fresh S6 tracked prepare 与候选导出隔离收口

完成项：前一候选 `95ff7d454e415576f3549e8d1a1e6a7a6569ed52` 的五组 exact-SHA CI 与 official PostgreSQL artifact
均通过，但在进入 fresh S6 前发现仓库只有 candidate source snapshot helper，没有完整、受版本控制的 prepare wrapper/exporter；使用远端临时脚本会继续
复制历史 attempt 的 CR 字节、权限、生产网络和环境变量假设，因此该 SHA 不再作为 S6 候选。提交 `79d4434a3` 新增 planner v2-bound
`prepare_release_rehearsal_attempt.sh` 与三模式 `export_s6_rehearsal_inputs.py`：先恢复最新生产只读快照到隔离 PostgreSQL，再创建无 membership、
无写权限、`default_transaction_read_only=on` 的专用 exporter role；候选 exporter 只加入仅连接该隔离 PostgreSQL 的 internal prepare network，
不接生产网络或 Redis。执行镜像固定为当前生产 Web 的 immutable image ID，只提供依赖运行时；候选身份继续由 exact SHA、密封 source tree 与 receipt
绑定，候选镜像仍由后续 S6 build 独立生成和验证。

生产 Web 环境不再整体复制给候选代码：后续真实 provider 阶段的 `provider.env` 只保留 Tushare、部署区域和显式 proxy 白名单；三次 exporter
单独使用新生成 Django/encryption key 与隔离只读 PG 凭据的 `prepare-export.env`。候选导出 helper 进一步拒绝可变 image tag、额外挂载、重复/不安全
tmpfs、错误 network、image 后 option 和相互重叠的 host paths。原内嵌 final validation 的 `follow_sylinks` 拼写错误已修复，并新增实际执行该
Python 段的 POSIX 反例。只读 exporter role SQL 拆为独立文件，使新 wrapper 保持 `951` 非空行，没有扩大 1,000 行门槛。Data Center
operational lifecycle、唯一 entrypoint 投影和 CI test selection 已同步；投影为 `1,322` entries，其中 `845 active_public / 337
adjacent_operational / 2 candidate-review / 138 compatibility`，scanner 与治理状态语义未修改。

测试计数：planner/source/exporter/wrapper/test-selection/entrypoint 聚焦回归 `139 passed / 7 skipped`；skip 为 Windows 缺少 POSIX mode、
symlink/fchown/bash 等环境能力，未计作通过。Luna Max 在 WSL POSIX 临时树实际执行 final-validation Python 成功，但 WSL 未安装 pytest，未补装依赖。
修改的 4 个生产 Python 文件增量 mypy 为 `0 regressions`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、py_compile、
`bash -n`、Data Center 唯一投影连续 write/check、governance consistency（0 violations）和 `git diff --check` 通过。

未验证风险与停止线：新 prepare 仍未在 Linux Docker/VPS 上实证真实 UID/GID、internal network membership、PostgreSQL role privilege、快照恢复和
失败资源保留，必须由新 exact-SHA CI 与 fresh S6 证明。候选 snapshot 同时携带 verifier 与 exporter；当前信任模型依赖候选已通过 exact-SHA
评审和 CI，不能据此安全执行任意未评审代码，未来如扩大信任范围须使用 candidate 外的 operator-owned verifier。六类已知环境契约不证明未知类别
已穷尽。失败 attempt `e6e6d5962d9443e19b90b4b7614c95ee` 保留原始证据且禁止 resume。生产 full-market 任务禁止重跑，两个周期入口保持
disabled；production financial refresh 仍须 verified full-scope capacity import、系统内两个独立认证 owner/reviewer 事件、有效 ceiling 与新的
显式授权，聊天授权不替代这些事实。

下一片是否可开始：可以提交本节台账并 push，以新 HEAD 从头绑定 Architecture、Security、Consistency、Fast Feedback 与 Publication
PostgreSQL 五组 CI。只有同一 SHA 五组全绿且 official artifact 全部 required identities 零 skip/failure/error 后，才可由 planner v2
原子 reserve 全新 attempt 并运行 tracked prepare；fresh S6 禁止 `--resume`，完整十阶段与 release validator 通过后只能部署 receipt 绑定的
同 SHA 预构建镜像。

##### 2026-10-10 Fresh S6 prepare Security 扫描误报整改

完成项：候选 `edf1b2bee7dbb9be8e29d83f1deb225c4541e177` 的 Architecture `38019286277` 通过，Security
`38019286323` 在 gitleaks 唯一失败；Bandit、依赖和 npm 扫描均通过。定位结果是 final-validation 嵌入 Python 的环境解析断言把局部变量名
`key` 与稳定错误码字符串写在同一行，命中 `generic-api-key` 启发式；扫描报告已 redact，没有真实凭据进入 Git。提交 `6224d06d3`
将变量改为 `variable_name`，并把失败分支改为显式稳定错误码，输入校验、错误码、密钥隔离和运行行为不变；没有添加 gitleaks ignore 或放宽规则。

测试计数：wrapper 聚焦回归 `6 passed / 1 skipped`，skip 为 Windows 缺少 POSIX mode；`bash -n` 与 `git diff --check` 通过。

未验证风险与停止线：该修复和本节台账组成的新 HEAD 尚未绑定五组 exact-SHA CI；旧 SHA 的 Architecture 成功不得拼接，仍运行的
Consistency、Fast Feedback 与 Publication PostgreSQL 也只能作为失败诊断，不能作为下一候选证据。fresh S6、部署及生产刷新停止线均不变。

下一片是否可开始：可以提交台账并 push，新 SHA 必须从头运行五组 CI；同 SHA 五组全绿前不得 reserve fresh S6。

##### 2026-10-10 S6 密封候选 verifier 禁止 bytecode 写入整改

完成项：候选 `c16aa4f7fa8cbf4b908157899ccaa0309612fe21` 的 Architecture `38019559510`、Security
`38019559509`、Consistency `38019559492`、Fast Feedback `38019559495` 与 Publication PostgreSQL
`38019585404` 全部通过；官方 artifact `11657079797` 的 API SHA-256 为
`32889b92bb346126dd88b1bc05d401b2ab46c9c8f14533d6b1e9cb958a118c34`。八个 JUnit 文件共 98 个 testcase，
全部 58 个 `REQUIRED_POSTGRESQL_TESTS` 身份出现，0 skipped / 0 failure / 0 error；其中 financial-capacity 13 项、
financial-slice 12 项、Account final-revalidation 8 项及 5,001 member soak 均由该 exact SHA 实证。

fresh attempt `6ef2bf3cc10d4e38ae05ba41d06126ce` 因操作者未在 reserve 后写入受控 `inputs-private`，在 preflight 以
`S6_FRESH_BOOTSTRAP_INPUTS_INVALID` fail closed；attempt `12ff55b972af41f9aa64a7a7f84ee919` 补齐临时输入后又以
`S6_CANDIDATE_SOURCE_VERIFY_FAILED` fail closed。两次均未创建隔离数据库/Redis、未调用 provider、未构建或部署，目录与安全诊断保留且禁止
resume。第二次的直接证据是密封树中新增了 `scripts/__pycache__/rehearsal_checkpoint.cpython-312.pyc`：root 运行普通 `python3`
导入 candidate verifier 时仍可在 `0550/0440` 树中生成 bytecode，随后 descriptor 复核正确拒绝该新增项。提交 `98a3f38c2` 只把该调用改为
`python3 -B`，保持 receipt、权限、哈希和稳定错误码不变，并补 wrapper 契约与 POSIX 零 bytecode 反例；没有手工删除失败 attempt 中的污染文件，
也没有放宽权限检查。

测试计数：prepare/source 聚焦回归 `28 passed / 6 skipped`，6 个 skip 均为 Windows 缺少 POSIX mode、symlink、fchown 或 bash 能力，
未计作通过；Black、isort、Ruff、`bash -n`、Data Center 唯一投影连续 write/check、governance consistency 0 violations、全仓 mypy
debt ceiling `0 errors in 0 files` 与 `git diff --check` 通过。wrapper 为 954 非空行，1,000 行门槛未放宽。

未验证风险与停止线：`98a3f38c2` 与本节台账组成的新 HEAD 尚未由五组 exact-SHA CI 验证，Linux 零 bytecode 回归须以新 Fast Feedback
实证；上一候选的五组成功和 artifact 不得拼接使用。新的 fresh S6、同镜像部署与只读联合 UAT 尚未开始。生产 full-market 任务禁止重跑，
两个周期入口保持 disabled；production financial refresh 仍须系统内双审批、有效 full-scope ceiling 与新的显式授权，聊天授权不替代这些事实。

下一片是否可开始：可以提交本节台账并 push，新 exact SHA 从头运行五组 CI。只有同一 SHA 五组全绿且官方 PostgreSQL artifact 身份完整，
才可重新 reserve fresh attempt；必须先注入受控临时输入，禁止 `--resume`、复用旧 receipt/image 或清理失败证据。

##### 2026-10-10 S6 exporter PUBLIC TEMPORARY 权限收口

完成项：候选 `cccdf08eb9d81fe5537e5597a5dc664f361ae57d` 的 Architecture `38021915074`、Security
`38021915067`、Consistency `38021915080`、Fast Feedback `38021915102` 与 Publication PostgreSQL
`38021929534` 全部通过；官方 artifact `11657914288` 的 API SHA-256 为
`a47b5868bc71802b082f15a1b8b81b3756547ece46a74eb42341abda4c2c9adb`，98 个 testcase 覆盖全部 58 个 required identity，
0 skipped / 0 failure / 0 error。fresh attempt `92a6f6b7dfde445d89ca42c32cb555d5` 已通过 sealed candidate verifier、生产只读 dump、
隔离 PostgreSQL restore 和普通角色 bootstrap，随后在 exporter role bootstrap 以 `S6_ISOLATED_EXPORTER_ROLE_BOOTSTRAP_FAILED`
正确 fail closed；尚未执行 candidate exporter、真实 provider、S6 runner、构建或部署。

只读诊断证明 `agomtradepro_s6_exporter` 为 LOGIN/NOINHERIT、无 membership、无 database CREATE、无 schema CREATE，但通过 PostgreSQL
默认 `PUBLIC` grant 获得 database TEMP，故现有 guard 正确报告 write-capable privilege。提交 `fcc335f70` 在 disposable S6 database 上于
exporter grant/guard 前执行 `REVOKE TEMPORARY ON DATABASE :"database" FROM PUBLIC`，保留 TEMP/CREATE/table-write/membership 全部 guard，
没有把 TEMP 从阻断条件删除。独立真实 PostgreSQL 16 容器执行同一 SQL 后验证 CREATE=false、TEMP=false、schema CREATE=false、membership=0，
普通 SELECT 成功且 `CREATE TEMP TABLE` 失败。失败 attempt 的状态与阶段日志保留；临时 token/password 和精确 plan-bound PostgreSQL、Redis、
network、volume 在确认 prepare 退出后移除，没有触碰生产资源。

测试计数：prepare/source 聚焦回归 `28 passed / 6 skipped`，6 个 Windows POSIX capability skip 未计作通过；真实 PostgreSQL exporter
contract `1 pass`。Black、isort、Ruff、`bash -n`、Data Center 唯一投影连续 write/check、全仓 mypy debt ceiling
`0 errors in 0 files` 与 `git diff --check` 通过；未修改生产 Python，因此无增量生产 mypy 文件列表。

未验证风险与停止线：`fcc335f70` 与本节台账组成的新 HEAD 尚未由五组 exact-SHA CI 验证；撤销 `PUBLIC TEMPORARY` 后完整 migration、
十阶段和 release validator 必须由下一次 fresh S6 实证，不能引用失败 attempt 的前缀结果。生产 full-market 任务禁止重跑，两个周期入口保持
disabled；production financial refresh 的系统双审批、full-scope ceiling 和新明确授权停止线不变。

下一片是否可开始：可以提交台账并 push，新 exact SHA 从头运行五组 CI；全部通过并核验 official artifact 后，重新 reserve fresh attempt，
禁止 `--resume` 或复用本次 isolated runtime。完整 S6 成功前不得部署。

##### 2026-10-10 S6 candidate exporter 全入口零 bytecode 收口

完成项：候选 `a31d584f4d5aa84db1bac304e30e268bd55dc555` 的 Architecture `38023868878` 与 Security
`38023868856` 已通过；在其余三组完成及 fresh S6 reserve 前，Luna Max 横向审计发现 tracked prepare 仅给
`--verify-only` helper 调用增加了 `python3 -B`，而 production/universe/contract 三个 `--run-export` 模式仍由 root 使用普通
`python3` 执行同一个密封候选 helper。该 helper 导入 `scripts.rehearsal_checkpoint`，会产生与上一轮相同的 `__pycache__` 污染，随后
receipt/tree 复核必然 fail closed。Consistency `38023868925`、Fast Feedback `38023868852` 与 Publication PostgreSQL
`38023886358` 已主动取消；该 SHA 未 reserve S6，已通过的两组结果不得与新候选拼接。

提交 `c82cdc81c` 将 exporter 唯一调用点也改为 `python3 -B`；契约测试要求两个 candidate helper 执行入口全部使用 `-B`，并明确禁止
恢复普通 `python3 "$candidate_source_helper"`。POSIX 回归同时执行 verifier 帮助入口和 `--run-export` 参数失败入口，证明两条 CLI 路径
均不产生 `__pycache__`/`*.pyc`；没有删除 snapshot 复核、放宽文件权限，或以清理污染文件代替根因修复。

测试计数：prepare/source 聚焦回归 `28 passed / 6 skipped`；6 个 skip 均为本地 Windows 缺少 POSIX mode、symlink、fchown 或 bash
能力，未计作通过。Black、isort、Ruff、`bash -n`、Data Center 唯一投影连续 write/check（1,322 entries）、全仓 mypy debt ceiling
`0 errors in 0 files` 与 `git diff --check` 通过；未修改生产 Python，因此无增量生产 mypy 文件列表。

未验证风险与停止线：`c82cdc81c` 与本节台账组成的新 HEAD 尚未由同一 exact SHA 的五组 CI 验证；Linux `--run-export` 零 bytecode
反例、完整 official PostgreSQL artifact、fresh S6 十阶段和 release validator 仍须重新实证。六类已知环境契约不能证明未知类别穷尽。
生产 full-market 任务禁止重跑，两个周期入口保持 disabled；production financial refresh 的系统双审批、full-scope ceiling 和新明确授权
停止线不变。

下一片是否可开始：可以提交本节台账并 push，以新 exact SHA 从头运行五组 CI。只有五组全绿且 official artifact 所有 required
identity 零 skip/failure/error 后，才可由 planner 原子 reserve 新 attempt；禁止 `--resume`、复用旧 receipt/image 或在 CI 前启动 S6。

##### 2026-10-10 S6 prepare Python here-doc 失败分支收口

完成项：候选 `aeb4ada8d0259f914dd087887f003fa19b84022b` 的 Architecture `38024566876`、Security
`38024566891`、Consistency `38024566888`、Fast Feedback `38024566907` 与 Publication PostgreSQL
`38024578526` 全部通过。官方 artifact `11659523776`（API SHA-256
`70c2c3abbed10581fe21b26d9032bb23f4eb68a99e130f7ea861b00b19c8be33`）绑定同一 SHA；八个 JUnit 共 98 项，
全部 58 个 required identity 出现，0 skipped / 0 failure / 0 error，其中 financial-capacity 13 项、financial-slice 12 项、
Account final-revalidation 8 项与 5,001 member soak 均通过。

fresh attempt `c8584269d6ed4383be1886719d426e91` 通过密封候选/零 bytecode、runner runtime、最新生产只读 dump、隔离
PostgreSQL restore、普通角色与 exporter role bootstrap；production exporter 也以非 root `1000:1000` 成功生成四个受控文件，随后
wrapper 以 `S6_PRODUCTION_EXPORT_INVALID` fail closed。根因不是导出内容：`verify_candidate_files` 的 Python here-doc header 末尾存在两个
反斜杠，令下一物理行 `|| fail S6_CANDIDATE_INPUT_TREE_INVALID` 成为 Python stdin 第一行并触发 `IndentationError`。提交
`510cd4c4c` 将 provider env capture、candidate file verification 和 final validation 三处 here-doc 失败分支全部绑定到 header 同一物理行，
并新增门禁禁止任何 Python here-doc header 以反斜杠续行；没有删减校验或放宽稳定错误码。

测试计数：prepare/source 聚焦回归 `29 passed / 6 skipped`，6 个 skip 均为 Windows 缺少 POSIX mode、symlink、fchown 或 bash
能力，未计作通过。Black、isort、Ruff、`bash -n`、Data Center 唯一投影连续 write/check（1,322 entries）、全仓 mypy debt ceiling
`0 errors in 0 files` 与 `git diff --check` 通过；未修改生产 Python，因此无增量生产 mypy 文件列表。失败 attempt 未进入 S6 runner、构建或
部署；`prepare-status.json` SHA-256 为 `818f0ec269f2062716b403fb5939b6674ac5e08fb94b6b5b44ad03c2cfa6da3b`。
确认 prepare PID 退出后已清除该 attempt 的临时凭据、provider export 目录、精确隔离 PostgreSQL/Redis/network/volume 和旧候选工作区；
失败 root、状态、日志及 candidate receipt 保留，磁盘可用约 26 GiB。

未验证风险与停止线：`510cd4c4c` 与本节台账组成的新 HEAD 尚未由五组 exact-SHA CI 验证；修正后的三处 shell here-doc 必须由
Linux CI 与新 fresh S6 实证。上一候选五组成功不得拼接，失败 attempt 禁止 resume。生产 full-market 任务禁止重跑，两个周期入口保持
disabled；production financial refresh 的系统双审批、full-scope ceiling 和新明确授权停止线不变。

下一片是否可开始：可以提交本节台账并 push，新 exact SHA 从头运行五组 CI。全部通过且 official PostgreSQL artifact 身份完整后，
才可重新上传精确候选、由 planner reserve 全新 attempt 并运行 tracked prepare；禁止复用本次 receipt、isolated runtime 或 image。

##### 2026-10-10 S6 provider identity 完整图单一契约收口

完成项：候选 `61e9ce6a192ed769afa5b4aa424a050f96864baf` 的五组 exact-SHA CI 与 official PostgreSQL artifact
已通过，但 fresh attempt `587d6055090a46eb8314680f24ea8734` 在 runner 启动前以
`S6_PRODUCTION_EXPORT_INVALID` fail closed。该 attempt 已越过密封候选、全入口零 bytecode、最新生产只读 dump、隔离
PostgreSQL restore、普通角色与 exporter role bootstrap；production exporter 成功输出三个完整 provider identity。真实 graph 中
`quote` 与 `valuation` 的 `deployment_region` 按规范为 `null`，唯一 `akshare_financial_route:3` 为 `unknown`。prepare wrapper 的
production 与 final validation 却重复要求每行 region 均为 truthy，和唯一 identity parser 的合法契约冲突；现有 POSIX fixture 也只有一行
region，无法代表真实 graph。

提交 `15abb90c4` 将“核心 identity + 恰好一个 financial route”的完整图解析提升到
`parse_complete_rehearsal_identities` 单一规范函数，exporter、production validation 与 final validation 全部复用；wrapper 两次导入候选
契约均使用 `python3 -B`，不重新引入 sealed tree bytecode。正向 fixture 改为真实三行结构，并增加缺少/重复 financial route、普通 identity
错误携带 region、financial route region 缺失及 wrapper 稳定错误码反例；没有给 quote/valuation 合成区域，也没有放宽 provider identity、
freshness、coverage、audit 或请求门槛。

测试计数：identity/exporter/prepare 聚焦回归 `35 passed / 2 skipped`；两项 skip 为本地 Windows 无法提供的 POSIX 文件 mode 与 bash
实证，未计作通过。修改的两个生产 Python 文件增量 mypy 为 `0 regressions`，全仓 debt ceiling 为 `0 errors in 0 files`；Black、isort、
Ruff、`bash -n`、`git diff --check` 与 Data Center 唯一投影重新生成/check（1,322 entries，无投影差异）通过。wrapper 为 960 个非空行，
未扩大 1,000 行门槛。失败状态文件 SHA-256 为
`00395c45112c879f4ae28f2c15f88c31e9fdcb5c8ab074b45b3f672d5a94a1d9`；runner、构建与部署均未开始。确认 prepare 退出后已清除临时
凭据、临时 export、精确隔离 PostgreSQL/Redis/network/volume 与候选 workspace，失败 root、状态、日志及 source receipt 继续保留。

未验证风险与停止线：该代码提交与本节台账组成的新 HEAD 尚未由五组 exact-SHA CI 验证；Linux final validation 与完整 fresh S6 仍须重新
实证，不能引用上一 SHA 或失败 attempt 的前缀结果。六类已知环境契约不能证明未知类别已穷尽。生产 full-market 任务禁止重跑，两个周期入口
保持 disabled；production financial refresh 仍须 verified full-scope ceiling、系统内两个独立认证 owner/reviewer 事件与新的显式授权。

下一片是否可开始：可以提交本节台账并 push，以新 exact SHA 从头运行五组 CI。只有五组全绿且 official PostgreSQL artifact 的全部
required identity 零 skip/failure/error 后，才可原子 reserve 新 fresh attempt；禁止 `--resume`、复用旧 receipt/image 或在 CI 前启动 S6。

##### 2026-10-10 Fast Feedback 身份证据、时间与发布契约收口

完成项：候选 `b94b9d3005bfb7baa7535ab5d4a1800e4e498677` 的 Architecture `38030247738`、Security
`38030247930`、Consistency `38030247751` 与 Publication PostgreSQL `38030247906` 通过；官方 artifact
`11662142782` 的 API SHA-256 为 `6a1280b5835e8009329e99cf7d0fd8899b553d4dfd8cd58a7a550d93d0630ba6`，八个 JUnit
共 98 项，全部 58 个 required identity 出现且 0 skip/failure/error。但 Fast Feedback `38030247743` 在 Python 3.11/3.13
同时出现相同六项失败，因此旧 SHA 不得进入 S6，也不得重跑旧 run。独立审计将失败归为三类：多个证据写入点使用 dataclass
`asdict`，把核心 identity 的可选 region 重新写成 `null`；两处 financial fixture 没有必需 region；容量审批 fixture 固定在
2026-10-09 到期，且 core publication 规模测试仍把已由 receipt-gated workflow 接管的 financial lane 当作通用 dataset。

提交 `031f73bf8` 增加 `rehearsal_identities_payload` 单一规范序列化入口，并让 identity verification、provider export、market
rehearsal、policy parity、response replay、financial slice、scope discovery 与主 release runner 全部复用；核心 identity 省略 region，
financial route 保留真实 region，digest 与 validator 继续使用同一 canonical shape。提交 `06b0eddfd` 将容量测试改为相对当前 UTC
时钟，并让规模测试断言明确的 `financial_capacity_receipt_required` deferred lane；生产的审批有效期和 financial fail-closed 门禁均未修改。

测试计数：原六个失败节点修复后 `6 passed`。相关 11 个测试文件扩大回归为 `145 passed / 1 skipped`，唯一 skip 是 Windows
无法实证的 POSIX snapshot mode；release runner 与 validator 回归为 `260 passed / 3 skipped`，三项 skip 为 Windows 缺少 POSIX
file/directory symlink 与 ownership/mode 注入，均未计作通过。修改的八个生产 Python 文件增量 mypy 为 `0 regressions`，全仓
mypy debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：上述两个提交和本节台账组成的新 HEAD 尚未由五组 exact-SHA CI 验证；旧 SHA 的四组成功与 PostgreSQL artifact
不得拼接。Linux 对 canonical identity 图、Fast Feedback 双 Python、official PostgreSQL required nodes、fresh S6 十阶段及 release
validator 仍须重新实证。六类已知环境契约不能证明未知类别穷尽。生产 full-market 任务禁止重跑，两个周期入口保持 disabled；production
financial refresh 仍须 verified full-scope ceiling、系统内两个独立认证 owner/reviewer 事件和新的显式授权，聊天授权不替代这些事实。

下一片是否可开始：可以提交本节台账并 push，新 exact SHA 从头绑定 Architecture、Security、Consistency、Fast Feedback 与
Publication PostgreSQL。五组全绿且官方 artifact 全部 required identity 零 skip/failure/error 后，才可由 planner 原子 reserve
全新 attempt；fresh S6 禁止 `--resume`，完整十阶段与 release validator 通过后只能部署 receipt 绑定的同 SHA 预构建镜像。

##### 2026-10-10 S6 target-date authority 与 internal-network prepare 收口

完成项：候选 `f7229ecee492ae288aed9c03e0df49b82158ab64` 的 fresh attempts 依次在 runner 前暴露三条独立环境边界：
`522b02...` 从非 Git 密封 source 调用 planner，稳定码 `S6_PREPARE_WORKSPACE_UNAVAILABLE`；`bc215f...` 在既有 24 GiB
门槛下以 `S6_DOCKER_DISK_HEADROOM_INSUFFICIENT` 正确阻断，确认无 active build 后只清理未使用 cache/image，使可用空间恢复约
28 GiB；`11fa71b43e504660b2f77a6ff7a31d28` 已从最新生产只读快照恢复隔离 PostgreSQL，但 `universe` exporter 在
internal network 内调用 provider-backed 市场日历，因无 Tushare/Akshare 出口返回 `S6_TARGET_SESSION_UNAVAILABLE`。三次均未启动
runner、构建、部署或生产写；失败目录与诊断保留，disposable runtime 只在确认退出后精确清理，禁止 resume。

提交 `fe85403a9` 删除 prepare 对 provider calendar 和主机当前时间的依赖。target date 现在在一个已验证的 PostgreSQL
`REPEATABLE READ READ ONLY` 快照中，由三类 current pointer、publication header/member/scope block、精确 PriceBar、
CandidateRawAuditManifest 与 Task Monitor 结果共同证明；task attempt、run、确定性 activation、publication ID/hash、member seal、
事实 content hash、source time、15:00 close 和 coverage 摘要全部一致才返回。Task Monitor 同时安全支持 bounded JSON 与历史 literal
编码。生产现状的 price 5572 requested / 5561 selected / 11 missing 仅在 11 个 scope blocks 与 publication hash 精确闭合时允许，
未写死证券、未放宽 coverage，也不会因有证据的停牌范围阻断整个系统。新的真实 PostgreSQL production-composition 节点已加入
`REQUIRED_POSTGRESQL_TESTS`。

测试计数：exporter/validator 单元回归 `171 passed / 1 skipped`；唯一 skip 为 Windows 未启用 disposable PostgreSQL，未计作通过。
修改的两个生产脚本分别通过增量 mypy，均为 `0 regressions`；全仓 mypy debt ceiling 为 `0 errors in 0 files`。Black、isort、Ruff、
`git diff --check` 和 Data Center entrypoint 唯一生成器 check 通过，投影仍为 1,322 entries、无手工差异。生产只读核查确认当前三个
pointer 共享 activation `19d9a93e-55b6-5b8e-882d-8f3160f560dc`，Task Monitor attempt
`709a571d92f7474f8bc001268bd59050` 与三份 manifest 一致，price 11 个 scope blocks 与 coverage 对账闭合；该核查未写生产。

未验证风险与停止线：新增 PostgreSQL 节点必须由新 exact-SHA official artifact 实跑且零 skip/failure/error；本地 Windows skip 不能替代。
新逻辑尚未在 fresh S6 internal network 中实证，六类已知环境契约仍不能证明未知类别穷尽。不得重跑 production full-market task
`bcb3e00f-538e-420d-b179-428c40082f43`；两个周期入口保持 disabled。production financial refresh 仍须有效 full-scope ceiling、
系统内独立 owner/reviewer approval 与新的明确授权，聊天授权不替代这些事实。

下一片是否可开始：可以提交本节台账并 push，以含代码与台账的新 exact SHA 从头运行五组 CI。只有五组全绿、official PostgreSQL
artifact 包含新增 target-date 节点及全部既有 required identity 且零 skip/failure/error，才可从最新生产只读快照 reserve 新 fresh S6；
禁止 `--resume` 或复用历史 receipt/image。S6 十阶段与 release validator 全部通过后，只能部署 receipt 绑定的同 SHA 预构建镜像。

##### 2026-10-10 Publication PostgreSQL 隔离 composition 与事实回读收口

完成项：候选 `eb4c9767caf8cc29b347d5db7a4ae7410e597e10` 的 Architecture `38038196485`、Security
`38038196474` 与 Consistency `38038196475` 已通过，但 Publication PostgreSQL `38038196480` 在
`Exercise real publication locks and frozen facts` 收集阶段失败，因此该 SHA 不得进入 S6，已通过组也不得与后续候选拼接。失败根因不是
target-date 业务断言：新增 production-composition 节点首次把真实 `TaskExecutionModel` 纳入隔离 schema，但专用
`tests.settings_data_center_sync_identity` 未注册 Task Monitor；直接补注册后，Django 继续加载该模块既有 repository 依赖的
`django_celery_beat`，故两者必须作为同一隔离 composition 完整登记。

提交 `c41b3360a` 新增无 production `ready()` 副作用的 `IsolatedTaskMonitorConfig`，同时在专用 settings 中登记
`django_celery_beat`，并将 `task_monitor` 迁移交给该 PostgreSQL fixture 的显式 schema 建表清单。修复没有修改生产模型、workflow、
测试选择或 required identity，也没有跳过新增节点；同一 exact workflow 命令在本地已能完整收集测试，不再出现 app-label 错误。

包含上述修复的候选 `43507ec55248595d4e907b510682014863997301` 已由 Architecture `38038952136`、Security
`38038952149` 与 Consistency `38038952167` 通过，并在 Publication PostgreSQL `38038952128` 实际执行到新增节点：其余 50 项通过，
target-date 节点以稳定码 `S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID` fail closed。第二层根因是 fixture 在 `INSERT`
PriceBar 后直接用未回读的 Python 对象生成 `fact_content_hash`；PostgreSQL 按列精度规范化 Decimal 后，exporter 从数据库读取的事实行
哈希与该内存态哈希不同。提交 `2a1843e20` 要求 fixture 按主键从数据库重新读取已持久化行后才生成 publication member，与真实发布路径
一致；严格 content-hash 绑定保持不变。失败 run `38038952128` 同样不得重跑或与后续候选拼接。

测试计数：exporter/validator 单元回归 `171 passed / 1 skipped`；Publication PostgreSQL exact 命令本地收集成功，因 Windows 未提供
显式 disposable PostgreSQL 为 `51 skipped / 6 deselected`，这些 skip 不计作通过。Black、isort、Ruff、`git diff --check` 与全仓
mypy debt ceiling `0 errors in 0 files` 通过；本片未修改生产 Python，因此无增量生产 mypy 文件列表。

未验证风险与停止线：隔离 composition、持久化事实回读和新增 target-date 节点仍必须由包含本片与本节台账的新 exact-SHA Linux
official artifact 实跑，全部 required identity 必须零 skip/failure/error。失败 runs `38038196480`、`38038952128` 禁止重跑或作为
后续证据。fresh S6、同镜像部署与只读
联合 UAT 尚未开始；生产 full-market 任务禁止重跑，两个周期入口保持 disabled。production financial refresh 的 full-scope ceiling、
系统内独立 owner/reviewer approval 与新明确授权停止线不变。

下一片是否可开始：可以提交本节台账并 push，以新 HEAD 从头绑定五组 exact-SHA CI。仅当五组全绿且 official PostgreSQL artifact
包含新增 target-date、financial slice、Account outer-fence 与 5,001-member soak 等全部 required identity，且零 skip/failure/error，
才可从最新生产只读快照 reserve fresh S6；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-10 Audit authority 恢复与新一轮全市场终态取证

完成项：候选 `f468ba12bf4e7ef3bd48d68edfb4f41c9df0a7fd` 的 Architecture `38039435803`、Security
`38039435698`、Consistency `38039435594`、Fast Feedback `38039435679` 与 Publication PostgreSQL
`38039435680` 全部通过；官方 PostgreSQL artifact `11665701122` 的 API SHA-256 为
`95cb9e3d149e94f59d4bb832a47534cdcf28759a4860b996b0a89714fd8e712f`，八份 JUnit 共 99 项且 required financial slice、Account outer-fence 与 5,001-member soak 节点均为
0 skipped / 0 failure / 0 error。fresh S6 attempt
`8fbbf7c258aa42879f14cce9b2fdb378` 在 `provider_probe` 以稳定码 `REHEARSAL_RESPONSE_FUTURE_DATE`
正确 fail closed：正式 current publication graph 仍绑定 `2026-09-30`，实时腾讯响应已晚于该 target；没有保留 provider artifact、
没有构建、部署或生产写，provider probe 诊断 SHA-256 为
`2824ce5afa6afe1ed33238df907896b6e8d9887ed3cc08d0ee52d3e54eeca94c`，失败 attempt 保留且禁止 resume。

生产 audit authority 已按既有 session-protected 流程重新采集真实 raw authority sources，并完成新的系统审计权限恢复；当前 profile 为 v20，
有效期至 `2026-10-23T15:50:47.606393+00:00`，证据根目录为
`/opt/agomtradepro/rehearsals/audit-authority-recovery-20261010`。提交 `740ef29e8` 在写入前新增 consumed-envelope、
predecessor/CAS 与 actor snapshot 只读预检，保留事务内 first-winner 竞争校验；旧已消费 envelope 继续禁止复用。

在 authority、lease、队列、周期入口 disabled 与目标交易日 `2026-10-09` 全部通过后，仅投递一次新的显式 full-market task
`8b960102-a668-48c7-b9f1-5261d526569c`，attempt `146099a2faad4841b0c25329f9af3e4a`，dispatch receipt
SHA-256 `7af9db9f497dc60134192787f27d9077e13128b65a7111196e1dfd43fcb945f6`。任务技术终态为 success，但规范业务终态为
partial：`requested/succeeded/failed/stored=5573/0/5573/5573`，publication `0/1`、`publication_updated=false`，
稳定码 `MODEL_MARKET_BATCH_FACTORS_MISSING`；lease 已释放，三个 current pointer 未切换。终态业务证据 SHA-256 为
`f31646b50e07aed3c3d8d1155ea9bcfb6721a311a3730197ab2473401a9725dd`，current pointer 证据 SHA-256 为
`722dd3f3a07656d3769b393be25dcc1122cc6a8653e271037afef480ad02fb18`。该 task 禁止再次投递或重跑。

测试计数：`740ef29e8` 的 audit authority 聚焦回归 `44 passed`；四个修改的生产 Python 文件增量 mypy 为
0 issues / 0 regressions，全仓 mypy debt ceiling 为 `0 errors in 0 files`，Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：生产仍运行旧 revision，正式 graph 未前移，因此 decision runtime 继续按保护阻断。当前 financial publication 仍是
legacy policy identity；production financial refresh 必须具备 verified full-scope capacity、系统内两个独立认证 owner/reviewer 事件与
新的显式授权，聊天授权不替代这些事实。两个周期入口继续 disabled。不得重跑上述 full-market task，也不得用未来日期放宽、合成 source time
或旧 receipt 绕过 S6 target-date 约束。

下一片是否可开始：可以修复本次真实 provider 契约根因并以新 exact SHA 从头运行五组 CI；全部通过后再选择不削弱未来日期保护的恢复路径。

##### 2026-10-10 行情日线与复权因子方向性覆盖契约整改

完成项：生产只读探针确认本次 14 个动态缺失报价证券在目标日 `daily_row_count=0`，但 `adj_factor` 返回 14 行；两组已知证券探针同时证明
多代码 daily/factor 路由本身可用。根因是批量与 session 准备把“daily 与 adj_factor 必须同时为空或同时非空”错误建模为对称不变量。
提交 `b85aeaf9f` 改为方向性覆盖：只对实际 daily `(ts_code, trade_date)` 键要求恰好一个有限且大于零的复权因子；没有对应 daily
键的额外 factor 行不参与校验。daily 非空而因子缺失、重复、非有限或非正仍 fail closed，并保留原稳定业务码、审计、停牌证据查询与缓存语义；
没有写死证券、增加 fallback、扩大 timeout/retry 或放宽 coverage。

测试计数：provider 与行情发布相关五个测试文件合计 `185 passed`，覆盖代码批次、全市场 session、混合 daily/factor、factor-only、
daily key 因子缺失/重复/无效以及经 `ModelMarketDataService` 查询停牌并复用 `MODEL_MARKET_SUSPENDED` 的端到端反例。修改的生产文件
增量 mypy 为 0 issues / 0 regressions，全仓 mypy debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff 与
`git diff --check` 通过。

未验证风险与停止线：本片尚未经过 exact-SHA 五组 CI、真实 provider fresh S6 或生产同镜像验证；上一候选的 CI 成功不能拼接使用。
失败 full-market task `8b960102-a668-48c7-b9f1-5261d526569c` 禁止重跑。正式 current graph 仍停在
`2026-09-30`，新的 fresh S6 会继续正确拒绝晚于 target 的 provider 响应，不能通过放宽 future-date guard 解决。production financial
refresh、两个周期入口和普通用户凭据停止线不变。

下一片是否可开始：可以提交本节台账并 push；新 exact SHA 必须从头绑定 Architecture、Security、Consistency、Fast Feedback 与
Publication PostgreSQL。五组全绿且 official artifact required identities 零 skip/failure/error 后，才可执行受控恢复；任何用于前移正式
graph 的生产任务必须是新的显式任务且只允许一次，随后重新从最新生产只读快照执行 fresh S6，禁止 `--resume`。

##### 2026-10-10 最终候选治理投影与可靠性字典前移门禁

完成项：候选 `40b450f2b669cc04921c394ef0d6a53b2d03ef08` 的 Security `38049909445` 通过；Architecture
`38049909428` 因 module map 漂移失败，Consistency `38049909424` 因 audit authority 新增动态 block reason 未登记失败，故该 SHA
立即失去候选资格。Publication PostgreSQL `38049909426` 已取消，Fast Feedback `38049909452` 已提交取消请求；旧 run 均禁止重跑或与
后续结果拼接。Architecture 根因是 `740ef29e8` 增加三条 `account → audit` import 后没有运行模块图唯一生成器；提交
`ef822cc20` 仅用 `python scripts/build_module_map.py` 生成 `account.depended_by.audit` 与
`audit.depends_on.account` 的 27→30 计数变化。Consistency 根因是同一提交新增管理命令稳定码和两个动态输出边界却未同步 reliability registry；
提交 `5ee9f502f` 登记 `renewal_transaction_rejected` 及 recovery/renewal 的收敛 allowlist，不扩大允许字符或未知错误透传。

为把同类投影错误前移到开发机，提交 `ec731270f` 将 `python scripts/check_module_map.py` 加入仓库既有 pre-push hook，和两个 Data
Center 投影检查一起执行，并同步工程门禁文档。钩子仍只检查、不自动改写工作树；生成投影仍只能调用唯一生成器。

测试计数：module map write/check 通过，`modules=44 / edges=210`；reliability ownership guard 通过，`statuses=7 / reasons=16`；
Data Center architecture inventory 与 entrypoint inventory 直接执行通过，entrypoint 总数 1,322；`git diff --check` 通过。本机 Python
环境未安装 `pre_commit` 包，无法执行 `pre-commit validate-config/run`，因此没有把该命令记作通过；三个 hook 的实际 entry 命令已逐一直接
执行，YAML hook 装载仍须由新 Linux CI 实证。

未验证风险与停止线：上述三个提交与本节台账组成的新 SHA 尚未运行五组 CI；旧候选的 Security 成功不能复用。pre-push 只有在开发者按文档
安装 hook 后才会本地执行，远端 Architecture/Consistency 仍是强制 fail-closed 兜底。fresh S6、部署、正式 graph 前移和只读联合 UAT
均未开始；production financial refresh 与两个周期入口停止线不变。

下一片是否可开始：可以提交台账并 push，以新 exact SHA 从头运行五组 CI。五组全绿且 official PostgreSQL artifact required identities
零 skip/failure/error 前不得 reserve fresh S6 或部署。

##### 2026-10-10 S6 隔离 current market graph 前移解环

完成项：候选 `e90f8140bee20582edbdc1cab5052e960dafbc10` 的 Architecture `38050583246`、Security
`38050583289`、Consistency `38050583297`、Fast Feedback `38050583278` 与 Publication PostgreSQL
`38050638140` 已全部通过；官方 PostgreSQL artifact `11668884855` 的 API SHA-256 为
`0ad9c99321ef479e25a0c2104c438faba51e604b6d1b3b4761c5a0c8ddcb897d`，八份 JUnit 共 `99 tests`，全部
`59` 个 required identity 出现，financial slice、Account outer-fence 与 5,001-member soak 均为 0 skip/failure/error。
标准部署入口随后正确拒绝没有 fresh S6 receipt 的候选，未改生产；旧 bundle 仅绑定 bundle manifest、没有 S6 handoff receipt，未被
当作 break-glass 使用。只读审计确认仓库不存在受治理的 S6 豁免部署路径。

提交 `8545685149fca78417ed38a6f4383cdcb6b9aca2` 将 attempt plan 升为 v3，新增默认关闭、必须在 plan 中显式绑定的
`advance_isolated_market_graph`。启用后，tracked prepare 只在从最新生产只读快照恢复出的 disposable PostgreSQL/Redis/network 上，
用 exact candidate source 和当前不可变执行镜像依赖运行一次真实 full-market Task Monitor 任务；候选代码同时校验实际数据库名/host、
容器和 network 不可变 ID、唯一网络成员及执行镜像。成功 receipt 绑定 candidate/attempt/plan、规范业务 outcome 与
`requested/succeeded/failed/stored`、Task Monitor attempt、target trade date、run/activation、三份 current pointer/publication、
重算 member manifest/publication/fact hash 以及最早/最晚 source time。universe 与 contract exporter 在只读事务中重新读取完整 graph 并
逐项重建 receipt；任何任务、身份、日期、哈希、文件集合或权限漂移均 fail closed，失败不生成成功 prepare receipt。默认 opt-out 不运行
provider、不写 graph、不增加 receipt。未放宽 future-date、15:00 close、freshness、coverage、audit、source 或任何请求/查询门槛。

长 final-validation heredoc 已下沉到受测 Python helper，prepare wrapper 保持 `985` 个非空行，未越过 1,000 行门槛。Data Center
operational ownership、planner v3 证据、S6 环境契约与唯一 entrypoint 投影均已同步；生成投影为 `1,328 entries`，其中
`848 active_public / 337 adjacent_operational / 5 candidate-review / 138 compatibility`，legacy direct/wrapper 均为 0。

测试计数：最终核心五文件回归为 `87 passed / 11 skipped`；11 项均为 Windows 无法实证的 POSIX directory symlink、file mode、
mount mode、descriptor、Linux bash `-u`、POSIX Python bytecode 与 snapshot mode，未计作通过。inventory/legacy 治理回归为
`32 passed`。五个修改的生产脚本分别通过增量 mypy，全仓 mypy debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、
`py_compile`、`bash -n`、唯一 entrypoint projection stale check、legacy checker 与 `git diff --check` 均通过。Windows 重复整包运行
曾分别出现一次临时 Git clone `HEAD_UNAVAILABLE` 与 `STATUS_UNAVAILABLE`，对应测试隔离重跑均通过；同一最终工作树另有完整核心整包
全绿证据，Linux CI 仍须复核这些主机相关路径。

未验证风险与停止线：本 opt-in 尚未在真实 Linux Docker、VPS、真实 provider 与 fresh S6 中实证，不能据本地测试宣称解环完成；六类已知
环境契约仍不能证明未知类别穷尽。新提交尚未绑定五组 exact-SHA CI，旧候选 `e90f8140b` 的成功证据不得拼接。失败 production
full-market task `8b960102-a668-48c7-b9f1-5261d526569c` 禁止重跑；新的生产 full-market 写入只能在同 SHA fresh S6 与 receipt-bound
部署通过后，按用户现有授权执行一次新 task。两个周期入口继续 disabled。production financial refresh 仍须 verified full-scope
capacity、系统内两个独立认证 owner/reviewer 事件和有效 ceiling；聊天授权不能替代这些系统事实。

下一片是否可开始：可以提交本节台账并 push，以包含实现和台账的新 exact SHA 从头运行 Architecture、Security、Consistency、Fast
Feedback 与 Publication PostgreSQL。只有五组全绿且 official artifact 的全部 required identity 为零 skip/failure/error，才可从
最新生产只读快照 reserve 一个启用 `advance_isolated_market_graph` 的 fresh attempt；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-10 S6 final validation Linux fixture 契约修复

完成项：候选 `cb8fb84d71149ffa979d209029b530bc8c88d519` 的 Architecture `38057645883`、Security
`38057645891` 与 Consistency `38057645939` 通过，但 Fast Feedback `38057645886` 在 Python 3.11 与 3.13 的同一 targeted suite
各自稳定复现 3 项失败，因此该 SHA 失去候选资格，已通过结果不得与后续 SHA 拼接。根因不是生产隔离环境失效：POSIX-only fixture
用随机 attempt 生成 v3 plan 后，仍把 PostgreSQL/Redis 容器名与数据库名写死为旧测试值，导致 final validator 在目标断言之前正确报
`S6_ISOLATED_DATABASE_ENVIRONMENT_INVALID`；另一个反例新增 `unexpected.json` 后未设置 `0600`，先触发文件 mode 校验而非预期的
file-set 校验。修复让 fixture 完全读取 plan 生成的资源身份，并让多余文件反例先满足既有 mode 前置不变量；生产校验顺序与门槛未改。

测试计数：本地相关回归 `33 passed / 9 skipped`，其中 9 项为 Windows 无法验证的 POSIX mode/symlink/bash 行为，未计作 Linux 通过；
聚焦文件回归 `10 passed / 3 skipped`。全仓 mypy debt ceiling 为 `0 errors in 0 files`，Black、isort、Ruff 与 `git diff --check`
通过。本片仅修改测试 fixture 与本台账，没有生产 Python 改动。

未验证风险与停止线：三项 POSIX-only 修复仍须由新 exact-SHA Linux Fast Feedback 实跑；失败 run `38057645886` 禁止重跑。
Publication PostgreSQL `38057688557` 即使单独完成也不能与后续候选拼接。fresh S6、部署、一次新生产 full-market 与联合 UAT 尚未开始；
旧 task `8b960102-a668-48c7-b9f1-5261d526569c` 禁止重跑，两个周期入口保持 disabled，production financial refresh 停止线不变。

下一片是否可开始：可以将测试 fixture 与本节台账作为一个独立修复提交并 push，以新 exact SHA 从头运行五组 CI。只有五组全绿并完成
official PostgreSQL artifact identity 核验后，才可 reserve fresh S6；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-10 S6 provider identity 数组读取边界修复

完成项：候选 `25670aa084b7ae147879bd7bef9205677a5f07ee` 的 Architecture `38058767487`、Security
`38058767436` 与 Consistency `38058767434` 通过，但 Fast Feedback `38058767433` 在 Python 3.11 和 3.13 各自稳定失败 2 项；
该 SHA 不得进入 S6，已通过结果不得拼接。前一片修复已让验证越过动态 database/container 与 mode 前置不变量，随后暴露真实生产边界缺陷：
final validator 复用只接受 JSON object 的 `_read_validation_json` 读取 `provider-identities.json` 数组，因此任何合法完整身份数组都会以
`S6_PROVIDER_IDENTITIES_INVALID` fail closed。修复新增有界的 JSON array reader，保持 symlink/regular-file/UTF-8/JSON shape 拒绝语义，
provider identity 仍交由唯一 complete-graph parser 校验；同时增加数组正例和 object 反例。没有放宽身份、来源或 S6 门槛。

测试计数：prepare/snapshot 相关回归 `35 passed / 9 skipped`；9 项均为本机 Windows 无法覆盖的 POSIX mode、symlink 与 bash 行为，
未计作 Linux 通过。修改的生产 Python 文件增量 mypy 为 0 issues / 0 regressions，全仓 mypy debt ceiling 为
`0 errors in 0 files`；Black、isort、Ruff 与 `git diff --check` 通过。

未验证风险与停止线：完整 final receipt happy path 与 graph-run drift 反例仍须由新 exact-SHA Linux Fast Feedback 实证；失败 run
`38058767433` 禁止重跑。该 SHA 的 Publication PostgreSQL `38058817071` 不得与后续结果拼接。fresh S6、部署、一次新生产
full-market 与联合 UAT 尚未开始；旧 task `8b960102-a668-48c7-b9f1-5261d526569c` 禁止重跑，两个周期入口保持 disabled，
production financial refresh 停止线不变。

下一片是否可开始：可以提交本生产边界修复、测试与台账并 push，以新 exact SHA 从头运行五组 CI。只有五组全绿且 official
PostgreSQL artifact 的 required identities 全部零 skip/failure/error，才可 reserve fresh S6；禁止 `--resume` 或复用旧 receipt/image。

##### 2026-10-10 S6 只读候选运行时日志目录契约修复

完成项：候选 `f81f9d468ada2bf7cdd584b2a43939a9bf83be3e` 的 Architecture `38059890766`、Security
`38059890777`、Consistency `38059890770`、Fast Feedback `38059890796` 与 Publication PostgreSQL
`38059922855` 全部通过；官方 PostgreSQL artifact `11672653638` 共 `99 tests`，全部 `59` 个 required identity
出现，financial slice、Account outer-fence 与 5,001-member soak 均为 0 skip/failure/error。fresh S6 attempt
`df56fa16294b4f04b6dd0d09821c37e3` 随后在 prepare 的 isolated current graph refresh 前以稳定码
`S6_GRAPH_REFRESH_COMMAND_FAILED` / `S6_GRAPH_REFRESH_RUNTIME_FAILED` fail closed，未生成 prepare receipt、未启动十阶段 runner，
生产 Task Monitor 没有对应 task，current pointers 与两个 disabled 周期入口均未改变。失败 status SHA-256 为
`590bf48f70707906dd7ba4a115643630e2b18f19caee15aed6d85d424601a8c1`；attempt 目录与诊断保留，disposable
PostgreSQL/Redis/network/volume 在确认进程退出后按精确 namespace 清理。

根因是候选源码和根文件系统按契约只读挂载时，`django.setup()` 仍在生产设置导入阶段无条件计算 Celery 文件日志路径，尝试创建
`/candidate-src/logs`，因此在 Task Monitor/provider I/O 之前触发 `PermissionError`。提交 `41932f71b` 增加通用
`AGOM_LOG_DIR` 契约：未设置时生产默认行为保持不变；S6 runner、candidate export 与 isolated graph refresh 显式使用既有
`/tmp` tmpfs 下的 `/tmp/agomtradepro/logs`，继续保持 candidate source 和 root filesystem 只读。统一 stage environment
preflight 对全部候选阶段检查环境值、Celery worker/beat 路径、可写目录，以及启用 `LOG_TO_FILE` 时的 Django file handlers；问题以
`REHEARSAL_STAGE_RUNTIME_LOG_DIRECTORY_INVALID` 加入聚合结果，后续网络、身份、时钟和外部状态检查仍继续执行。

测试计数：核心定向回归 `90 passed / 9 skipped`，日志路径与 preflight 补充回归 `20 passed`，契约矩阵回归 `1 passed`；9 个 skip
均为本机 Windows 无法验证的 POSIX/Linux 行为，未计作 Linux 通过。7 个修改的生产 Python 文件增量 mypy 为 0 issues /
0 regressions，全仓 mypy debt ceiling 为 `0 errors in 0 files`；Black、isort、Ruff、module-map write/check 与
`git diff --check` 通过，模块投影保持 `44 modules / 210 edges`、无生成差异。

未验证风险与停止线：该修复尚未在 Linux Docker 与 fresh S6 中实证，`/tmp` tmpfs、非 root UID 创建日志目录和统一 preflight
必须由新 exact-SHA 五组 CI 与 fresh prepare/runner 验证；六类已知环境契约仍不能证明未知类别穷尽。失败 attempt 禁止 resume，旧
receipt/image 不得复用。生产 full-market 旧任务均禁止重跑；新的生产 full-market 仅在同 SHA fresh S6、receipt-bound 部署通过后，
按现有授权执行一次。两个周期入口保持 disabled。production financial refresh 仍须 verified full-scope capacity、系统内两个独立认证
owner/reviewer 事件和有效 ceiling；聊天授权不能替代这些系统事实。

下一片是否可开始：可以提交本节台账并 push，以包含实现与台账的新 exact SHA 从头运行 Architecture、Security、Consistency、
Fast Feedback 与 Publication PostgreSQL。只有五组全绿且 official artifact 的全部 required identity 零 skip/failure/error，才可从
最新生产只读快照 reserve 新 fresh S6；禁止 `--resume` 或复用历史 receipt/image。

##### 2026-10-10 Fast Feedback sealed helper fixture 收口

完成项：候选 `54cd9ae2378474162cd3e850c5fbd4d54a628b12` 的 Architecture `38063634610`、Security
`38063634643`、Consistency `38063634644` 与 Publication PostgreSQL `38063634602` 通过，但 Fast Feedback
`38063634591` 在 Python 3.11/3.13 的定向套件中失败，因此该 SHA 不得进入 S6，四组成功结果不得与后续候选拼接。失败包含两个独立的
fixture/治理断言：sealed helper POSIX fixture 只复制原有两个脚本，未复制新引入的 `shared/runtime_log_paths.py` 依赖；governance
consistency 测试仍断言 `architecture_rules.json` 的旧 `2026-06-30.v8`，而唯一治理文件已于既有提交升级为
`2026-10-09.v9`。提交 `272e7196a` 只扩展 sealed fixture 的依赖集合并同步已有治理版本断言，没有修改生产行为、扫描规则或门槛。

测试计数：本地聚焦回归 `1 passed / 1 skipped`；skip 为 Windows 无法执行的 POSIX Python sealed-helper bytecode 契约，未计作通过，
必须由新 Linux Fast Feedback 实证。两个测试文件的 Black、isort、Ruff 与 `git diff --check` 通过；本片没有生产 Python 改动，
不适用增量生产 mypy。

未验证风险与停止线：POSIX fixture 修复尚未在新 exact-SHA Linux CI 实跑；失败 run `38063634591` 禁止重跑，候选
`54cd9ae23` 的其他成功 run 也不再是 release 证据。fresh S6、部署与生产任务均未开始；production full-market 与 financial refresh、
两个周期入口的既有停止线不变。

下一片是否可开始：可以提交本节台账并 push，以新 HEAD 从头绑定五组 exact-SHA CI。只有五组全绿且 official PostgreSQL artifact
required identities 零 skip/failure/error，才可 reserve fresh S6。
