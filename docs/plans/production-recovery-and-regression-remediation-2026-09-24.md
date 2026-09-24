# 生产恢复与系统性防回归整改计划（2026-09-24）

状态：执行中。用户已要求主代理带领 GPT-5.6 Luna（max）子代理完成本计划，并设置持续执行 goal。
工作基线：`dev/next-development@12c65a919`；生产版本必须另行读取，不能把本地 HEAD 当作部署版本。
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

执行协调更新：任务 `01a0b754-cfdb-7a11-8416-3d72c88dee45` 正在处理审计身份恢复、生产重跑和最终提交/合并/部署。本任务及三位子代理保留未提交补丁，完成本地审查与证据后交接，暂不执行 commit/merge/deploy；避免修改 `apps/audit/**`、部署脚本和仓库根 README。`data_center.0085` 由本任务保留用于事实修订，部署前须确认所有写入器版本一致。

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

上线涉及 provider、current Publication、Alpha 或任务规模的改变时，必须先形成与候选提交绑定的预演报告。

1. 固定真实 provider、目标交易日、当前完整 universe/hash 和确定性的约 50 只样本（若不足则完整范围）；覆盖不同交易所、单位、新上市、停牌等真实可获得类别，不造边界数据。
2. 使用真实配置/真实时钟调用 provider，记录脱敏来源、响应身份、单位、源时间、覆盖、failover 一致性、延时/请求配额和数据错误。
3. 默认不修改生产事实、current publication、推荐或任务；写路径演练在隔离 staging/临时数据库中走真实装配并验证回滚/零残留。provider 读取本身消耗配额，必须记录预算。
4. 重放有效/缺失/截断/陈旧/重复/单位错误/后续事实更新等契约；财报 source-time 无证据必须明确 blocked。
5. 按真实规模测算全量预算，记录审计有效窗口、软硬时限和安全余量；不接受线性外推掩盖有状态锁/配额上限。
6. 发布门检查报告的候选、测试哈希、provider/范围/目标日、实际调用证据与时效；缺报告、mock-only、failed/partial/blocked 均不得宣称门禁通过。
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
| R1 发布/运行时/Alpha | 候选代码完成，生产待验 | 四类事实不可变修订、完整交易日历、发布计数和 Alpha 只读/显式刷新已形成组合回归；正式发布、运行时激活和当前日 Alpha 仍须在同一部署候选验证 |
| R2 信号/MCP | 候选代码完成，生产待验 | API/SDK/MCP 分页、最后业务 503、政策待分类及安全业务码已回归；部署重启后的新 MCP 会话待验 |
| R3 只读/工作台/文案 | 候选代码完成，生产待验 | 账户归属、GET 零写入、研究入口、慢请求/重试和缺失价格语义已通过本地行为验收；生产普通投资者浏览器 UAT 待验 |
| R4 进度/诊断 | 候选代码完成，生产待验 | current attempt / last completed、phase、outcome、计数单位和安全错误投影已形成回归；生产任务结果待验 |
| S1–S5 | 候选代码完成，远端 CI 待验 | 真实 provider 契约、不变量、时间、规模和跨消费者选测已集成；同一最终 SHA 的远端 CI 结果仍须冻结 |
| S6 | 门禁代码完成，真实证据待采集 | 部署前验证器固定四类报告、候选/日期/universe/provider、时效、响应/写入 artifact 与 23 项 PostgreSQL JUnit；缺真实报告时明确阻断，不能把 synthetic 单测当发布证据 |
| 生产联合复验 | 未完成 | 真实普通用户、四发布、自然周期和准确 runtime 门尚需验证 |

本表在每个阶段完成后更新，只写实际验证结果。最终报告必须列完成项、未完成项、已验证测试与未验证风险。

### 2026-09-25 候选收口与发布门禁

- 修复增量 CI 的同类漏选：Data Center 生产变更会执行 realtime consumer component；部署入口会选择 verifier、remote builder、Qlib 安装、watchdog 和发布预演验证器契约。PostgreSQL 工作流除 21 项 publication/provenance 用例外，显式运行两项 backfill control-plane 用例，并拒绝 missing、failed、error 或 skipped。
- `deploy-vps.ps1` 的后置验证由“警告后成功”改为真实非零退出；Python verifier 缺 Paramiko 时也 fail closed。部署包装器将批准的精确 SHA 传给 remote builder，若本地 HEAD 在预验收和构建之间变化，会在读取凭据或 SSH 前终止。
- 新增 `validate_release_rehearsal.py`。它只验证、不采集证据：四类报告必须绑定相同候选、交易日、完整 universe hash 和结构化 provider 身份；真实响应和隔离写入回执必须是可解析、身份一致的结构化记录并继续校验所引用原始 body；容量报告必须携带排序去重后的完整证券清单并重算 hash；每个数据集的样本必须等于由该 universe 确定性选出的 `min(50, universe_count)`；PostgreSQL JUnit 必须包含固定 23 项用例、无 skip/failure/error 和有效时间。候选回归同时查询 GitHub Actions 官方接口，核对同 SHA 成功 run、该 run 的未过期唯一 artifact、ZIP 的官方 SHA-256，以及 ZIP 内两份 JUnit 与本地报告的逐字节一致性；下载鉴权头不会转发给签名存储地址。
- synthetic 正常样例及反例用于证明 validator fail closed，不属于上线证据。独立攻击复验确认：无关 PostgreSQL 用例、单资产冒充全量 universe、浮点 `0.0` 冒充零残留均被拒绝。最终候选仍需采集真实响应/单位重放、完整容量、隔离写入回滚以及远端 CI JUnit 后才能部署。
- `collect_release_regression_evidence.py` 只从 GitHub 官方 run 采集候选回归子报告和两份原始 JUnit，并在写 success 报告前由共享 validator 重新下载、逐字节复核；来源在采集前后漂移、目录已存在或任一校验失败时只保留 blocked 结果。它不会把 provider 身份关联上下文冒充 provider 验收，另外三类报告仍须独立采集。

### 2026-09-24 首轮执行证据

- 注册表 v180 校验通过：55 units、0 violations，DATA-18 为 repository focus。
- VPS READ ONLY 快照查明原任务为 partial：requested=57、succeeded=56、failed=1、stored=11114，单位 sync_operation/fact row；published_members=0、publication_updated=false、errors=[ValueError]。56 个事实同步操作完成，最后发布操作失败；旧记录没有更细异常，不伪造具体校验原因。另有 valuation_seed_stored=5557，不能并入原 stored 口径后仍声称相同字段。
- 当前 09-24 publication 中估值 5557/5557 行、报价 600/5557 行不匹配；样本的 fetched_at/available_at 在发布后发生变化而 revision 仍为 1。日线 5557 行无失配。旧财报 80 行缺现代 fact hash，单列为历史证据不足，不把空 hash 算作新发生篡改。
- 生产决策总闸仍为 2026-08-29 设置的 blocked，reason 为 MCP audit evidence write failed during final acceptance，release_ref=3e08a3b3a7b6ccd33898e5bb2c5074300b1a4928。该历史状态需正常验收和 activation 流程解除，不能用本日审计身份续期替代。
- 阶段诊断先新增两个反例，实际 2 failed（缺 phase），实现后全文件 32 passed；新增每阶段计数、target_trade_date、fact_row 单位和运维异常日志。尚未部署，也不改写原失败记录。
- 原始脱敏只读证据：`output/recovery-readonly-evidence-2026-09-24.json`。正式归档时需绑定候选、命令和 SHA；当前仅阶段证据。
- 报价/估值发布后刷新先复现 2 failed（旧 fact hash 被改写），修复为冻结行追加 revision 后，发布/时间/候选/成员组合 30 passed（6.02 秒）。其中包含 5557 只未发布事实重刷，断言批量有界 SQL 且无大型 CASE UPDATE；这不是 PostgreSQL 实测吞吐承诺。
- `makemigrations --check --dry-run data_center` 通过。9 个主代理改动的生产 Python 文件增量 mypy 0 regression；Celery guard 94 tasks、current guard 69 surfaces、计划注册 55 units 均通过。完整债务门禁及子代理静态检查仍在运行。
- SDK-only 与 SDK/共享模块混合变更现进入 SDK 和 MCP 两组 PR 选测；选测回归 51 passed。尚未触发远程 PR CI，不能标 CI 执行完成。
- PostgreSQL 并发/更严格超时/回滚反例已加入 opt-in 套件；本机未配置专用测试数据库且 Docker 未响应，执行为 11 skipped，明确不计通过。最新冻结事实套件 5 passed（含规模及幂等）；部署前必须实际跑 PostgreSQL 测试。
- 进一步业务不变量反例：发布 count 为 True、负数、0、浮点、字符串、None 的 6 个反例先失败；现在只有严格正整数才能设置 publication_updated，整份任务测试 38 passed，增量 mypy/Ruff 通过。
- 新增 `.github/workflows/ci-publication-postgres.yml`：临时 PostgreSQL 16、11 项真实锁/回滚测试、拒绝 skipped/空集、保留 JUnit。YAML 已解析，远程 CI 尚未运行；不能把工作流存在当实际 PG 通过。
- 全量 mypy 首轮发现 R3 透传参数缺口，已反馈并修复，正在复跑。未抬高债务基线。
- 同类别待收敛：日线虽然生产抽查没有漂移，旧 upsert 路径仍可能改写发布行；财报写入保护目前重证据验证，仍需对冻结成员更新逐入口审查。正式宣称“永久消除事实改写类问题”前必须覆盖这些入口。

### 后续执行：日线同类整改

- 日线更正也复现冻结 hash 被覆盖（1 failed）；PriceBarRepository 纳入同一追加修订机制，QMT 保持对原始 revision=1 的幂等约束，0085 增加日线唯一键。冻结/候选/成员组合 27 passed，4 文件增量 mypy 0 regression，迁移无遗漏。财报同类入口仍需独立证据审查。
- 本地 Docker Desktop 已尝试启动，正在核实引擎是否可用；不得据此计 PostgreSQL 通过。

### 后续执行：真实 PostgreSQL 与迁移

- Docker 引擎不响应，未重启既有后台。通过 [PostgreSQL 官方 Windows 页面](https://www.postgresql.org/download/windows/) 链接的 EDB 便携包建立专用本地 PostgreSQL 16.15，监听 127.0.0.1:15432，仅使用独立空测试库。包 URL/大小/SHA-256 保留在 `output/pg-data18/download-evidence.json`，测试结束后由主代理停止该实例，不安装全局服务。
- 实际 PostgreSQL 套件 **12 passed、0 skipped，10.02 秒**：包括锁排斥、冻结发布保留、更严格超时、事务回滚；迁移 0085 实际执行三类唯一键和 member index 变更，旧行内容不变，存在多个修订时降级拒绝且事务不丢数据。
- `output/pg-data18/publication-postgres.xml` 为 JUnit；`output/pg-data18/evidence-summary.json` 记录测试名、JUnit SHA 和受测源码 SHA。该证据属于未提交工作树，不冒充生产候选放行或远程 PR CI 已执行。
- QMT 集成 **9 passed，305.46 秒**；原始上传 revision=1 的幂等及冲突约束保留。计划中的 PostgreSQL 未验收状态由上述实际本地证据更新，远程 CI/生产仍待验收。
- R3 首轮提交 7 项行为测试、14 项前端请求约束及增量静态检查；主代理发现逻辑账户名称、缺 account_id 的建议写入尚需真实归属证明，已要求继续带 DB 权限与真实浏览器验收，不能以普通登录状态替代账户归属。

### 后续执行：财报修订与停止后的接手复核

- 财报同类反例确认旧已发布行会被更正覆盖；现在冻结财报追加修订，继续独立验证原始来源/可用时间证据；历史查询先按知识截止时间限定再选择修订。SQLite 财报/冻结/当前候选组合 **29 passed（3.84 秒）**，5 个相关生产文件增量 mypy 0 regression。
- 真实 PostgreSQL 扩展套件 **20 passed、0 skipped（10.47 秒）**，0085 实际四类唯一键变更、旧行保留、不可无损降级保护均覆盖；财报来源验证使用明确的测试替身，不代表真实 provider 来源验收。测试准备曾遇到实例停止/端口不符及缺资产/策略表，修正后实际执行通过。CI 已扩展两份 PG 套件并拒绝少于 20 项/任何 skipped，远程 CI 未执行。
- 重新生成 `output/pg-data18/evidence-summary.json`，绑定本次 JUnit 与财报/锁/迁移源码哈希；`current_data_contracts` 纳入四类事实和财报历史知识测试，69 surfaces 校验通过。
- 三个 Luna 子代理已不在运行；R3/R4 明确因账户用量限制终止。已有改动保留，由主代理接手核验，未自动消耗重置额度或将未完成工作报为完成。
- R3 只读及账户归属组合 **9 passed（194.05 秒，含真实本地数据库归属测试）**；SDK/MCP/Task Monitor/Alpha 提示定向组合 **58 passed（29.70 秒）**。这些不能替代浏览器及生产普通用户联合验收。
- 全量类型检查又暴露 R3 执行接口 3 个新增错误。主代理新增旧版预览/审批归属反例，实际 **2 failed**，确认旧版预览漏校验、审批误用未定义变量；已移动校验到正确分支并修复参数类型，6 项定向回归通过、该文件增量 mypy 0 regression，未抬高债务基线；全量生产 mypy 债务门禁复跑 **0 errors**。
- R3 后续复核确认 Alpha 首页待执行请求曾按全局队列聚合。现已在 Decision Rhythm repository、Dashboard gateway、首页和决策链贯穿用户账户过滤；空账户返回空集，未绑定旧请求仅保留给显式系统级查询。双账户真实 SQLite ORM 探针通过，正式 HTTP 与生产普通用户联合验收仍保留在发布后 UAT。
- R3/P8 举一反三发现 Qlib 缓存未命中的普通 GET 会投递或同步执行推理、Provider fallback 会写告警、股票上下文读取会回写名称且把缺失价格改成 `0.0`。现已改为 GET/SDK/MCP 只读：缓存缺失返回稳定 `read_only_cache_miss`，推理由显式刷新或调度负责；告警写入仅允许显式 `record_alerts`；名称读取不回写，价格缺失保留 `None` 并形成可靠性阻断。
- R3 受控真实 Chromium 组件复验覆盖显式未知账户和“宏观阻断 + 空推荐”场景：未知账户不回退到首账户，空推荐的证券/账户研究链接已移到常驻首屏区域，仍保持全程只读。候选请求无法证明账户归属时执行入口 fail-closed；该证据不是生产认证 UAT。
- R4 主代理补充反例实际 1 failed：小写 `canonical_publication_stale` / `decision_runtime_blocked` / `qlib_source_data_stale` 被安全投影丢失。已限制长度并支持有界 snake_case 业务码，仍拒绝 URL/诊断原文，4 项回归通过。
- R4 补修后的 DTO 增量 mypy 0 regression；Celery 契约 94 tasks、21 exemptions、23 governed files 通过；本轮核心修改 Black/Ruff 通过。
- Task Monitor API、Signal API/Interface、TUI Workbench、Terminal Agent、内部 SSL 和 SDK Client 组合 **435 passed（484.49 秒）**；Web 迁移 inventory 196 templates / 117 route pages 通过。执行权限补测与财报 PostgreSQL 证据另列，不能误称这 435 项包含全部新增路径。
- 本轮本地 PostgreSQL 实例已正常停止；未安装全局服务，未操作生产数据库。
- S6 真实 provider 50 只生产预演门仍未落地；正式发布、决策运行时正常激活、Alpha 当前日完整链路、普通用户浏览器联合复验均仍未完成。生产由既有集成任务协调，本任务未提交、合并或部署。

### 后续执行：交易日历、工作台与 SDK 错误链

- 真实日期反例确认 weekday-only 算法会把 2026-09-25 休市日和国庆休市区间当成交易日，导致 9 月 24 日完整行情被误判过期。行情时效、全市场任务、预演、诊断、市场温度计、Alpha 日期和缓存补齐已统一到 provider-backed 日历解析；日历不可用时 fail closed。
- 首轮修复又被截断响应反例推翻：仅一条 open date 曾被服务层错误包装成完整 coverage。现由 Tushare 适配器读取请求区间内每个自然日的 `cal_date/is_open`，严格拒绝缺尾、缺中间、非法状态和重复冲突；路由层只转发来源签发的 coverage/source/observed_at，不能根据请求参数制造覆盖。完整链复验 6/6 通过，包含 pandas 数值 `0/1`。
- 工作台受控 Chromium 复验覆盖慢投顾、账户 17→18 切换、已有阻断推荐、推荐查询失败及点击重试。常驻研究入口不再被状态 banner 覆盖；失败重试仅增加一次同账户 GET，三场景无写请求和 JS 错误。生产普通用户认证 UAT 仍须绑定部署候选执行。
- SDK 真实 loopback 复现两次 503 后 urllib3 `RetryError` 丢失最终响应。重试现使用 `raise_on_status=False`，耗尽后由 SDK 解析最后一份 JSON；独立复验保留 status=503、`decision_runtime_blocked` 和完整阻断字段。已连接的旧 MCP 进程仍可能缓存旧 SDK，部署重启后需再次验证。
