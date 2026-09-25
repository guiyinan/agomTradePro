# 生产恢复与系统性防回归整改计划（2026-09-24）

状态：执行中。用户已要求主代理带领 GPT-6 Luna（max）子代理完成本计划，并设置持续执行 goal。
当前集成基线：`dev/next-development@9c77c51182c49613699fe916a4ad0d82c7a6cd2d`；该精确 SHA 已部署生产，当前工作树中的后续修复尚未提交或部署，不能把本地改动当作生产版本。
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
| S6 | 第十一次真实演练完整成功，部署器修复待最终 SHA 重跑 | `66615517e3` 的同 SHA CI 和 25 项 PostgreSQL 契约全绿；全新候选完整通过构建、镜像身份、真实 provider 探针、原始响应重放、5,569 只全市场容量、隔离 PostgreSQL 写入回滚、官方 CI 证据、不可变 bundle 和最终 validator。独立下载后复算 bundle tree、manifest、GitHub run 与四类报告也通过，临时凭据和隔离 PostgreSQL 已清理。首次部署在任何生产切换前因 prebuilt 校验 payload 的 Python 引号错误阻断；修复属于部署代码变更，必须以最终新 SHA 重跑全部 CI 和整套真实 S6，不能用旧候选绕过 |
| 生产联合复验 | 部署前阻断 | prebuilt 校验 payload quoting 修复后待最终候选部署；真实普通用户、四发布、自然周期和准确 runtime 门尚需验证 |

本表在每个阶段完成后更新，只写实际验证结果。最终报告必须列完成项、未完成项、已验证测试与未验证风险。

### 2026-09-25 候选收口与发布门禁

- 修复增量 CI 的同类漏选：Data Center 生产变更会执行 realtime consumer component；部署入口会选择 verifier、remote builder、Qlib 安装、watchdog 和发布预演验证器契约。PostgreSQL 工作流除 21 项 publication/provenance 用例外，显式运行两项 backfill control-plane 用例，并拒绝 missing、failed、error 或 skipped。
- `deploy-vps.ps1` 的后置验证由“警告后成功”改为真实非零退出；Python verifier 缺 Paramiko 时也 fail closed。部署包装器将批准的精确 SHA 传给 remote builder，若本地 HEAD 在预验收和构建之间变化，会在读取凭据或 SSH 前终止。
- 新增 `validate_release_rehearsal.py`。它只验证、不采集证据：四类报告必须绑定相同候选、精确 Docker image ID、交易日、完整注册 universe hash 和结构化 provider 身份；真实响应和隔离写入回执必须是可解析、身份一致的结构化记录并继续校验所引用原始 body。探针与容量预演先用目标日估值及 active 发布策略冻结 eligible/excluded 范围，再从 eligible 范围确定性选取样本并要求行情完整；容量回执还按 PostgreSQL 全集群连接口径重算资源余量。PostgreSQL JUnit 必须包含固定 25 项用例、无 skip/failure/error 和有效时间，其中真实 PostgreSQL endpoint 用例拒绝带 CIDR 前缀的地址。候选回归同时查询 GitHub Actions 官方接口，核对同 SHA 成功 run、该 run 的未过期唯一 artifact、ZIP 的官方 SHA-256，以及 ZIP 内两份 JUnit 与本地报告的逐字节一致性；下载鉴权头不会转发给签名存储地址。部署采用预构建镜像复用，预演通过后的 image ID、OCI revision 和证据 manifest 摘要在服务切换前再次核对。
- synthetic 正常样例及反例用于证明 validator fail closed，不属于上线证据。独立攻击复验确认：无关 PostgreSQL 用例、单资产冒充全量 universe、浮点 `0.0` 冒充零残留均被拒绝。最终候选仍需采集真实响应/单位重放、完整容量、隔离写入回滚以及远端 CI JUnit 后才能部署。
- `collect_release_regression_evidence.py` 只从 GitHub 官方 run 采集候选回归子报告和两份原始 JUnit，并在写 success 报告前由共享 validator 重新下载、逐字节复核；来源在采集前后漂移、目录已存在或任一校验失败时只保留 blocked 结果。它不会把 provider 身份关联上下文冒充 provider 验收，另外三类报告仍须独立采集。
- provider 响应预演已补全为两阶段：在线探针只读并将每个 quote/valuation 响应正文写入独占目录，正文回执不包含 token、请求体、查询参数或请求头；离线命令按输入 SHA 重放全部留存响应，验证有效、缺失、截断、陈旧、重复、单位错误和后续事实更新七类场景。成功报告还会逐资产比较在线事实与重放事实，区分 transport received 与 normalization completed 时钟；任一未列入报告的响应、正文漂移、实时事实不一致或源树变化均阻断。
- 新增 `run_release_rehearsal.py` 单入口：工作树必须 clean，证据输出必须位于 checkout 外；同一预构建镜像依次运行七个阶段并在每阶段复核 candidate SHA、image ID、交易日、universe 与 provider 身份。launcher 只生成 `deployable=false` 的 evidence handoff，不冒充 validator 授权；底层部署入口在 SSH 前独立重跑 validator，重新校验 bundle tree、manifest、同 SHA CI 与全部身份，成功后才继续，防止同形 JSON 或验证后替换绕过门禁。
- 同类调用者复核发现带响应证据的 dataframe wrapper 曾只实现 `empty/to_dict`，历史行情与模型数据还会使用长度、列、掩码、复制、排序和合并。wrapper 现在透明代理公共 DataFrame 操作，并由行情、历史、交易日历和模型数据组合回归覆盖，避免真实直连返回在探针外退化。
- 审计授权续期请求路径已写入 VPS Compose 的 Web/Worker 环境，并使用既有持久化 `var_data` 卷。版本替换后缺请求会明确报告 `renewal_request_not_found`；该修复只恢复续期通道，不自动制造审批材料或解除决策阻断。
- `ff4d81a0c` 首次真实 S6 在 VPS 运行：候选镜像 `sha256:c2fad4…cafdc` 构建成功且未部署，provider 探针完成运行后因 Linux evidence bind mount 不可写而无法生成 `probe.json`，launcher 返回 `provider_probe / S6_STAGE_COMMAND_FAILED`。该失败没有被改写为通过；修复同时把阶段目录从 world-writable 方案收紧为候选主组 `2770`、结束 `0750`，并补充失败恢复、symlink/inode 替换反例。新 provider 身份由实际 `request_mode/http_url/api_endpoint/provider/source/active/priority/name` 与客户端版本派生，白名单错误码可在命令证据中安全透传；动态健康指标和密钥不进入身份摘要。
- `84334bcdbf` 第四次真实 S6 证明全范围估值响应与冻结样本回放修复有效：真实响应重放和 5,569 只容量阶段均成功。随后全新隔离 PostgreSQL 缺 runtime catalog，稳定阻断为 `REHEARSAL_WRITE_CATALOG_UNAVAILABLE`。本地一次性 PostgreSQL 16 正向组件验证从空 catalog 经标准初始化后完成 4 条生产路径写入、读回和防篡改检查，业务行回滚为 0，治理 catalog 持久保留；9 项 scope、迁移和 catalog 负向场景也通过。初始化前 preflight 同时绑定候选镜像、迁移完成状态、预期数据库名和实际服务端 endpoint，防止误写同名生产数据库。
- `3faa1e2248` 第五次真实 S6 的前五阶段再次通过，隔离写入在任何 catalog 或业务写入前 fail closed。后续一次诊断误把临时 env 文件纳入工具输出，涉及生产数据加密 key、应用管理员口令、provider token 和一次性 PostgreSQL URL/密码；未在仓库落盘。远端临时 env、密码文件和一次性 PostgreSQL 容器已删除，候选镜像与非敏感失败证据保留用于审计。可轮换的管理员口令和 provider token 必须走凭据签发流程；生产数据加密 key 在没有重加密与回滚方案前不得直接替换。随后改用只输出布尔匹配结果的一次性诊断，确认根因是 `inet_server_addr()::text` 的 CIDR 掩码导致同一 Docker endpoint 被误判。
- `c2d5422e8a` 第六、七次真实 S6 均使用全新目录、镜像、探针和隔离 PostgreSQL，六个部署前阶段连续通过。首次 CI 证据排查还发现远端进程默认没有 GitHub token；后续操作辅助以 `0600` 临时文件只向 collector 进程注入 token，并在退出时删除，独立采集验证成功。正式 S6 仍在同一位置失败，静态复核确认实际先发根因是 launcher 预建 `github-ci-evidence`，而 collector 为防覆盖明确要求该目录不存在。目录所有权现统一归 collector；不得用手工生成的证据代替完整重跑。
- `53f506fe57` 第八次真实 S6 首次越过官方 CI 证据采集，随后在不可变 bundle 创建前 fail closed。四类输入对比确认前三类报告的候选、镜像、日期、universe 和 provider 摘要一致；CI 报告包含同一规范化 provider 身份数组却遗漏对应摘要，导致 bundler 正确拒绝。修复复用 collector 已返回的校验摘要，不放宽 bundler 或最终 validator 的身份门禁；失败运行的临时凭据和隔离 PostgreSQL 已清理。
- `1ea5641a4b` 第九次真实 S6 成功创建完整 bundle，最终 validator 在读取真实四类报告后阻断。只读重放确认稳定码为 `REHEARSAL_PROVIDER_IDENTITY_INVALID`；真实 capacity 与 isolated 报告只有已冻结的 `provider_identities_sha256`，而 synthetic validator fixture 曾给四类报告全部添加身份数组，掩盖了生产契约差异。修复后测试 fixture 与真实生产形态一致，并覆盖四类顶层摘要必填、replay/CI 完整数组必填和摘要重算。launcher 另以严格的二字段 blocked JSON 解析 validator 稳定码，含附加诊断字段或多个错误码的输出仍降级为通用安全错误。
- `24da5c943` 第十次真实 S6 证明身份形态与稳定码透传修复有效，最终 validator 随后在单位合同检查 fail closed。冻结 bundle 的只读复核确认报价合同与单位重放均使用系统已规范化的英文 canonical 名称和正确倍率，只有 validator 的 synthetic 常量仍保留旧中文别名。修复只统一单位名称，不改变数值倍率、原始响应、已发布事实或估值合同；失败运行的临时凭据和隔离 PostgreSQL 已清理。随后增加报价旧中文别名、报价及估值五字段任一合同倍率漂移、微小 observation 倍率漂移的 fail-closed 回归；单位倍率按已定义的整数转换系数精确匹配。聚焦 validator suite 76 项通过，Ruff、Black、isort 和增量 mypy 通过；新的候选 SHA 仍须跑完整 CI 与全新 S6。
- `66615517e3` 第十一次真实 S6 首次完整成功，九个阶段全部完成且 `success_evidence/error_code=null`。候选镜像 `sha256:5fb0f6c…f8a3`、release tag `20260925190720`、bundle tree `d5501f57…a800` 与 GitHub run `36163499730` 绑定同一提交；本地独立 validator 重放再次成功。随后正式部署入口在 SSH 和镜像定位后、生产 mutation 前因生成的 `python -c` payload 将 Docker label 模板双引号错误嵌入双引号字符串而 `SyntaxError`。修复把 payload 收敛为有类型、有 docstring 的单一生成函数，并直接编译测试生成结果；生产服务仍保持旧版本。

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

### 后续执行：readiness 决策状态与全市场预览规模复验（2026-09-26）

- 生产复验报告 `/api/ready/` 在 decision runtime 为 `blocked` 时仍返回 `status=ok`、HTTP 200。根因是基础 readiness 聚合只计算数据库/Redis/Celery 的服务可用性，既未把持久决策运行时放入 checks，也没有把已有的决策数据 warning 映射到总体状态；`/api/health/` 则是独立 liveness 探针。
- 已在 readiness checks 中显式加入 `decision_runtime`，响应新增 `service_status` 与 `decision_availability`。决策受阻时状态为 `degraded`，载明 `must_not_use_for_decision=true` 和稳定阻断码；一般服务仍为 ready 并返回 HTTP 200。基础 `/api/health/` 不读取运行时门，仍只报告进程存活。blocked/available 两条接口契约及 liveness 独立性已回归。
- 生产 5,557 只证券 dry-run 超过 10 分钟的代码根因之一为报价候选 N+1：先批量读最新报价，再对每只报价单独查询 ORM 行以生成 Publication fact reference。现由共享 `_latest_quote_rows` 查询同时服务普通最新报价和 current publication 候选，直接基于相同排序与最新 revision SQL 行构造引用；覆盖、事实 hash、原子发布和 execute 审计预检保持原样。
- 新增命令级 5,557 证券组件测试：调用真实 `rebuild_active_a_share_core_publications` dry-run，quote/price/valuation 各选出 5,557 个候选，financial 为空时仍准确 `ready=false`；数据库读取不超过 8 条 SQL，且断言没有 INSERT/UPDATE/DELETE/REPLACE。格式化后的 readiness 与发布聚焦组合 **49 passed（24.88 秒）**；SQLite 首轮新建测试库应用完整迁移耗时 284 秒，后续使用同一 disposable DB 复验，不将建库时间误报为查询耗时。Ruff、Black、isort、diff check 通过；增量 mypy（3 个生产文件，0 regression）和全量 debt ceiling（0 errors in 0 files）通过。
- 剩余风险：5,557 规模测试证明命令编排、SQL 查询预算及 dry-run 零写入，不代表生产 PostgreSQL 的 P95/锁竞争/内存和真实 provider wall-clock 预算；必须在生产预演或同规格隔离 PostgreSQL 复测时另记实测时长和数据库查询数。此测试未提供财报事实，维持业务阻断；不能据其声称正式四类 Publication 已恢复。

### 2026-09-26 生产重跑根因、修复候选与剩余执行矩阵

#### 原任务与本次重跑证据

- 原任务 `0d739398-3052-4378-bed1-0b99405ebfdf` 的持久业务结果为 `requested=57 / succeeded=56 / failed=1 / stored=11114`，`publication_updated=false`、`published_members=0`；另有预取估值 `valuation_seed_stored=5557`，统计单位不同，不能合并后伪装为全成功。旧结果只保留 `ValueError`，无法反推更细异常，因此根因结论仅限定为“同步完成后、正式发布阶段失败”。
- 生产已部署并核验精确 SHA `9c77c51182c49613699fe916a4ad0d82c7a6cd2d`，镜像 `sha256:bed0fa3badbc3e3c38bda192cb662ef84e24b28b8e072405f9d0541e4d55a743`，release `20260925201025`。审计 authority 已按正常 V5.3 receipt/evidence 与 V3 authority 链恢复，未编辑历史 receipt、未关闭保护开关。
- 本次全市场任务 `e9941169-d5c8-4f04-901f-a9579d9c7939` 于 2026-09-25 19:28:46–20:27:06 UTC 运行，在 55 个 100 只批次及末批 57 只的报价/估值写入完成后，进入估值 current publication 候选查询；该 PostgreSQL 查询约 8 分钟后触发任务固定的 3,500 秒软时限。Celery 最终只留下 `SoftTimeLimitExceeded()` 和 FAILURE，没有业务 outcome、阶段或写入统计。这同时复现用户第 1、9 项。
- 当前实现用相关子查询在完整历史事实表上逐资产寻找最新自然键修订；5,557 只证券的 SQLite SQL 数量测试没有暴露 PostgreSQL 查询计划退化。修复候选改为 PostgreSQL CTE：先按资产求最大观测日，再在该有界横截面选最新修订，最后每资产排序取一条；SQLite 保留便携 ORM 路径。
- 任务捕获 `SoftTimeLimitExceeded`，返回 `outcome=failed`、实际 `requested/succeeded/failed/stored`、`phase`、稳定码 `MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED`、`publication_updated=false`、`must_not_use_for_decision=true` 和本次 `publication_run_id`。成功路径把正式 Publication 的 id/hash/run_id 合并进同一任务结果，支持结果与发布内容对账。
- 本次实际交易范围为 5,557，只排除 12 只 provider 明确返回当日成交量为 0 的停牌证券：`000016.SZ, 002731.SZ, 002860.SZ, 300082.SZ, 300096.SZ, 301139.SZ, 601059.SH, 601198.SH, 601238.SH, 603400.SH, 605303.SH, 688496.SH`。不能为凑 5,569 人工制造 09-24 日线/估值；正式结果必须把排除代码、原因、目标日和 per-security 阻断与 run_id 一并保留。

#### 十项状态、下一退出条件和剩余风险

| 用户项 | 当前根因 / 改动证据 | 下一退出条件 | 剩余风险 |
| --- | --- | --- | --- |
| 1 全市场刷新 | 原任务发布阶段失败；本次重跑定位到估值候选 SQL 触发软时限。已优化查询并规范超时业务结果 | 最终 SHA 部署后重跑，Task Monitor 与数据库逐项对账四计数、阶段、发布状态和 run_id | 新 SQL 尚未在生产 PostgreSQL 实测执行计划与 wall-clock |
| 2 正式发布 | 旧 quote/price/valuation publication 均为 5,557 成员；财报仍为历史部分发布。财报批任务 50/50 失败的首因是 provider 配置使用裸 HTTP；改走现有 HTTPS gateway 后真实 probe 得到 26 条事实，但 `available_at/announced_at` 仍缺失，`financial_source_time_match_contracts` 仍待 owner approval。成功结果此前未带发布 id/hash | 用同一 run_id 重建三类合格发布并核对策略版本、来源时间、成员 hash；财报必须取得 provider-native exact source-time 并由获批 match contract 验证 | 12 只停牌例外需保持可审计；严禁用 fetched_at 推断公告时间或把待审批合同自动激活 |
| 3 决策总阻断 | 历史 MCP 审计失败门与行情 freshness 是两条链；authority 已正常恢复，readiness 曾错误显示 ok | 四类正常 activation preflight 全通过后才 CAS 激活；Regime/估值接口再验业务结果 | Regime 另有 PMI/CPI 数据不足；不能误归因行情或总闸 |
| 4 Alpha | 生产评分日已到 2026-09-24，workspace default 有 1,831 候选；自然调度此前缺失，现补工作日 17:30 显式推理 | 部署后核对日线准备、调度回执、账户 scope、缓存日期/hash 和候选更新；真实自然周期留证 | 页面仍可能受 quote/financial/valuation 阻断；手动成功不替代自然周期 |
| 5 信号契约 | API/SDK/MCP 的 offset、过滤和空集契约已形成候选回归 | 部署重启新 MCP 会话，验证默认、offset=0、非零分页、状态、证券和空集 | 旧长连接进程可能缓存旧 schema/SDK |
| 6 MCP 信息 | 业务 503、政策 PX/unclassified/manual review 的安全透传已有候选测试 | 生产分别复验 runtime blocked、网络失败、政策待审及数据时间 | 上游 Regime 数据不足须保持独立稳定码 |
| 7 候选详情 | 本地受控 Chromium 已覆盖账户切换、宏观阻断下研究详情、慢请求与重试 | 生产普通用户从山东黄金进入正确账户详情，记录冷/热时延和超时恢复 | 尚无可用于生产的普通用户验收凭据 |
| 8 只读零写入 | GET/MCP 缓存 miss、workspace 浏览和研究读取已改为只读；刷新留给显式动作/调度 | 生产前后对账重复 GET/MCP 的任务、建议、历史行数；显式 POST 验权限 | provider alert 等旁路写入需在联合 UAT 继续观察 |
| 9 进度可观测 | 本次软超时证明旧页面只得技术状态；候选结果已保留阶段、计数和稳定码，状态 DTO 已区分本次/最近完成 | 以真实重跑检查运行中、失败、成功三态及用户/运维字段边界 | 旧历史任务无法补造当时不存在的精细 phase |
| 10 文案与时间 | readiness 已拆成 service status 与 decision availability；缺价格保留 None，原始/正式时间分离 | 生产普通用户页面验“不可用原因/可做动作/处理角色”、北京时间和缺失值 | `/api/ready/` 保持 HTTP 200 是负载均衡契约，必须以 body 的 degraded/decision 字段解释 |

#### 五类永久整改和生产预演状态

| 类别 | 已形成候选 | 本轮必须补齐的生产证据 |
| --- | --- | --- |
| S1 真实 provider 契约 | 真实响应身份、单位、源时间及 replay 进入 S6 bundle | 最终新 SHA 重新执行完整 S6；旧 SHA 报告不能授权新查询实现 |
| S2 业务不变量 | 软超时业务统计、发布 run_id/id/hash、一致范围、只读零写入均有反例 | 生产任务结果与 publication/member/事实逐项对账 |
| S3 时间维度 | provider-backed 交易日历、来源观测/可用/获取时间分离 | 休市、停牌、自然调度和真实周期回执 |
| S4 规模测算 | 5,557 命令组件限制为 8 条读取 SQL、零写入；查询算法消除逐历史相关扫描 | PostgreSQL `EXPLAIN`、实际 wall-clock、锁/内存和 3,500 秒余量 |
| S5 component PR CI | 当前数据、Celery、SDK/MCP、PostgreSQL publication 选择器已纳管 | 最终提交同 SHA 的远端 CI 全绿且零 skipped |
| S6 生产预演 | 旧候选曾完整通过 50 只真实 provider、5,569 容量、隔离 PG 写入回滚和不可变 bundle | 查询/部署脚本变更后必须生成全新候选并完整重跑，不复用旧放行 |

#### 本轮本地验证与部署前停止线

- 任务、发布仓储、current rebuild、5,557 规模、readiness/TUI 聚焦组合：**81 passed（315.64 秒）**。
- 入口治理重建：1,261 项，`candidate-review=0`；相关治理和健康/部署组合：**109 passed（500.16 秒）**。
- current-data guard：**70 surfaces**；Celery guard：**94 tasks / 21 exemptions / 24 files**。
- 候选尚未提交、未跑最终增量 mypy/债务门禁、未绑定远端 CI/S6、未部署，因此以上均不得写成生产恢复。部署前还必须验证自动回滚确实恢复旧服务和内部 `/api/health/`；首次新部署曾出现 transient `check --deploy` 失败后自动回滚未完整拉起服务，候选已加入重试和回滚健康核验。
- 生产 `/api/tui/operator/governance-queue/` 另复现交易日历未来 coverage 缺失导致 500；候选把它转换为 `readiness_calendar_coverage_unavailable` 的结构化 blocked 结果，保留中文原因和 `must_not_use_for_decision=true`，部署后需复验不再 500。
