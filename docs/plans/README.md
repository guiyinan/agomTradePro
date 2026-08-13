# 活跃计划索引

> 更新日期：2026-08-13
> 本目录只保留仍需开发、真实数据、生产验收或外部依赖闭环的计划。已完成的实施计划、阶段记录、复盘和历史证据统一放在 [`../archive/plans/`](../archive/plans/)；归档记录见 [`../archive/ARCHIVE_INDEX.md`](../archive/ARCHIVE_INDEX.md)。

## 维护规则

- `docs/plans/`：存在未完成交付、真实数据、生产切换、外部验收或明确后续批次。
- `docs/archive/plans/`：仓库范围已实现，或阶段已经验收/被新计划取代；归档文档仅作历史证据，不代表当前运行状态。
- “代码已完成但生产未验收”仍属于活跃计划，不能仅因本地测试通过而归档。
- 归档时必须同步修正 `docs/INDEX.md` 和活跃计划中的引用，不复制第二份文档。

## 当前主跟踪入口

### 策略研究与证据治理

- [`evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md`](evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md)
- [`strategy-research-capability-completion-audit-2026-08-05.md`](strategy-research-capability-completion-audit-2026-08-05.md)
- [`strategy-research-capability-roadmap-execution-2026-08-05.md`](strategy-research-capability-roadmap-execution-2026-08-05.md)
- [`strategy-research-production-data-closure-tracking-memo-2026-08-12.md`](strategy-research-production-data-closure-tracking-memo-2026-08-12.md)
- [`strategy-research-r1-r2-readiness-plan-2026-08-05.md`](strategy-research-r1-r2-readiness-plan-2026-08-05.md)
- [`macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md`](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md)
- [`strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md`](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md)

### 数据与生产可靠性

- [`data-center-canonical-architecture-refactor-2026-08-02.md`](data-center-canonical-architecture-refactor-2026-08-02.md)
- [`production-data-reliability-full-remediation-2026-08-01.md`](production-data-reliability-full-remediation-2026-08-01.md)
- [`critical-reliability-test-closure-2026-07-22.md`](critical-reliability-test-closure-2026-07-22.md)
- [`uat-remediation-2026-07-20.md`](uat-remediation-2026-07-20.md)

### 产品界面与运行时

- [`web-to-tui-migration-plan-2026-07-25.md`](web-to-tui-migration-plan-2026-07-25.md) 与 [`web-to-tui-migration-matrix-2026-07-25.csv`](web-to-tui-migration-matrix-2026-07-25.csv)
- [`web-to-tui-m5-readiness-2026-07-27.md`](web-to-tui-m5-readiness-2026-07-27.md)
- [`ai-native/README.md`](ai-native/README.md)

### 外部环境或真实接入阻断

- [`qmt-live-trading-bridge-plan.md`](qmt-live-trading-bridge-plan.md)
- [`macro-sizing-multiplier-outsourcing-2026-03-31.md`](macro-sizing-multiplier-outsourcing-2026-03-31.md)

## 未完成项执行期（重要到次要）

| 期次 | 优先级 | 主线 | 退出条件 |
|------|--------|------|----------|
| 第一期 | P0 | 决策证据硬门禁、策略研究生产数据、Data Center canonical 与可靠性整改 | 决策链不再消费无证据或不新鲜数据，机器门禁和生产数据证据齐全 |
| 第二期 | P0 | Web → TUI M5 readiness、生产 preflight、浏览器 UAT、回滚演练与 route closure | cutover、UAT、回滚和路由关闭均取得最终签字或可复验证据 |
| 第三期 | P1 | AI-Native 人工 UAT/release gate、首页聊天复用前端自动化与浏览器验收 | 任务书验收表、人工签字、自动化资产和发布门禁全部闭环 |
| 外部阻断线 | P2 | QMT 实盘桥接、宏观 sizing multiplier 真实接入 | 外部环境、真实数据和生产接入证据到位后再转入完成验收 |

同一期内先处理会阻断投资决策正确性和生产安全的项目；仅有代码或本地测试、但缺少任务书要求的最终验收证明时，继续保留在活跃目录。

## 分阶段执行记录

| 日期 | 期次 | 阶段 | 完成情况 | 后续 |
|------|------|------|----------|------|
| 2026-08-12 | 基线 | 归档与排期 | 已在 `dev/plan-closure-by-priority` 创建基线提交 `919a9cea7` | 按本表期次继续独立提交 |
| 2026-08-12 | 第一期 P0 | Evidence M1 Domain 首批 | 统一分类、ArtifactRef、Track Record、Envelope、权限交集和 fail-closed 传播已实现；canonical hash、非有限 Decimal 和有效期防线已加固；纯 Domain `19 passed`，standalone strict mypy `0 errors` | 做 M1 persistence、API、审批激活和 adapters |
| 2026-08-12 | 第一期 P0 | Evidence M0 owner/freeze | ADR-0007 owner/接口矩阵已接受；54 个 HTTP、15 个 SDK、25 个发布态 TUI 决策 action、23 个 TUI mutation/AI/admin action 与 32 个 MCP 仓位相关写能力被机器门禁精确冻结，发布图 SHA 漂移也会阻断；聚合验证 `19 passed` | 补输出、raw/governed MCP 与旧 Transition Plan 语义分类，再推进 M1 持久化 |
| 2026-08-12 | 第一期 P0 | Evidence M0 输出分类首批 | 41 个高风险输出（其中 11 个直接影响仓位）被精确冻结；全部如实标记为 legacy boolean/ungated 或 research-only，机器门禁已建立 | 扩展 R1–R8、动态 payload、raw/governed MCP，并逐项接入 Evidence |
| 2026-08-12 | 第一期 P0 | Evidence M1 persistence 首批 | schema-only/zero-seed 的 Operator Spec、Track Record、Envelope append-only ledger，strict codec、公共 exact/PIT reader 和私有幂等 append store 已实现；内存数据库 `8 passed` | 补标准 pytest-django/PostgreSQL 并发验证、审批激活和各 App adapters |
| 2026-08-12 | 第一期 P0 | Evidence M1 exact read API 首批 | Application port/facade 与三个 staff-only detail endpoint 已实现；强制 identity/version/hash/PIT，未来 cutoff 双层拒绝，写方法 405；隔离 Django/DRF `18 passed` | 定义真实用户/租户 scope 后再做 owner-scoped 授权；继续审批激活和 adapters |
| 2026-08-12 | 第一期 P0 | Evidence M1 Operator Spec lifecycle 首批 | ID-only activation、可信 definition provider/Risk Center approval port、双读防漂移、原子 receipt+activation ledger 与完整 supersession replay 已实现；DB 约束阻断双 root/双 successor；纯测试 `11 passed`、隔离仓储 `3 passed` | 实现真实 Risk Center provider/composition，补 PostgreSQL 并发验证和各 App adapters |
| 2026-08-12 | 第一期 P0 | Evidence M0 CI wiring | 决策写面冻结与 Evidence 输出清单两条机器守卫已接入 consistency-check workflow，并纳入 governance wiring 自检 | 继续扩展输出分类与统一 Evidence adapters |
| 2026-08-12 | 第一期 P0 | Evidence M1 summary contract | 紧凑 `EvidenceSummaryDTO` 已固定 hashes/分类/权限/blockers/有效期，并区分 Track Record `not_required/unavailable/empty/available`；纯测试 `5 passed` | 接入各 App 输出 DTO 与 TUI Evidence Strip |
| 2026-08-13 | 第一期 P0 | Evidence M1 Risk approval provider 首批 | Risk Center 专用 immutable subject/approval ledger、human staff 非自审批、server clock、exact/PIT selector、tamper/ORM mutation 防线已实现；纯测试 `10 passed`、隔离 component `6 passed` | 补 Research↔Risk composition、生产人工审核入口和 PostgreSQL 并发验证 |
| 2026-08-13 | 第一期 P0 | Evidence M1 Research↔Risk composition | Research 经 Risk Center Application facade 精确读取审批，二次校验 owner/capability/definition/supersession，并以 approval record hash 封存外部真源；纯单元 `3 passed` | 补 Risk 人工 subject/审批入口、PostgreSQL 并发验证和各 App adapters |
| 2026-08-13 | 第一期 P0 | Evidence M1 Data Center legacy adapter 首批 | `QuoteResponse` 已转成 content-bound legacy Envelope 与统一 summary；精确重建阻断伪造 spec/权限/lineage，始终 `legacy_unverified + DISPLAY_ONLY`；聚合纯测试 `19 passed` | 补真实 Operator Spec/持久化/consumer 接线，并逐项迁移其余 40 个输出 |
| 2026-08-13 | 第一期 P0 | Evidence M1 人工 subject/审批写入面 | ID-only 注册/审批、Research 可信 definition、server-auth staff actor、CSRF/session/staff/POST-only 与两人审批已实现；纯 Application `13 passed`，架构扫描 0 违规 | 完整项目 DRF/component 未在当前依赖环境验证；补 PostgreSQL 并发、owner scope 与生产人工记录 |
| 2026-08-13 | 第一期 P0 | Evidence M1 Broker approval legacy adapter | `OrderApprovalSnapshot` 全字段复用 approval digest 做 content-bound legacy Envelope；严格 expiry/Decimal/金额/JSON/source IDs，恒为 display-only 且不接入 Broker 授权；聚合 `22 passed` | 这不是正式 Evidence 或执行许可；补真实 Operator Spec/持久化/consumer，并继续直接仓位输出 adapters |
| 2026-08-13 | 第一期 P0 | Evidence M0 Transition Plan internal writer freeze | 修正为 6 个 legacy（含 plan-linked approval status 旁路）与 4 个 canonical writer；canonical 模式统一阻断 legacy plan mutation，approve/reject 稳定返回 409，freeze `8 passed` | 默认开关仍关闭；先补同表 schema family 隔离和 cross-family 阻断，再迁移完整 generate/update/approval 工作流 |
| 2026-08-13 | 第一期 P0 | Evidence M0 Transition Plan 同表 family 隔离 | nullable schema-only family 字段；新 legacy/canonical 写入显式分类，双方跨 family decode/write/approve 均失败关闭；聚合纯测试 `16 passed`，架构 `207 edges / 0 cycles` | 补完整 Django migration/repository component、存量分类审计与 PostgreSQL 并发；默认开关仍关闭 |
| 2026-08-13 | 第一期 P0 | Evidence M0 Broker 动态输出冻结 | AST 精确冻结 8 个 `BrokerExecutionQueryService` dict 查询方法及其 8 个 GET 发布入口；新增、删除或 symbol 漂移均阻断，专属 `8 passed` | 这只是迁移分母；补 typed contract、Envelope/summary adapter、consumer 与执行硬闸重验，并盘点其余动态输出 |
| 2026-08-13 | 第一期 P0 | Evidence M0 R1–R6 输出分母扩展 | 补冻结 13 个 R1–R6 research-only 结果与 2 个 internal presenter；显式/直接仓位/marker/dynamic 分母为 `54/11/45/18`，专属 `9 passed` | 只完成分类冻结；补 R7/R8、mixed/variant schema、MCP 语义与正式 Evidence adapters/consumer binding |
| 2026-08-13 | 第一期 P0 | Evidence M0 MCP P0 输出语义冻结 | 精确冻结 11 个 tagged read、6 个 Broker native 与 Terminal read bridge；published 闭包 `430/408`，`raw_debug=430`、`evidence_binding=0`，integrated=`0`；专属 `6 passed` | Terminal result bridge 已另批暂停；继续迁移 Broker/tagged reads，并登记其余 28 个 marker 高风险面 |
| 2026-08-13 | 第一期 P0 | Evidence M0 Terminal MCP read kill switch | result bridge manifest 禁用且 handler 在 POST 前稳定阻断，coverage 不再把 disabled bridge 误报可达；408 个未绑定 read action 全部 blocked，普通 TUI/两张 graph 不变；聚合 `12 passed, 3 skipped` | 完成 metadata binding、runtime summary exact 校验与 MCP 白名单投影后才能恢复；当前 integrated 仍为 0 |
| 2026-08-13 | 第一期 P0 | Evidence M0 Broker MCP read kill switch | 禁用全部 6 个 Broker native read：4 个决策/执行发布面、存在 heartbeat freshness 假阳性的 connection，以及可泄漏任意 before/after 的 audit；P0 MCP disabled=`7`、integrated=`0` | 补 typed contract/summary/runtime binding；connection 增 freshness/blocker，audit 动态字段白名单后逐项恢复 |
| 2026-08-13 | 第一期 P0 | Evidence M1 Strategy DecisionResult legacy adapter | Strategy 决策 action/reason/有效期/confidence 已绑定 content hash，恒为 `legacy_unverified + display_only + must_not_execute`；聚合 `28 passed`、架构 0 违规 | 未接 production consumer；补 Operator Spec/持久化/硬闸。11 个 tagged MCP read 的暂停需用户明确授权 |
| 2026-08-13 | 第一期 P0 | Evidence M0 R7–R8 输出分母 | 新增 R7 结果/监控/lifecycle 与 R8 report/assembly/run/canonical snapshot/execution feedback 8 面，精确扩展既有合同；分母为 `62/11/53/18`，聚合 `39 passed` | 分母冻结不等于 Evidence；补 mixed/variant、其余动态面及 R7/R8 Operator Spec/Envelope/consumer |
| 2026-08-13 | 第一期 P0 | Evidence M1 Strategy OrderIntent legacy adapter | 完整 OrderIntent 顶层、Decision/Sizing/Risk 字段以 Decimal/aware time canonical hash 绑定，状态变化即使时间未刷新也产生新版本；恒为 display-only/must_not_execute；聚合 `46 passed` | 未接执行 consumer/正式 Operator Spec/持久化硬闸；有损 `OrderIntentResponseDTO` 仍未集成，旧直提交流程未改变 |
| 2026-08-13 | 第一期 P0 | Equity research snapshot 四入口收口 | 将 identity/quote/history/valuation/financial/news/flow 与严格 readiness 的归并迁入 Equity Application；新增 authenticated REST 与 SDK，MCP 改为单次 SDK 薄代理，Agent 保持能力路由；纯 Application+SDK/MCP `39 passed`，current-data 46 面与架构门禁通过 | API runtime 当前无 Django 5.2/DRF/Celery 完整环境，专属 API tests 未执行；Evidence 仍为 semantic overclaim，未声明 integrated |
| 2026-08-13 | 第一期 P0 | Strategy execution preview 真实发布面收口 | 移除 Interface 的价格100/Unknown Regime/0.8置信度伪事实；行情/信号/Regime/账户及四类观测时间必填且 freshness 失败关闭；Domain allow 也恒为 display-only/can_execute=false；分母校正为 `63/12/53/18`，纯测试 `8 passed` | 尚非 Evidence wrapper；补正式 Operator Spec/Envelope。API/serializer 测试因当前环境缺 Django 未运行；下步先处理 Advisor live-draft consumer 与真实 Portfolio 分母 |
| 2026-08-13 | 第一期 P0 | Portfolio canonical transition 真实分母 | 补冻结 production `TransitionPlan/OrderDraft` 全字段与 composite，均标未接 Evidence/legacy ungated；确认 create/get/approve/submit 可达但尚无 Broker 真接线；分母校正为 `65/14/53/18`，专属 `12 passed` | 补 approve/submit Evidence exact 重验或独立授权的 display-only 硬阻断；默认 snapshot 校验仍关闭，旧 Domain 读链仍未退役 |
| 2026-08-13 | 第一期 P0 | Portfolio canonical account/submit 硬闸 | create/detail/approve/submit 全部绑定当前用户实际账户，跨账户403；APPROVED 计划在无正式 Evidence 时稳定阻断 execution_handoff，原链无 Broker 真调用；纯测试 `4 passed`、写面/架构门禁通过 | 创建/审批仍非 Evidence，默认 snapshot 校验仍关闭；补 exact Evidence graph 后方可恢复 submit；Django API tests 已写但当前环境未运行 |
| 2026-08-13 | 第一期 P0 | Advisor→Broker live draft consumer 硬闸 | 保留 advisor sheet 只读 preview，但发布 commit_allowed=false/display-only/must-not-execute；commit 与底层 converter 双层阻断，Classic 工作台不再展示提交按钮；inventory 如实改为 hard-blocked，分母仍 `65/14/53/18` | 补完整 Advisor Evidence graph 与 consumer exact 重验后才能恢复；Django component/API 待合格 runtime 复跑 |
| 2026-08-13 | 第一期 P0 | Broker connection 双时钟 current-data 硬闸 | Agent 上送 source observed_at，服务端保留 source/receipt 双时钟；connections/onboarding/lease 统一90秒规则，旧Agent或缺失/未来/过期源时间均降级且不能领单；current-data=`48 surfaces`，纯+SDK/MCP验证 `35 passed` | 生产 Windows Agent 须升级并重新观察 fresh heartbeat；MCP保持disabled，其他 Broker 输出仍待 typed Evidence 收口；Django component/API 待合格runtime复跑 |
| 2026-08-13 | 第一期 P0 | Broker overview 完整 current-evidence READY 门禁 | READY 改由 Application 从逐账户 binding、双时钟连接、SLA 内 snapshot、同 snapshot completed reconciliation、开放订单、kill/alert/difference 完整推导；查询时钟不再洗白源时间，SDK 原样保留门禁字段，MCP 保持 disabled；current-data=`49 surfaces`，纯测试 `29 passed` | 尚非正式 Evidence/Risk Authorization；生产 Agent/snapshot/reconciliation 与 Django API/component 待合格 runtime 和真实运行复验 |
| 2026-08-13 | 第一期 P0 | Broker live-order 四节点 Evidence 硬暂停 | create/approve/lease/submitting 在 Application+repository 双层 fail-closed；approve/advisor commit 的 MCP/TUI 发布面关闭，preview 与 reject/cancel/kill/对账保持；CI guard 冻结4节点，纯+MCP回归 `44 passed` | 明确暂停实盘新提交，尚非 Evidence 集成；须完成 owner-bound Evidence/Risk Authorization/plan receipt 四节点 exact 重验并补 Django/Agent runtime 后才能恢复 |
| 2026-08-13 | 第一期 P0 | Broker order detail legacy Evidence 只读收口 | exact重验 approval digest；raw risk/event payload 改 hash/白名单；lifecycle 与 actor授权分离；只恢复 closed-schema MCP详情读，聚合 `51 passed`，P0 MCP=`18 / disabled 6 / integrated 0` | 永久 display-only/must_not_execute，不解除四节点硬闸；Django/API/core-only MCP runtime待补，audit/reconciliation/catalog继续disabled并分批收口 |
| 2026-08-13 | 第一期 P0 | Broker audit 动态字段白名单与脱敏 | HTTP/SDK/Classic audit 不再透传 actor/resource/request身份、IP/UA、credential、risk、approval、recommendation、任意 Agent result；未知writer/command仅元数据+blocker，纯+SDK `12 passed` | MCP audit保持disabled且integrated=0；14-writer AST机器guard、Django component与Classic回归待补，随后收口reconciliation/catalog |
| 2026-08-13 | 第一期 P0 | Broker reconciliation typed current-evidence 只读收口 | 四维expected/actual白名单、源时点顺序、run/resolution状态、计数守恒、P0 auto-stop与唯一identity全部fail-closed；canonical hash+display-only markers，纯+SDK `13 passed` | 不是正式Evidence，MCP reconciliation保持disabled；total_asset差异、snapshot created_at绑定、Django/PostgreSQL持久化与并发验证待补 |
| 2026-08-13 | 第一期 P0 | Broker order catalog actor-aware display-only 收口 | 动态risk改hash、目录删敏感详情；16态/Decimal/时点不变量fail-closed；lifecycle×role/account×Evidence四层合成，approve固定false，权限缓存3A，纯+SDK `48 passed` | MCP catalog保持disabled且integrated=0；reject grant策略、Classic effective_actions、Django/query-count待补，正式receipts未完成 |
| 2026-08-13 | 第一期 P0 | Broker execution authorization 本地合同冻结 | Broker自有exact scope绑定Plan/审批、订单快照、Evidence envelope/spec/track record、Risk authorization、benchmark及有效期交集；canonical hash与supersession已冻结，聚合 `22 passed` | 合同固定inactive/must-not-execute；先补Portfolio与Risk owner receipts/ledger/provider，再做Broker签发、四节点重验，现有总闸不得解除 |
| 2026-08-13 | 第一期 P0 | Portfolio canonical plan integrity 与 inactive approval 合同 | canonical-v1哈希提升为Domain真源且字节兼容；repository读/批/重放重算拒绝篡改；approval receipt绑定plan/hash/actor/expiry但固定inactive，聚合 `15 passed` | 补append-only ledger、可信actor/clock、exact/PIT provider和canonical-v2完整输入hash；Risk/Broker未完成前submit与实盘总闸保持关闭 |
| 2026-08-13 | 第一期 P0 | Risk Center Broker order authorization Domain 合同 | Risk scope绑定account、execution scope、plan/approval、order、policy及有效期；双human-staff非自批、PIT与supersession已冻结，Risk+Broker gate聚合 `33 passed` | 尚无policy/provider/Application/ledger或first-winner并发证明；Broker issuer/四节点重验未接，总闸继续false |
| 2026-08-13 | 第一期 P0 | Risk Center Broker order authorization Application 合同 | register/approve写命令仅ID/version；server clock、scope+policy双读、账户闭合、current-head predecessor、first-winner/CAS与exact/PIT读协议已完成，纯fake+gate `39 passed` | 尚无生产policy/scope composition与Django append-only ledger/人工入口/PG并发；不可签发生产授权，Broker总闸保持false |
| 2026-08-13 | 第一期 P0 | Risk authorization first-winner/current-head 修正 | 修复register/approve跨时钟重试冲突；approve核对persisted subject winner；新增closed scope selector并拒绝已supersede旧授权，聚合 `41 passed` | 当前仍是pure fake协议；repository必须原子实现logical-head CAS，生产provider须保证exact版本也是current head |
| 2026-08-13 | 第一期 P0 | Risk Broker authorization append-only persistence | 独立private-UOW、两张append-only ledger、strict codec、identity/content/header seals、root/successor约束与current-head predecessor CAS已落盘；0008为schema-only/zero-seed | 当前Python缺Django，component/migration断言未运行；补项目runtime+PG并发、production provider/人工入口，未接Broker总闸 |
| 2026-08-13 | 第一期 P0 | Risk ledger chain/current-head 修正 | current-head改为全ledger restore后按Domain identity验证单根/同链前驱/时钟/可达；header篡改不能复活旧head，IntegrityError只返回exact candidate | component仍因缺Django未运行；补PG双事务root/successor race与完整tamper runtime，Broker总闸不变 |
| 2026-08-13 | 第一期 P0 | Portfolio inactive plan approval Application | ID-only register/approve/exact-PIT、trusted plan双读、server clock、persisted first-winner、跨时钟幂等与非自批已完成；聚合 `22 passed` | 仅pure fake且固定inactive；补Django exact provider/append-only ledger/人工入口/PG first-winner，不接旧approve/submit/Broker |
| 2026-08-13 | 第一期 P0 | Portfolio inactive receipt subject seal 修正 | receipt hash补绑定subject identity/hash与requester；actor_id/user_id双重非自批，winner replay限原requester/approver，exact read同时闭合subject+plan；专属 `19 passed` | plan_status仅inactive签发快照、未进入canonical-v1 hash；仍缺owner lifecycle event/ledger/runtime，不能用于submit/Broker |
| 2026-08-13 | 第一期 P0 | Portfolio inactive approval append-only persistence | private-UOW两表账本、strict codec、exact first-winner/PIT与approved_at provider已落盘；0017 schema-only/zero-seed；SQLite最小往返1+1条通过 | 完整Django component/migration与PG并发未验证；无人工入口，不接旧approve/submit/Broker，status仍非canonical-v1内容 |
| 2026-08-13 | 第一期 P0 | Risk-owned Broker execution policy Domain | 7项Decimal风险参数、source snapshot seal、账户/时钟/有效期/前驱与execution-eligible authority固定为content-addressed合同；聚合 `48 passed` | 仅Domain；现有mutable policy不得直接adapter，补source snapshot/activation/ledger/current-head provider前继续Unavailable且总闸false |
| 2026-08-13 | 第一期 P0 | Broker order approval owner artifact | 将canonical订单UUID/version、完整approval snapshot与既有digest、账户、批准人双身份/角色、批准时点和snapshot expiry封存为Broker自有content-addressed工件；金额闭合与推荐lineage失败关闭，专属 `21 passed` | 仅Domain seal，固定activation不可用/must-not-execute；尚无append-only ledger/provider，也不等于Plan、Research或Risk授权，总闸继续false |
| 2026-08-13 | 第一期 P0 | Risk execution policy Application workflow | ID-only激活绑定完整floor/template/account override/global+account exception source bundle；trusted source双读、server human-staff actor seal、first-winner/CAS predecessor与exact current PIT provider协议完成，Risk/Broker聚合 `66 passed` | 仅Application+pure fake；尚无source snapshot生产器、Django ledger/codec/provider或PG并发，zero-seed下authorization仍Unavailable且Broker总闸false |
| 2026-08-13 | 第一期 P0 | Broker order approval artifact append-only persistence | private-UOW单表账本、strict codec、identity/order/content first-winner、全header/ledger seal与历史exact/PIT reader已落盘；0008 schema-only/zero-seed，Django5.2 SQLite最小往返为 `1 / True / must_not_execute=True` | 只提供历史批准工件，不提供current execution permission；完整component/迁移往返与PG并发未验证，尚无pre-risk scope/provider，总闸继续false |
| 2026-08-13 | 第一期 P0 | Risk execution policy append-only persistence | 五类source bundle与actor-bound activation两表账本、strict codec、first-winner、account root/successor CAS和full-chain current head已落盘；0009 schema-only/zero-seed，Django5.2 SQLite最小往返 `1 source / 1 activation / current=True` | 尚无mutable policy→exact source生产composition或PG并发；zero-seed下不会自动激活policy，Risk authorization与Broker总闸继续关闭 |
| 2026-08-13 | 第一期 P0 | Broker/Risk ledger contract audit修正 | 0008/0009 model↔migration constraint deconstruct已对齐，Broker clock约束补persisted=recorded；Risk policy DTO/authorization scope拆分policy content hash与actor-bound activation hash，聚合 `53 passed`、架构2688/0 | 完整项目makemigrations仍被当前Django5.2环境缺cryptography阻断；Risk source exact selector闭集扫描与PG并发仍待补，执行总闸不变 |
| 2026-08-13 | 第一期 P0 | Risk policy source closed-world restore | source first-winner与activation binding改为先restore完整source ledger再按Domain identity选winner；双改identity tuple+seal也不能隐藏坏行或重开原identity | component回归已补但完整Django runtime尚待执行；PG race仍未验证，zero-seed与Broker总闸不变 |
| 2026-08-13 | 第一期 P0 | Broker pre-Risk inactive scope | ID-only注册在单一server cutoff双读Portfolio plan/inactive receipt与Broker order artifact，封存三源exact identity/hash/有效期并形成本地first-winner/current-head链；纯测试 `36 passed`、strict mypy与架构门禁通过 | scope固定inactive并保留5个blocker；尚无ORM ledger、跨账户namespace owner binding或Risk adapter，最终issuer/四节点重验与总闸均未启用 |
| 2026-08-13 | 第一期 P0 | Broker pre-Risk append-only persistence | private-UOW账本、strict codec、identity/content/root/successor first-winner与closed-world current-head restore已落盘；0009 schema-only/zero-seed，Django5.2最小往返 `1 / inactive / must_not_execute=True` | 完整pytest-django与PG race未验；固定inactive且Risk active port selector/依赖方向不闭合，未加伪adapter，最终issuer与四节点总闸继续关闭 |
| 2026-08-13 | 第一期 P0 | Broker/Portfolio 账户 namespace binding Domain | Broker int 与 Portfolio str 账户身份原样分域；账户身份真源归Account而非Portfolio，binding封存两侧owner/type/id/version/hash、human-staff双身份、identity/content hash、时钟与supersession，纯测试 `47 passed` | 仅inactive Domain；尚无Account/Broker可信source provider、ID-only workflow、ledger/人工入口/PG并发，不能解除pre-Risk namespace blocker或执行总闸 |
| 2026-08-13 | 第一期 P0 | Broker Plan→Order inactive binding Domain | 精确封存canonical-v1 plan/receipt/subject/order ordinal row bytes与Broker order artifact identity/digest；固定三方owner/type和最早有效期、successor logical subject，纯测试 `59 passed` | 仅inactive Domain；尚无owner providers、ID-only workflow/ledger/真实签发，不能解除pre-Risk blocker或执行总闸 |
| 2026-08-13 | 第一期 P0 | Broker/Account namespace binding Application | ID-only注册在同一server cutoff双读Broker与Account exact-current source；要求相同owner user、real+active，并以human-staff actor、first-winner/CAS封存inactive binding，聚合 `74 passed` | 仅协议+pure fake；两侧immutable source、binding ledger/composition/人工入口/PG并发均缺，不能解除pre-Risk blocker或执行总闸 |
| 2026-08-13 | 第一期 P0 | Portfolio policy benchmark snapshot Domain | 封存Account identity、planning-policy activation、benchmark definition exact refs；Decimal组件唯一/有序/权重守恒，三源最早有效期与live inception时钟闭合，纯测试 `27 passed` | 固定inactive；三类owner source/ledger/provider、daily valuation、审批与Broker issuer均未实现，现有Float配置不得冒充正式benchmark |
| 2026-08-13 | 第一期 P0 | Portfolio policy benchmark definition Domain | 完整冻结成分/price ID/币种/Decimal权重、日历/价格/FX/公司行动/费用税费五类owner ref、估值cutoff/窗口/陈旧度与missing fail-closed；definition+snapshot `34 passed` | 五类methodology owner ledger/provider、definition ledger/activation、daily valuation与approval未完成；固定definition-only/must-not-execute |
| 2026-08-13 | 第一期 P0 | Broker Plan→Order binding Application | ID-only注册在单一Broker cutoff双读exact plan ordinal row、inactive receipt与order artifact；三源owner/type/hash/account/有效期闭合、first-winner/CAS与closed-current完成，聚合 `90 passed` | 仅协议+pure fake；三个owner public readers、binding ledger/composition/真实签发与PG并发均缺，账户namespace/pre-Risk blocker和总闸不变 |
| 2026-08-13 | 第一期 P0 | Portfolio planning policy definition Domain | 从mutable status中拆出policy ID/version、lot与5项exact Decimal定义；canonical hash/有效期闭合且无status/current/activation语义，纯测试 `75 passed` | 仅definition；先补append-only ledger/exact provider，再做两人activation；legacy status=active不得冒充正式activation |
| 2026-08-13 | 第一期 P0 | Portfolio planning policy definition ledger | strict codec+private UOW/claim、全写绕过阻断、identity/content/header/clock seal与closed-world exact PIT完成；Django5.2 zero-seed往返及隔离组件 `13 passed` | 不提供current/activation；完整manage.py drift因缺Celery、PG并发未验；activation ledger/composition与legacy迁移未完成 |
| 2026-08-13 | 第一期 P0 | Portfolio planning policy activation Domain | exact definition subject绑定server requester、definition seals/clock与predecessor；第二名human staff按actor/user双重非自批后签activation，definition+activation组合 `83 passed` | 仅configuration activation Domain，固定must-not-execute；ID-only workflow、两张ledger/current provider、legacy迁移和benchmark composition均未完成 |
| 2026-08-13 | 第一期 P0 | Portfolio planning policy activation Application | ID-only注册/审批，server actor/clock、definition与subject双读、first-winner/predecessor CAS及closed-current selector闭合；组合 `92 passed` | 仅Protocol+pure fake；definition/activation持久化、真实composition/actor interface、PG并发和legacy迁移未完成，执行总闸不变 |
| 2026-08-13 | 第一期 P0 | Portfolio planning policy activation ledger | subject+activation双账本、private UOW/claim、single-root/predecessor CAS、closed-world restore、FK/header/hash/clock seal与current head完成；Django5.2组件 `15 passed` | PG并发、完整manage.py drift与ruff未验；真实composition/actor、legacy迁移及benchmark消费未完成，仍must-not-execute |
| 2026-08-13 | 第一期 P0 | Account-owned account identity snapshot Domain | 字符串Account identity与底层整数unified provenance分离；封存underlying source seal、owner/real/active、TTL最早有效期；legacy默认user强制Account reclaim receipt，纯测试 `61 passed` | 仅inactive Domain；trusted provider、ID-only发行/reclaim、append-only ledger/current facade未实现，不能供namespace binding真实签发 |
| 2026-08-13 | 第一期 P0 | Account identity snapshot Application | 普通Issue与legacy Reclaim均ID-only；raw/receipt双读、server actor/clock、first-winner/CAS和exact/current reader闭合，legacy无exact reclaim receipt零写入；组合 `95 passed` | 仅Protocol+pure fake；raw adapter、reclaim receipt owner ledger、snapshot ledger/composition、真实actor与PG并发未完成 |
| 2026-08-13 | 第一期 P0 | Account identity snapshot ledger | actor/provenance/reclaim refs/identity-content-header-clock seals、private UOW/claim、single-root/predecessor CAS与closed-world exact/current完成；Django5.2 minimal往返通过 | 完整组件pytest无最终结果，PG并发/完整migrate未验；raw adapter、reclaim receipt owner ledger/provider、composition与actor仍缺 |
| 2026-08-13 | 第一期 P0 | Broker-owned broker account identity snapshot Domain | 封存Broker账户、Account exact source、binding/Agent owner seals和keyed QMT ref digest；owner/real/active一致、TTL最早有效期与successor闭合，纯测试 `34 passed` | 仅inactive Domain；Account facade、Broker raw provider/digest service、ID-only发行、ledger/current reader均缺，不能接namespace binding真实composition |
| 2026-08-13 | 第一期 P0 | Broker account identity snapshot Application | ID-only发行双读Account exact source与Broker binding/Agent raw facts；QMT opaque bytes仅进keyed digest service，server actor、first-winner/CAS和closed-current闭合；组合 `54 passed` | 仅Protocol+pure fake；真实Account facade/raw provider、key service、snapshot ledger/composition、actor与PG并发未完成，ruff未验证 |
| 2026-08-13 | 第一期 P0 | Broker account identity snapshot ledger | actor/Account ref/binding/Agent/keyed digest与全套seals、private UOW/claim、single-root/predecessor CAS、closed-world exact/current完成；Django5.2 minimal往返通过 | 完整组件/migration state/mypy/ruff与PG并发未验；真实facade/raw provider/key service/composition/actor仍缺，不能接namespace binding |
| 2026-08-13 | 第二期 P0 | Web→TUI M5 candidate/observation gate 加固 | UAT/cleanup/rollback 改为绑定 commit+matrix+graph+schema+runtime/build/manifest；旧 108/108 与旧 rollback 已改判 FAIL；observation 只接受新鲜、已提交的 production deployment attestation，禁止 caller 回填日期；observation `15 passed` | 补真实候选部署、14 日窗口、生产样本与双签 |
| 2026-08-13 | 第二期 P0 | Web→TUI M5 cleanup wave guard | 修复 post-delete/pre-cleanup SHA 不可达循环；强制双签重放、≤10 route/波、rollback manifest、串行 commit、≥48h+定时周期观察、缺陷与错误率门禁；`15 passed` | 补 cleanup wave/rollback/observation ledger recorder；无真实证据前保持 DENY |
| 2026-08-13 | 第二期 P0 | Web→TUI rollback drill v2 | 从 migration anchor 自动推导 baseline，全部 patch/manifest/graph/schema/runtime 绑定 immutable candidate；真实隔离 reverse/forward 通过 31 artifacts，actions `402→430` | 补 Django registry 往返 runtime、生产备份/恢复和最终候选重跑 |
| 2026-08-13 | 第二期 P0 | Web→TUI candidate evidence recorders | UAT/cleanup 固定执行套件并重解析 JUnit，rollback 只接受 drill v2，报告绑定 exact candidate 且不接受自报 passed；`5 passed` | 建立真实 candidate 后重跑；另补 M5-B wave/48h observation ledger recorder |
| 2026-08-13 | 第二期 P0 | Web→TUI M5-C final inventory gate | 新增独立 `--require-finalized`：只允许 41 个 C 档物理模板，A/B/D 全 deleted，并检查孤儿 view/route/static 与 legacy alias；普通 196 行冻结检查保持通过，最终模式因 148 个 A/B 未清理保持 DENY | 仅在逐波生产观察、rollback 和审批齐全后执行删除；清理 11 个 dead alias 与 1 个 dangling alias |
| 2026-08-13 | 第二期 P0 | Web→TUI current production preflight | 公开 health/ready 为 200/ok；当前 release=`source-20260813002655`，但 OCI revision=`unknown` 且 release 无 Git/source manifest，不能绑定 candidate，观察仍未开始 | 修复 release provenance，重新部署干净最终候选，并在部署后生成结构化 attestation |
| 2026-08-13 | 第二期 P0 | Web→TUI M5-B cleanup wave recorder | 从 candidate Git snapshot 重算单波删除/≤10 route/task/rollback；强制已提交且 commit+OCI 精确绑定的 deployment preflight，以及部署后 48h telemetry/defect/scheduled-cycle 原始证据；`14 passed` | 当前无删除候选和生产证据，CLI 保持 FAIL；待候选部署后逐波实际执行 |
| 2026-08-13 | 第二期 P0 | Web→TUI release provenance fail-closed | 发布工具拒绝 dirty/unknown source，clone 锁定 exact commit；构建强制 OCI revision 并生成只读 release manifest，deploy 在启动服务/切换 current 前复核 manifest+image；相关 `44 passed` | 尚未部署；当前生产仍为 revision=`unknown`/无 manifest，须经授权部署干净候选并重新 preflight |

## 2026-08-12 整理结果

- 归档 50 份已完成文档：原批次 44 份，加上零循环整改、TUI IA，以及经代码与自动化证据复核完成的 MCP、Capability Catalog 和 Terminal 三条历史任务主线。
- 保留 45 份活跃文件；其中也包括尚未解除生产门禁的本地完成记录。
- Web → TUI M0–M4 历史证据已归档；M5 readiness、生产 preflight、UAT、回滚与 route closure 继续留在活跃区，直到 cutover 门禁真正解除。
- AI-Native 主计划因人工 UAT 签字与 release gate 尚未补齐继续保留；首页聊天复用任务书因前端自动化和浏览器验收资产未闭环继续保留。
- `implementation-progress-summary.md` 暂保留为总体进度入口，不按阶段总结归档。
