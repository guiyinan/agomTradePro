# AgomTradePro 证据治理与决策硬闸改造计划

> 执行状态（2026-08-13）：**M0 进行中，外部写面、Transition Plan 内部 writer、65 个显式高风险输出及 18 个动态 query/GET/presenter 面已冻结；M1 Domain、append-only persistence、staff-only exact read API、Operator Spec lifecycle、Risk Center approval provider、Research↔Risk read composition、人工 subject/审批写入面代码与首批 legacy adapters 已完成**。当前工作分支为 `dev/plan-closure-by-priority`；归档与排期基线提交为 `919a9cea7`。本状态只证明下列已列出的仓库交付，不代表用户/租户 owner-scoped API、写入面的完整项目 runtime/component 证明、其余 App 输出 adapter、TUI、Portfolio、Broker 或生产硬切换已经完成。

### 2026-08-15：旧计划收口后的 Evidence 接管范围

`GOV-01` 已清空旧计划审查队列，但不关闭生产证据门禁。以下残余由本计划继续承接：

- 账户业绩/估值与统一账本：`account-performance`、`account-refactor` 的 owner scope、source freshness/identity/content hash、exact-current、真实回填与 rollback 证明归 `EVID-01/EVID-03`；破坏性迁移同时受 `DATA-01/02/03` 约束。
- 决策工作台与 Alpha 退出：`workflow-upgrade`、`alpha-exit-loop` 的 legacy writer、Transition Plan receipt、执行前重验与审批授权归 `EVID-03`，不因旧实施计划归档而开放执行。
- Alpha 首页及用户面：`alpha-homepage` 的 PIT/OOS、owner/receipt 与 consumer 证明继续由 Strategy/Evidence 处理；页面迁移和角色化 UAT 由 `web-to-tui-m5` 处理。

上述映射只调整计划归属，不把本地 API、缓存或单元测试升级为可信生产 Evidence；全局 execution deny、owner/tenant authority 与 PostgreSQL 证据要求保持不变。

## 0. 分阶段实施记录

### 2026-08-12：M0 基线与 M1 Domain / persistence 首批

已完成：

- 在独立 `dev/plan-closure-by-priority` 分支开始实施，并把完成计划归档、活跃计划优先级和索引修正作为独立基线提交。
- 新增 [`ADR-0007`](../architecture/adr-0007-evidence-envelope-and-decision-gates.md)，明确 Research、Data Center/Signal、Risk Center、Portfolio、Broker Execution 与 TUI 的 owner/接口矩阵，以及决策写入口冻结原则。
- 新增 `governance/decision_write_surfaces.json` 与机器门禁，冻结 54 个 Decision Rhythm、Portfolio、Broker Execution、Simulated Trading、Strategy HTTP 写入口、15 个 SDK 写方法、25 个发布态 TUI 决策流 action、23 个发布态 mutation/AI/admin action，以及 32 个可能影响决策或仓位的 MCP 写能力；发布图 SHA 漂移、新增旁路或陈旧登记均阻断。
- 同一写面门禁现冻结 Transition Plan 的 10 个内部 writer：默认仍启用的 6 个 Decision Rhythm legacy build/save/upsert/status/approval-request 路径（含审批结果对 plan 的连带状态写入），以及 4 个 Portfolio canonical build/validate/save/approve 路径。每项固定 ownership、mutation semantic、默认启用状态、legacy replacement 与关键 AST call；新增未登记 writer、陈旧 symbol 或写调用漂移均阻断。这只冻结现状，不批准 legacy 原地 upsert。
- 新增 Research Domain `evidence_contracts.py`，落地 `ClaimKind`、`MethodKind`、`GovernanceState`、唯一有序的 `DecisionPermission`、`DependencyFlag`、`ArtifactRef`、`EvidenceOperatorSpec`、`TrackRecordSnapshot`、`GovernanceGrant` 与 `EvidenceEnvelope`。
- 实现 fail-closed 传播：权限取严格交集，lineage/不确定性依赖取并集，必要输入 stale/missing/PIT 未验证、Promotion/monitoring/Track Record 缺失或过期、精确 artifact 不匹配和 `n=0` 均降为 `DISPLAY_ONLY`。
- 兼容布尔值只由权限派生；旧输出只能生成非持久化 `legacy_unverified + DISPLAY_ONLY` Envelope。
- 新增 19 个纯 Domain 测试；补充 Operator Spec、Track Record、Envelope 的 canonical hash 重算和构造后篡改阻断、naive datetime、非有限 Decimal 及倒置有效期拒绝；隔离项目外部插件后 `19 passed`，Domain/codec standalone strict mypy 为 `0 errors`。
- 新增 schema-only、zero-seed 的 migration `0026_evidence_ledgers`，建立 Operator Spec、Track Record 与 Envelope 三个 immutable ledger；identity/content/header hash、clock check 与 PIT index 均落在数据库 schema。
- 新增 strict codec、公共 exact/PIT reader 和私有 token/claim append store；instance/QuerySet/manager 的 save/update/delete/bulk/conflict-update/raw shortcut 均 fail closed，exact replay 幂等，identity fork、payload/header/hash 漂移均阻断。
- 新增 `governance/evidence_output_surfaces.json` 与机器门禁，首批冻结 41 个高风险决策输出（11 个直接影响仓位）；12 个 legacy boolean、14 个 legacy ungated、15 个 research-only 输出均明确标为尚未接入统一 Evidence，不以登记冒充完成。
- 将 write-surface freeze 与 Evidence output inventory 两条守卫接入常规 consistency-check CI，并由 governance wiring 自检强制保留命令，避免仅靠人工单独运行。
- 新增 Research Application exact-read port/facade、composition root 与三个只读 HTTP detail endpoint；Operator Spec、Track Record 和 Envelope 均强制 identity/version、预期 content hash 与非未来的 timezone-aware `as_of`，Envelope 额外强制应用级 `output_owner`。
- 只读 HTTP 面严格限定已认证 staff，写方法全部 405，miss 使用统一非枚举 404；由于当前 Evidence artifact `owner` 表示应用/能力而非用户或租户，本批没有伪造 owner-scoped 授权语义。
- 公共仓储同时注入权威 server clock 并拒绝 future PIT cutoff，确保绕过 HTTP 直接调用 Application/Repository 也不能查询未来证据。
- 新增 Operator Spec definition、Risk Center approval receipt 与 activated record 的 immutable lifecycle；调用方 mutation command 只能提交 spec/approval 的 ID、版本和 `as_of`，claim/method/权限/actor/supersession 均只能来自可信 definition provider 与 Risk Center Application port。
- 激活在同一事务内双读 definition/approval 防漂移，并原子追加 approval receipt 与 activation；exact/PIT read 会重放完整 supersession chain，fork、orphan、cycle、断链、空 active ledger 和 future cutoff 均失败关闭。
- migration `0027_evidence_operator_spec_lifecycle` 为 schema-only/zero-seed；数据库唯一约束同时阻断并发双 root 和同一 predecessor 的双 successor，append-only ORM guard 继续覆盖直接 create/bulk/mutation/delete shortcut；没有新增公开 HTTP writer。
- 新增紧凑 `EvidenceSummaryDTO` Application 合同，固定输出 artifact/envelope/operator hashes、分类、治理状态、权限、blockers、依赖与有效期；`must_not_use_for_decision` / `must_not_execute` 只从 Envelope 派生，并将 Track Record 明确区分为 `not_required / unavailable / empty / available`，为后续 TUI Evidence Strip 保留正确语义。

### 2026-08-13：M1 Risk Center approval provider 首批

已完成：

- 新增 Risk Center 专用 immutable approval subject / record 与 canonical hash；没有把字段不足的 Scenario Governance audit 或 `AgentProposal` 冒充 Operator Spec 审批真源。
- 审批命令只接受 subject/approval ID、版本和 `as_of`；批准者来自 server-authenticated actor，必须是 human staff，并同时以 actor ID 与 user ID 禁止自审批；签发时间只取 Risk Center server clock。
- 新增 Application exact/hash/PIT/definition selector facade；未来 cutoff、签发前、过期、identity/hash/definition/supersession 不匹配均失败关闭。
- 新增 append-only subject/approval ledger、strict codec、typed redundant headers、first-winner 唯一约束与 raw tamper 检测；migration `0007_evidence_operator_spec_approvals` 为 schema-only、zero-seed，无跨 App ORM FK、无公开 HTTP writer。
- 新增 Research Application adapter 与 Django composition：只通过 Risk Center Application query facade 读取 exact approval，不直接导入 Risk ORM；adapter 二次校验 owner/capability/approval/operator/definition/supersession selector，并把 Risk approval record hash 固定为 Research receipt 的外部真源。
- composition 只暴露 ID-only activation 和 exact/active PIT reads，不暴露 Risk append repository 或 actor 注入；在人工 subject/审批写入面未提供时仍 fail closed。

仍未完成：

- Risk Center 的 subject 注册/人工审核入口及生产 actor 注入；PostgreSQL 真实并发 first-winner 验证。
- 各 App 输出 adapter、M2–M5 与生产硬切换证据仍未完成。

本阶段验证：

- 纯 Domain/Application/codec：`10 passed`，standalone strict mypy `0 errors`。
- Django 5.1/SQLite component：`6 passed`；migration forward/reverse/re-forward 全通过且 zero seed，migration drift 无变化，最小 Django check `0 issues`。
- 架构扫描：`2640 files / 0 violations`；Black、isort 与 `git diff --check` 通过。
- Research↔Risk adapter 纯单元：`3 passed`；adapter/test standalone strict mypy `0 errors`；Black、isort 与 `git diff --check` 通过。
- 未验证：标准项目 pytest-django runtime 与 PostgreSQL 真实并发竞争。

### 2026-08-13：M1 Data Center legacy adapter 首批

已完成：

- 为 `QuoteResponse` 增加 Research Application adapter；adapter 从 quote 全字段生成 canonical content hash，使用源 `snapshot_at` 作为 artifact version，并拒绝 naive/future 时间、future fetch、非有限数值和非法 freshness window。
- 旧 quote 只生成非持久化 `legacy_unverified + DISPLAY_ONLY` Envelope；`EvidenceSummaryDTO.from_legacy_envelope` 会重建并精确比对标准 legacy wrapper，禁止伪造 Operator Spec、治理状态、权限、lineage 或 blocker。
- Evidence 输出清单将且仅将 `QuoteResponse` 标为 `legacy_evidence_wrapped_display_only`；其余 40 个输出的未接入状态不变。这个状态不等于正式 Evidence 集成，也不授予任何决策或执行权限。

仍未完成：

- Quote 真实 Operator Spec 激活、持久化 Envelope、owner-scoped API 与 consumer 接线；其余 Data Center、Regime、Policy、Pulse、Alpha、Signal、R1–R8、Strategy/Portfolio adapters。

本阶段验证：

- adapter、summary 与 inventory 聚合纯测试：`19 passed`；standalone strict mypy `0 errors`；Black、isort、`py_compile`、inventory CLI 与 `git diff --check` 通过。

### 2026-08-13：M1 Broker approval snapshot legacy adapter

已完成：

- 为实际位于人工批准到券商提交边界的 `OrderApprovalSnapshot` 增加 content-bound legacy adapter；复用现有 approval digest，绑定账户、Agent、资产/市场、方向/订单类型、数量/限价/金额、有效期、Risk policy/snapshot、approval mode 与 recommendation/signal IDs 全字段。
- adapter 对 aware expiry/evaluation clock、正且有限的 Decimal、数量×价格金额勾稽、canonical JSON object、严格有序唯一 source IDs 和 exact enum/type 失败关闭。
- 输出始终为 `legacy_unverified + DISPLAY_ONLY`，`must_not_use_for_decision` 与 `must_not_execute` 恒真；没有接入或修改 Broker 批准/提交授权链，也不替代现有 approval digest。
- Evidence inventory 仅把 `OrderApprovalSnapshot` 与此前 `QuoteResponse` 标为 wrapped；41 个 surface、11 个 direct-position 与 32 个 marker 分母不变。
- Broker Domain 类型到 Research 数据投影的转换位于 `core/integration`，Research Application 不直接依赖 Broker App；带 allowlist 的 module-cycle gate 保持 207 条边、0 cycle。

本阶段验证：

- adapter 与 inventory 聚合纯测试 `22 passed`；inventory guard 为 `41 / 11 / 32`。
- 两个目标文件 standalone strict mypy `0 errors`；Black、isort、`py_compile` 与 diff check 通过。

### 2026-08-13：M0 Broker 动态输出面冻结

已完成：

- 在既有 41 个显式 Evidence 输出清单之外，精确登记 `BrokerExecutionQueryService` 的 8 个 `dict[str, Any]` 查询方法，以及实际发布这些查询结果的 8 个 GET handler。
- 守卫通过 AST 独立发现这 16 个动态面；新增未登记 query/GET、删除后遗留登记或 symbol 漂移均失败关闭，避免动态 payload 绕开基于 dataclass/字段的原有发现规则。
- 本步骤只冻结迁移分母，不把 legacy dict 响应标为 Evidence 集成，也不授予决策、批准或执行权限。

仍未完成：

- 16 个 Broker 动态响应的 typed contract、Evidence Envelope/summary adapter、consumer 接线与执行硬闸重验；其余 App 的动态 dict/TypedDict/interface/query payload 及 raw/governed MCP 输出语义仍待盘点。

本阶段验证：

- `python scripts/check_evidence_output_surfaces.py`：通过，显式输出 `41`、direct-position `11`、marker-discovered `32`、Broker dynamic `16`。
- 专属纯测试 `8 passed`；守卫与测试 standalone strict mypy `0 errors`；Black、isort、`py_compile`、JSON parse 与 diff check 通过。

### 2026-08-13：M0 R1–R6 研究输出分母扩展

已完成：

- 代码反查补登记 13 个可静态、诚实分类的 R1–R6 结果面：R1 baseline preflight/trial，R2/R4/R5/R6 research-control preflight，R3 governed read/macro-factor assessment，R5 fixed-income preview/portfolio risk/relative-value assessment，以及 R6 active projection/qualification assessment。
- 所有新增结果均保持 `indirect + not_evidence_integrated_research_only`；登记只冻结迁移分母，不代表 Operator Spec、Envelope、summary、consumer 或决策许可已经接入。
- 动态面新增两个无 HTTP route 的 internal presenter：Macro Factor 与 Fixed Income 的 `dict[str, object]` 投影。机器守卫验证精确 symbol 与返回类型，不把它们冒充公开 API。
- `OperatingForecastVersion` 可在同一实例混合 observation、human assumption 与 model inference；`DatedMacroFactorOutput` 又由角色区分 current estimate/forward forecast，因此没有强塞进当前单值 `claim_kind/method_kind`，留待 inventory discriminator/composite schema 扩展。

仍未完成：

- R7/R8 及 Broker 以外其他动态 dict/TypedDict/query/interface 发布面；R1/R3 上述 mixed/variant 类型的 schema 表达。
- 54 个显式输出中的绝大多数仍无正式 Evidence adapter/持久化/consumer binding，所有新增研究结果仍不得用于当前决策或执行。
- raw/governed MCP 语义仍须独立冻结；审计已发现 TUI read-action bridge 与 Broker native read 是优先绕行面。

本阶段验证：

- `python scripts/check_evidence_output_surfaces.py`：通过，显式输出 `54`、direct-position `11`、marker-discovered `45`、动态面 `18`。
- 专属纯测试 `9 passed`；`py_compile` 通过。完整格式、类型、架构与 diff 检查随本阶段提交执行。

### 2026-08-13：M0 MCP P0 输出语义冻结

已完成：

- 新增独立 `governance/mcp_evidence_output_surfaces.json`，先冻结 18 个最高优先 MCP 发布面：11 个带 research/decision Evidence 语义 tag 的 read、6 个 Broker native read，以及可展开全部发布态 read action 的 `terminal.read.user_action_result`。
- 每项精确绑定 capability key、executor kind/ref、raw alias、canonical output-schema SHA、发布语义与当前 gate state；新增、删除、alias/schema/executor 漂移均失败关闭。
- `equity.read.research_snapshot` 虽带 `mcp:decision_evidence`，但没有完整 Evidence Summary/Envelope/Operator/Track Record 合同，机器状态明确记为 `semantic_tag_overclaims_contract`，不把标签当完成证明。
- TUI bridge 闭包必须先经过 runtime metadata normalization：当前 published graph 为 430 actions / 408 read，430 个 `raw_debug=true`、0 个 `evidence_binding`；raw graph SHA 与 read-key SHA 均冻结。随后已将 `terminal.read.user_action_result` manifest 关闭，并让 handler 直调在 POST 前返回稳定 `mcp_evidence_binding_required`，因此 408 个未绑定 read action 当前全部对 MCP result bridge fail-closed；普通 TUI/search/schema 与其调试 payload 不变。
- 新 guard 已接入 consistency-check workflow，并纳入 governance wiring 自检。

仍未完成：

- 本批 `integrated_count=0`；18 个面均未因此取得 Evidence 决策或执行许可。Terminal result bridge 已安全暂停；只有 metadata binding、runtime Evidence Summary 校验与 MCP 白名单投影全部完成后才能重新启用。随后迁移 6 个 Broker native 与 11 个 tagged read。
- 审计识别的其余 28 个首批 marker 高风险 read 尚待登记，之后仍需完成剩余 read-like capability 的 raw/governed 语义分类与等价性门禁。
- `QuoteResponse` 与 `OrderApprovalSnapshot` 虽已有 legacy adapter，但运行时 Data Center/Broker MCP 链尚未接入这些 adapter。

本阶段验证：

- `python scripts/check_mcp_evidence_output_surfaces.py`：通过，surfaces `18`、tagged reads `11`、Broker native `6`、integrated `0`。
- 专属纯测试 `6 passed`；其余格式、类型、架构、governance wiring 和 diff 检查随本阶段提交执行。

### 2026-08-13：M0 Terminal MCP 未绑定 read bridge kill switch

已完成：

- `terminal.read.user_action_result` 已从 MCP discovery/call 面禁用；handler 保留第二道 fail-closed，schema 为 read 但没有 Evidence binding 时不发起 action POST，稳定抛出 `mcp_evidence_binding_required`。
- 修正 TUI action coverage guard 的假阳性：disabled bridge 不再把 published read action 计为 reachable；当前 read bridge count 为 `0`、blocked read actions 为 `408`。
- 保留普通 TUI 的 `raw_debug` 默认、`run_action` envelope、generated/published graph 字节和 action search/schema。只删除 raw response 仍会经 view model 发布无 Evidence 结论，因此没有采用该不完整方案。

仍未完成：

- 首个受控恢复批次必须同时实现 metadata `evidence_binding` schema、Agent schema 发布、runtime `evidence_summary` exact 校验及 MCP 白名单投影（永不返回完整 debug），并同步两张 operation graph 后才可重新启用。
- 6 个 Broker native、11 个 tagged read 及其余 marker/read-like capability 的正式 Evidence 接入仍未完成。

本阶段验证：

- MCP Evidence freeze 与 coverage/handler 专属聚合：`12 passed, 3 skipped`；skip 为当前隔离运行未加载 core-only MCP fixture，不是断言失败。

### 2026-08-13：M0 Broker MCP 决策语义 read kill switch

已完成：

- 逐项反查 6 个 Broker native read：overview 发布 readiness/待审批金额/kill switch/现金与仓位对账差异；order catalog/detail 发布审批链、订单状态和 action availability；reconciliation 发布订单/成交/现金/仓位差异。这 4 项已从 MCP discovery/call 面禁用。
- `connection_status` 进一步核出 freshness 假阳性：它直接发布持久化 `qmt_connected/status/last_heartbeat_at`，没有复用已有 90 秒 heartbeat freshness 或 blocker，因此也已禁用。历史 `audit_catalog` 的动态 before/after 可嵌完整订单/审批与 credential/Agent 结果，在 typed discriminated 白名单完成前同样禁用。
- MCP semantic guard 强制 6 个 `blocked_unbound_native_dynamic` 在未完成 typed contract、summary/Envelope 与 consumer 校验前保持 disabled；连同 Terminal bridge，当前 18 个 P0 面中 disabled=`7`、integrated=`0`。
- HTTP、TUI、SDK 与 Broker 写/审批链未改，避免关闭正式运维入口；本批只关闭缺 Evidence 的 MCP 旁路。

仍未完成：

- Order detail 只能在 exact、未过期、LIMIT、来源/金额/risk JSON 完整且 approval digest 闭合时复用现有 approval snapshot legacy adapter；catalog、overview、reconciliation 需要各自新的 typed contract 与 display-only Evidence summary，不能套用单订单 adapter。
- Connection 需补 heartbeat freshness、derived connected、stable blocker 与 typed projection；audit before/after 需白名单和有界化。完成运行时接线与测试后才可逐项恢复 disabled capability。

本阶段验证：

- MCP semantic freeze 与专属 disabled-state 测试随本阶段提交执行；完整项目 Broker HTTP/component 未改也未重跑。

### 2026-08-13：M1 Strategy DecisionResult legacy adapter

已完成：

- 新增纯 Application projection，把单个 Strategy `DecisionResult` 的 action、reason、有效期与 confidence 绑定到 canonical content hash；只接受规范 action、排序去重的非空 reason codes、aware 且未过期的有效期，以及 `[0,1]` 内有限 confidence。
- adapter 固定生成 `legacy_unverified + research_only + display_only` summary，始终发布 `must_not_use_for_decision=true`、`must_not_execute=true`；旧 `ALLOW` 不会因此成为 Evidence 授权或交易许可。
- production Strategy/Broker consumer 尚未接线；本批只提供可复核的兼容投影，不改变现有执行路径。

仍未完成：

- 补真实 Operator Spec、持久化 Envelope/Track Record、consumer binding 与执行时二次核验；在此之前 inventory 只能标记为 display-only wrapper。
- 11 个 tagged research/decision MCP read 同样尚无 Evidence；暂停它们属于生产可见服务降级，安全审查要求取得用户明确授权，本轮未绕过、未修改其 manifest。

本阶段验证：

- Strategy adapter 与 Evidence contract/summary 聚合 `28 passed`；standalone strict mypy 2 files `0 issues`；architecture delta `0` violations。

### 2026-08-13：M0 R7–R8 输出分母扩展

已完成：

- 新增 R7 持久结果、晋级后监控与 family lifecycle snapshot 3 个输出面，以及 R8 research report、assembly、run bundle、canonical portfolio snapshot、execution feedback 5 个输出面。
- 扩充既有 R7/R8 输出的 exact required fields；run bundle 以 `composite_fields=result+lifecycle_root` 明确复合合同，canonical snapshot/feedback 如实分类为 `not_evidence_integrated_governed_input`，不冒充 research-only 或 Evidence integrated。
- 机器分母现为 62 个显式面、11 个直接仓位面、53 个 marker 面、18 个动态面；新增/字段漂移/composite 漂移均 fail closed。

仍未完成：

- 这只是 R1–R8 分母冻结；R7/R8 仍需真实 Operator Spec、Envelope/Track Record、持久化 lineage 与 consumer binding。
- mixed/variant 类型、Broker 以外其余动态 dict/TypedDict/interface/query payload 与 11 个 tagged MCP read 仍待后续批次。

本阶段验证：

- inventory guard 通过；Evidence inventory + Strategy adapter/contracts 聚合 `39 passed`；py_compile、Black/isort 与 diff-check 通过。

### 2026-08-13：M1 Strategy OrderIntent legacy adapter

已完成：

- 新增独立的纯 Research Application projection，完整绑定 Strategy `OrderIntent` 顶层身份、方向、数量、限价、时效、幂等键、状态与时间，以及 Decision、Sizing 和 Risk Snapshot 的全部业务字段；调用方只能提供冻结的 tuple/Decimal/datetime 数据，adapter 不导入 repository、orchestrator 或执行 provider。
- 数量必须与 sizing 数量一致；ID/枚举/文本有界，Decimal 必须有限，confidence 在 `[0,1]`，价格/名义金额/风险限额与交易次数按现有领域约束失败关闭；`created_at <= updated_at <= evaluated_at < decision_valid_until` 且全部时间必须 aware。
- canonical hash 对等价 Decimal 尾零与等价时区保持稳定；artifact version 同时绑定 content hash，因此 `DRAFT→SENT` 即使旧 repository 没有刷新 `updated_at` 也会产生新身份。
- 输出固定为 `legacy_unverified + research_only + display_only`，`must_not_use_for_decision=true`、`must_not_execute=true`。现有 `ExecutionOrchestrator` 及 broker submission 链没有接入或改变，旧 `ALLOW` 绝不因本 wrapper 获得授权。
- inventory 仅把完整 Domain `OrderIntent` 标为 `legacy_evidence_wrapped_display_only`；有损的 `OrderIntentResponseDTO` 继续保持未集成，不能从缺失有效期、完整 sizing/risk 的 DTO 反推 Evidence。

仍未完成：

- production consumer/composition、正式 Operator Spec、持久化 Envelope/Track Record 与执行前 exact revalidation；当前 canonical planner flag 和旧 Strategy 直提交流程均未切换。
- `DecisionPolicyEngine` 的普通 DENY 在 OrderIntent 持久化前返回且没有 validity；adapter 不为其补造有效期，只有外部已提供未来 canonical validity 的完整投影才可包装。

本阶段验证：

- OrderIntent/Decision adapter 与 Evidence contract/summary 聚合 `46 passed`；Evidence inventory guard 为 `62 / 11 / 53 / 18`；architecture delta `0` boundary/audit violations；生产 adapter standalone strict mypy `0 issues`；Black/isort 与 diff-check 通过。

### 2026-08-13：Equity research snapshot 四入口唯一归并

已完成：

- 将原 MCP handler 内的 7 次 SDK/API 请求、evidence presence、nested freshness 和全局 readiness 归并迁入纯 Equity Application use case；Application 只依赖 Protocol，Data Center publication-only readers 与 core strict readiness 在顶层 composition 注入。
- 新增 authenticated、GET-only REST `/api/equity/research-snapshot/{stock_code}/`，严格拒绝未知参数/越界 limit/不安全 identifier；SDK 新增单一方法，MCP handler 只做一次 SDK 调用并原样返回服务端 envelope，Agent 继续沿既有 capability route。
- 更新 current-data 机器合同，明确 Application 是 freshness/阻断语义唯一 owner，REST/SDK/MCP 不再各自拼结论；`equity.read.research_snapshot` 仍保持 `semantic_tag_overclaims_contract`，没有误报 Evidence integrated，也没有禁用 11 个 tagged reads。

仍未完成：

- 当前本机没有符合项目声明的 Django 5.2 + DRF + Celery 完整 runtime；专属 API tests 已写但未执行。可用 `agomwiki` 仅 Django 4.2，且缺 Celery，不能作为正式证明。
- 补正式 EvidenceSummary/Envelope 与 consumer binding 后，才能移除 semantic overclaim；四入口收口本身不授予决策或执行权限。

本阶段验证：

- Application + SDK/MCP 专属聚合 `39 passed`；current-data contract `46 surfaces` PASS；architecture delta `0` violations；Black/isort/diff-check PASS。API runtime 测试明确列为未验证项。

### 2026-08-13：Strategy execution preview 真实发布面 fail-closed

已完成：

- 代码审计确认 inventory 中旧 `EvaluateExecutionResponseDTO` 没有 production caller；真实 `/api/strategy/execution/evaluate/` 原先在 Interface 直接拼 dict，并在缺 `current_price` 时使用 `100.0`、缺真实 Regime 时使用 target/`Unknown` 与固定 confidence=`0.8`，随后可能发布 `can_execute=true`。
- 新增纯 Strategy Application `ExecutionPreviewRequest/Policy/Result`，Interface 只做 serializer 输入与 settings policy 装配；行情、信号、Regime、账户快照的完整数值与各自源观测时间全部必填，不再合成当前价格/状态/账户事实。
- 四类源时间均须 timezone-aware、不得来自未来并分别满足 5 分钟/15 分钟/1 日/5 分钟 freshness；过期或非法输入稳定失败关闭。真实 current Regime/confidence 直接送入 Domain engine，不再把 target Regime 当 current。
- 即使 Domain 返回 `allow` 且 PreTradeRiskGate 通过，Application 仍固定 `research_only + display_only + can_execute=false + must_not_use_for_decision=true + must_not_execute=true`，并发布稳定 blocker；本 endpoint 是 sandbox preview，不再冒充执行授权。
- 将真实 `ExecutionPreviewResult` 补入 Evidence 输出分母并如实标为 `not_evidence_integrated_research_only`；旧零调用 DTO 的原状态不变。机器分母由 `62/11/53/18` 修正为 `63/12/53/18`，没有把显式阻断冒充 legacy Evidence wrapper。

仍未完成：

- 为 preview 建立正式 Operator Spec/Envelope/Track Record 与 EvidenceSummary 后，才能考虑 advisory/decision permission；当前无条件禁止执行。
- `AdvisorOrderIntent` 已确认流向 Broker live draft，不能只加 display-only adapter；后续必须同步硬阻断该 consumer 或完成正式生产 Evidence。真实 Portfolio canonical `TransitionPlan/OrderDraft` 尚未进入本 inventory，须先修分母，再处理旧 Transition DTO/审批链。

本阶段验证：

- 纯 Application `8 passed`；current-data guard `47 surfaces`；Evidence inventory `63 / 12 / 53 / 18`；architecture delta `0` boundary/audit violations；生产 Application standalone strict mypy `0 issues`；Black/isort/diff-check 通过。
- API/serializer 测试已补，但当前系统 Python 缺 Django，普通 pytest 还先被损坏的 Playwright entry point 阻断；禁用自动插件后仍因缺 Django 无法加载，因此不计为通过。`py_compile` 也因既存 `__pycache__` 权限拒绝未作为证明。

### 2026-08-13：Portfolio canonical transition 输出分母校正

已完成：

- 只读核对真实 `/api/portfolio/transition-plans/*` 链后，补登记此前 inventory 漏掉的 `apps.portfolio.domain.entities.TransitionPlan` 与 `OrderDraft`；两者都直接影响仓位，不能用多个零 production caller 的旧 Decision Rhythm DTO 替代真实分母。
- `TransitionPlan` 冻结身份、账户、decision/portfolio/target snapshot refs、as-of/expiry、现金、状态/version、orders/constraints 与 `metadata`（包含 planning policy version）；`OrderDraft` 冻结资产、方向、数量、参考价格、费用、状态、剩余数量与约束。三个复合字段由 guard 继续要求存在。
- 两项均如实分类为 `not_evidence_integrated_legacy_ungated`。当前 create/get/approve/submit REST 均生产可达；submit 只校验 `APPROVED + 未过期` 后返回 `execution_handoff`，尚无 Broker 调用，但也没有 Evidence/must-not-execute 语义，不能标 wrapped 或 research-only。
- 旧 Application `ExecutionPreviewDTO/TransitionOrderDTO/PortfolioTransitionPlanDTO` 没有 production 构造；旧 Domain TransitionPlan/Order 仍有读/审批消费者，故本批不删除旧登记，也不把旧 Domain 类误标 dead。

仍未完成：

- canonical approve/submit 必须绑定并重验 immutable payload hash、contract family、decision/portfolio/target/prices/market facts/policy version 与正式 Evidence；`DECISION_SNAPSHOT_REQUIRED` 当前默认 false，不能据可选校验宣称硬门禁完成。
- submit 在 Evidence 完成前应转为明确 display-only handoff 或硬阻断；这属于生产可见行为收缩，需作为独立批次实施与验收。TUI 生成的 detail GET 参数类型也需另批修正。

本阶段验证：

- inventory 专属 `12 passed`；机器分母 `65 / 14 / 53 / 18`；diff-check 通过。本批仅修改治理 inventory、测试和文档，没有改变 Portfolio 运行行为。

### 2026-08-13：Portfolio canonical transition 账户边界与 submit 硬阻断

已完成：

- canonical create/detail/approve/submit 四个 REST 入口不再只检查 `IsAuthenticated`：create 的 `account_id` 必须是当前用户实际拥有的数字账户，后续三个入口先读取 plan，再用 plan.account_id 复核同一 ownership；跨账户访问稳定返回 403，非数字 legacy account identity 不再被猜测映射。
- `SubmitApprovedPlanUseCase` 保留 not-found/status/expiry 前置校验，但在当前未接正式 Evidence 时固定失败关闭，`APPROVED` 计划也不能再从 API 获得 `execution_handoff`。该链原本没有 Broker 真调用，因此本批不撤销订单或外部交易，只关闭了一个语义上过度声明的 handoff 发布面。
- create 与 approve 仍保留用于生成/审核不可执行计划；旧 Decision Rhythm plan 链与 `AdvisorOrderIntent` live-draft consumer 未在本批改动。

仍未完成：

- 只有在 canonical payload hash、contract family、decision/portfolio/target/prices/market facts/policy version、正式 Operator Spec/Envelope/Track Record 与调用者授权全部 exact 重验后，submit 才能恢复。
- `DECISION_SNAPSHOT_REQUIRED` 仍默认 false；创建和审批目前只是计划生命周期，不是 Evidence 硬门禁。完整 Django API/component 因当前环境缺 Django 未执行，跨账户与 blocked handoff API 测试已写、待合格 runtime 复跑。

本阶段验证：

- 纯 Application submit gate `4 passed`；Decision write freeze `10 / 54 / 15 / 25 / 23 / 32`；architecture delta `0` boundary/audit violations；Application standalone strict mypy `0 issues`；Black/isort/diff-check 通过。

### 2026-08-13：Advisor intent → Broker live draft consumer 硬阻断

已完成：

- 代码核对确认 `AdvisorOrderIntent` 会经当前服务端 advisor sheet、`PreviewOrCreateAdvisorLiveOrdersUseCase` 与 `CreateLiveOrdersFromAdvisorExecutionPlanUseCase` 转成 Broker live-order draft；此前只做 preview digest、服务端 risk recheck 和后续审批，未绑定 Operator Spec/Envelope/Track Record/EvidenceSummary。
- 保留只读 preview，但固定发布 `commit_allowed=false`、`display_only=true`、`must_not_use_for_decision=true`、`must_not_execute=true` 与稳定 blocker `advisor_order_intent_evidence_not_integrated`；Classic Broker workbench 在该标志为 false 时不再展示“确认生成草稿”按钮。
- commit 分支在调用 order creator 前返回稳定 conflict；底层 plan converter 同样独立 fail closed，内部直调也不能绕过。原先无效 `valid_until` 静默补 30 分钟的路径不再可达，未用伪造窗口冒充有效证据。
- inventory 将 `AdvisorOrderIntent` 从 `not_evidence_integrated_legacy_ungated` 改为新的、如实的 `not_evidence_integrated_hard_blocked`；分母仍为 `65/14/53/18`，没有把 hard block 声称成 Evidence integrated 或 legacy wrapper。

仍未完成：

- 只有在完整 advisor payload、source recommendation/signal、risk/data-as-of、有效期、账户授权与正式 Evidence graph 全部 exact 绑定并在 consumer 重验后，才可恢复 draft commit。
- 本批不改变普通 advisor sheet 阅读，也不处理旧 Decision Rhythm approval/read 链。Django component/API 仍需在项目声明的 Django runtime 复跑；当前环境只有纯 Application/inventory 测试可执行。

本阶段验证：

- 纯 Application + inventory `17 passed`；Evidence inventory `65 / 14 / 53 / 18`；Decision write freeze `10 / 54 / 15 / 25 / 23 / 32`；architecture delta `0` boundary violations；Black/isort/py_compile/diff-check 通过。
- 项目 mypy 配置在当前环境因缺 `mypy_django_plugin` 不能完整加载；隔离 strict 对该历史大文件仍报告 5 个未改区域的 `no-any-return`，增量脚本报告 `0 regressions`，但不把它记为全文件 strict 通过。Django component/API 同样因当前环境缺 Django 未执行。

### 2026-08-13：Broker connection current-data 与执行时钟硬闸

已完成：

- 核对确认正式 `/api/broker-execution/connections/` 与 SDK 原先直接发布 persisted `qmt_connected/status/last_heartbeat_at`，而 90 秒 freshness 只存在于 admin onboarding；更关键的是 `last_heartbeat_at` 是服务端接收时间，不是 Agent 源观测时间，旧值可被包装成当前连接。
- Agent heartbeat `1.0` 新增可选、timezone-aware `observed_at`；服务端在既有 `health_snapshot` 分别保存 `source_observed_at` 与 server `received_at`，无需 migration。旧 Agent 缺该字段仍可被接收，但 effective connection 固定 degraded，不能领取订单。
- 新增纯 Domain 双时钟规则与 Application typed projection：source 与 receipt 必须有时区、顺序为 `source <= receipt <= evaluated` 且都在 90 秒窗口；缺失、未来、过期、inactive、offline 或 reported disconnected 均发布稳定 blockers、`must_not_use_for_decision=true`、`must_not_execute=true`，且不覆盖原始时间。
- connections 与 QMT onboarding 共用同一投影；SDK 继续一跳原样保留 current markers。普通用户连接响应不再暴露 owner/binding `user_id`，admin credential 投影仍保持原权限边界。lease 在读取数据库状态后再次重验同一 source/receipt 时钟规则，手工或陈旧 `qmt_connected=true` 不能绕过。
- 新增 `broker_execution.connection_status` current-data 机器合同；总数升为 `48 surfaces`。Broker MCP connection/read 能力继续 `enabled=false`，本批没有据 HTTP/SDK 修复提前恢复 MCP identity/permission/Evidence 语义。

仍未完成：

- 完整 Django component/API 需要项目声明的 Django runtime 复跑；生产 Windows Agent 也必须升级后重新产生 fresh heartbeat，不能把兼容接收旧 heartbeat 当成连接验收。
- connection 只是运维 current-data 合同，不是 EvidenceSummary，也不授权决策/执行；Broker overview/order/reconciliation/audit MCP 仍须各自 typed projection、权限与 Evidence 收口。

本阶段验证：

- pure connection/Agent `30 passed`；SDK `4 passed`；MCP disabled assertion `1 passed`；current-data guard `48 surfaces`；architecture delta `0` boundary violations；新 Domain/Application strict mypy `0 issues`；Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Broker overview 完整 current-evidence READY 门禁

已完成：

- 代码复核确认原 `build_overview()` 会用任一持久化 `online + qmt_connected` Agent 把页面判为 READY，并以查询时 `generated_at` 包装结果；它没有验证 active binding 的逐账户覆盖、Broker snapshot 新鲜度或 latest reconciliation 是否精确绑定同一 snapshot。
- Infrastructure 现在只返回 actor-scoped 原始事实：active bindings、最新 snapshot、最新 reconciliation 及其 snapshot identity、开放订单、kill switch、告警、差异和 daily report 原 `generated_at`；它不再生成 `today_readiness`，查询时钟也不再冒充源观测时钟。
- 新增纯 Application typed projector。READY 必须同时满足：每个 active binding 的 auto execution 开启、对应 Agent 双时钟连接 fresh、snapshot 在该 binding SLA 内、completed reconciliation 精确绑定同一 snapshot id 与 captured time、开放订单未过期且非异常状态，以及无 kill switch、P0/P1 alert、execution exception 或 reconciliation difference。
- 输出固定发布 `evaluated_at/evidence_complete/must_not_use_for_decision/must_not_execute/blocker_codes/source_times`；STOPPED 优先于 OFFLINE，其他阻断为 REVIEW。SDK 保持单次 GET 原样保留这些字段；`broker_execution.read.overview` MCP 继续 `enabled=false`，本批没有恢复最终调用者身份或 EvidenceSummary。
- 单账户 live-execution readiness 也补用相同 source/receipt 90 秒规则；旧 `qmt_connected=true` 不能在 overview、resume evidence 或 Agent lease 任一处绕过 freshness。

仍未完成：

- 这只是 Broker operational current-evidence，不是正式 Evidence Envelope、Track Record 或 Risk Authorization；order/reconciliation/audit typed summary 和四节点 receipt 重验仍未完成。
- 完整 Django component/API 仍需在项目声明的 Django runtime 复跑；生产 Windows Agent、snapshot 与 reconciliation 必须重新产生真实 fresh evidence，不能用本地构造测试替代。

本阶段验证：

- overview/connection 纯测试 `29 passed`；SDK `4 passed`；MCP disabled assertion `1 passed`；current-data guard `49 surfaces`；新增 Application strict mypy `0 issues`，Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Broker live-order 四节点 Evidence 硬暂停

已完成：

- 代码核对确认 Advisor HTTP create 已被上一批阻断，但内部 `CreateLiveOrderFromExecutionPlanUseCase` 与 repository 仍能创建 `WAITING_APPROVAL`；更严重的是存量或旧批次订单可仅凭普通 risk JSON、recommendation IDs 与 approval digest，经 approve → Agent lease → submitting 进入实盘。approval digest 只证明 14 个订单字段未漂移，不包含 Operator Spec、Envelope、Track Record、Risk Authorization、Portfolio attestation 或 owner-bound plan receipt。
- 新增唯一 fail-closed gate，在 create、approve、lease、submitting 四个 advancement checkpoint 双层阻断 Application 和 repository 直调；不接受配置、环境变量或 warning-only bypass。Agent poll 返回稳定空订单与 blocker，闸上线时遗留 lease 也不能 ack 到 submitting。
- approve preview 继续只读但固定 `commit_allowed=false/display_only/must_not_execute`；reject、cancel、kill switch、对账和所有只读面保持可用。MCP `broker_execution.approve.order` 标记 disabled；TUI 保留 approval/advisor preview 与风险降低操作，移除 approve/advisor-draft commit action；SDK ABI 保留，由后端稳定 409。
- 新增独立机器 guard 并接入 consistency-check，冻结 4 个 checkpoint、MCP disabled 与 TUI commit=0；任何 checkpoint marker、disabled 状态或风险降低 action 漂移都会阻断 CI。

仍未完成：

- 本批是明确的实盘新提交功能收缩，不是正式 Evidence 集成。恢复 create/approve/lease/submitting 前，必须先实现 owner-bound append-only Evidence、Risk Authorization、exact plan/attestation receipt，并在四节点做 current/exact 重验；不得用现有 caller-controlled JSON 或 digest 冒充。
- 已存在 SUBMITTED/PARTIALLY_FILLED/FILLED 的订单不回退、不自动撤单；风险降低与对账继续工作。完整 Django API/component/critical/fake-Agent runtime 因当前环境缺 Django/Celery 未运行，必须在合格项目 runtime 补验状态零副作用与稳定 409。

本阶段验证：

- 纯 hard-gate/advisor/Agent/domain 聚合 `39 passed`；MCP disabled/catalog `5 passed`；Broker gate、decision-write freeze、MCP Evidence freeze、全仓 architecture scan（2661 files / 0 violations）、Black/isort/py_compile/diff-check 通过。项目 mypy 因缺 `mypy_django_plugin` 仅证明增量 regressions 为 0；完整 broker_execution unit 与 TUI component 因当前环境缺 Celery/Django 未执行，不计为通过。全局 governance consistency 仍被本批未修改的既存 `core/integration` infrastructure import 基线差异（0→4）阻断，未通过抬高基线掩盖。

### 2026-08-13：Broker order detail legacy Evidence 只读收口

已完成：

- 抽出唯一 canonical `approval_snapshot_for_order`，审批、Agent ACK 与读取投影共用同一 14 字段 digest；读取时重新构造 snapshot、重算 lowercase SHA-256，并要求 legacy Evidence `output_content_hash` 与 persisted approval digest exact 一致。
- 新增 frozen Application 投影：无论 approval Evidence 是否可验证，结果均固定 `display_only / must_not_use_for_decision / must_not_execute`。过期、缺字段、金额不闭合、非 canonical risk JSON、source IDs 或 digest 漂移均发布稳定 blocker，绝不升级为执行授权。
- 将生命周期可迁移性与当前 actor 的角色/账户授权拆成两个字段；raw `risk_snapshot` 仅发布 content hash，Broker event 任意 payload 被删除，events/fills 采用字段白名单，畸形 transport 行发布 blocker。
- SDK 保留上述 markers；MCP 仅恢复 `broker_execution.read.order_detail`，handler 再做 closed projection，output schema 每层 `additionalProperties=false`。overview、order catalog、connection、reconciliation、audit 5 个动态读继续 disabled；18 个 P0 面仍明确 `integrated=0`，本项只标记 `legacy_evidence_wrapped_display_only_native`。

仍未完成：

- legacy wrapper 没有 activated Operator Spec、Track Record、Risk Authorization 或 owner-bound plan receipt，不能用于 approve/lease/submitting，四节点硬暂停保持不变。MCP 使用配置 SDK 身份，`actor_authorization` 只说明该服务身份的账户权限，不代表最终自然人授权。
- 完整 Django API/component、Celery Application boundary 和 core-only MCP dispatcher 因当前 runtime 缺 Django/Celery/MCP 包未完整执行；HTTP 账户隔离和零写入需在合格项目 runtime 复验。audit 任意 before/after、reconciliation expected/actual、order catalog 动态 risk 仍按下一阶段分别收口。

本阶段验证：

- Broker projector/domain `32 passed`；SDK `5 passed`；MCP closed projection `5 passed`；MCP semantic guard `9 passed`，统计 `18 / disabled 6 / integrated 0`；全仓 architecture scan（2662 files / 0 violations）、Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Broker audit 动态字段白名单与脱敏

已完成：

- 代码核对确认 audit repository 原样返回 `before/after/reason/request_id/actor/resource_id`，且 Agent command `result` 为外部 Agent 可控任意 JSON；`view` 角色覆盖 analyst/read_only，因此仅禁用 MCP 不能保护 HTTP、SDK 与 Classic read。
- 新增纯 Application audit projector：按固定 action/resource family 投影有界状态字段，未知 writer 或未知 command type 只返回元数据与稳定 blocker。动态 command 明确登记 cancel/full_sync × completed/failed，不使用前缀泛化放行。
- 统一删除 actor id/username、resource/request id、reason、IP、UA、credential、token/secret/password、risk snapshot、approval digest、recommendation IDs、broker order id 与完整 Agent result；订单 audit 只留状态、版本、成交数量及状态时间，其他 family 只留最小安全状态。
- QueryService 使用单一 aware 评估时钟，顶层及逐事件固定 `display_only / must_not_execute / must_not_use_for_decision`；SDK 原样保留这些 redaction markers。MCP audit 继续 disabled，本批不改变 Evidence inventory 的 `integrated=0`。

仍未完成：

- 本批是 legacy audit read-model 安全收窄，不是正式 Evidence/Audit receipt。14 个 writer 的 AST/schema 机器清单尚未独立固化，后续新增 writer 仍需在 CI 增加 closed-world guard；完整 Django HTTP/component 与 Classic 页面需合格 runtime 回归。
- reconciliation 与 order catalog 仍有任意 JSON/权限语义待收口；正式 Evidence/Risk/plan receipts 与四节点 exact current 重验仍未完成。

本阶段验证：

- audit projector `6 passed`；Broker SDK `6 passed`；MCP semantic freeze PASS（18 / disabled 6 / integrated 0）；全仓 architecture scan（2663 files / 0 violations）、Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Broker reconciliation typed current-evidence 只读收口

已完成：

- 将 repository 原样 `summary/expected/actual` JSON 收敛为纯 Application typed projector；固定 run status、四维 dimension、P0/P1 severity 与 difference status，未知/legacy值整批 fail-closed，不发布局部 raw JSON。
- 保留 snapshot source time 并校验 `snapshot_captured_at <= started_at <= completed_at <= evaluated_at`；查询时钟仅用于评估，不回填源时点。run completion、resolution 与 difference status 必须互相一致。
- 强制四维计数、`summary.difference_count` 与实际差异条数守恒，`p0_auto_stop` 与 P0 差异精确一致，`(dimension,difference_key)` 唯一；expected/actual 仅允许 order/fill/cash/position 各自精确字段与有限 Decimal 文本。
- 计算 canonical content hash；resolved summary 只保留 resolution identity，不发布 operator reason/resolved_by。顶层及逐 run 固定 `display_only / must_not_execute / must_not_use_for_decision`，SDK 原样保留。MCP reconciliation 继续 disabled，`integrated=0` 不变。

仍未完成：

- 这是 operational reconciliation display-only projection，不是正式 Evidence Envelope/Track Record/Risk Authorization。生产 `total_asset` 目前只进入 run_key、未形成差异比较；Overview 尚未显式绑定 snapshot row `created_at`，需后续 source contract 扩展。
- Django HTTP/component、真实 PostgreSQL run/difference 持久化与并发 resolution 未在当前 runtime 验证；MCP 恢复需另批 closed schema/handler 与最终调用者身份语义，不能因 typed 投影自动启用。

本阶段验证：

- reconciliation projector `6 passed`；Broker SDK `7 passed`；MCP semantic freeze PASS（18 / disabled 6 / integrated 0）；全仓 architecture scan（2664 files / 0 violations）、Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Broker order catalog actor-aware display-only 收口

已完成：

- 将订单目录从 30 字段动态 payload 收敛为有界摘要，移除 agent、approval digest、broker order id、failure message、source IDs 与 raw risk JSON；仅保留 canonical risk content hash，详细审批/事件/成交身份留在已治理的 order detail。
- 严格校验 UUID、16 态生命周期、BUY/SELL、LIMIT、有限 Decimal、positive version、aware datetime，并要求 `created <= updated <= evaluated`、submitted/expires 不早于 created、filled quantity 不超过 quantity；任一异常关闭全部 effective action。
- 将旧 `action_availability` 明确保留为 lifecycle-only 兼容别名，同时新增 lifecycle、actor role/account authorization、Evidence gate 与 effective action 四层。approve 因正式 receipt 未集成固定 false；reject/cancel 仅在生命周期、角色与账户授权同时允许时可见。
- QueryService 使用单一 trusted now，并按 `(account_id, action)` 缓存访问检查，权限查询上限由逐行 3N 收敛为每账户 3A。顶层/逐行均固定 display-only/must_not_execute，MCP order catalog 继续 disabled。

仍未完成：

- `has_account_access` 当前对 reject 只要求任意 active grant、没有独立 can_reject 字段；本批忠实投影现有策略，未擅自改变产品授权模型，需后续 RBAC/账户授权决策。目录 API 对未知 status 从静默空结果改为 400，是有意 fail-closed 兼容变化。
- 正式 Evidence/Risk/plan receipts 未完成，approve/create/lease/submitting 总闸保持关闭；Django API/component、Classic 模板 effective_actions 切换与固定 query-count 验证待合格 runtime 补验。

本阶段验证：

- catalog + order-detail 纯测试 `40 passed`；Broker SDK `8 passed`；MCP semantic freeze PASS（18 / disabled 6 / integrated 0）；全仓 architecture scan（2665 files / 0 violations）、Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Broker execution authorization 本地合同冻结

- 新增 Broker Domain 自有、零跨 App import 的 exact authorization artifact ref、scope 与 inactive receipt contract；固定绑定账户、Portfolio plan/approval、Broker approval snapshot、Research output/envelope/operator/track record、Risk authorization、policy benchmark 及五方有效期。
- scope 与 receipt 使用 UTF-8 canonical JSON、UTC `Z` 和 lowercase SHA-256；订单 identity 必须是 canonical UUID，Portfolio/Risk/Research/Broker owner 与 artifact type 不可替换，最终有效期只能等于所有上游窗口的最小值。
- receipt contract 只接受 Evidence 与 Risk 都为 `execution_eligible` 的结构，但 `activation_available=false`、`must_not_execute=true` 固定不变；相邻 supersession 必须绑定 exact previous hash、同账户/订单并推进 server clock。当前不提供 issuer、provider、store、API 或 consumer，四节点总闸继续保持关闭。
- 代码核对确认尚缺两个 owner 真源：Portfolio Domain 的 plan content hash/approval receipt/exact provider，以及 Risk Center 的 account+plan+order scoped authorization。现有 Portfolio Infrastructure hash、Research legacy summary、Broker approval digest 与 Risk Operator Spec approval 均不能冒充这些真源。

未完成：

- Portfolio `TransitionPlanApprovalReceipt`、Domain canonical plan hash 和 exact/PIT provider；Risk Center `BrokerOrderRiskAuthorization`、policy/actor/validity/supersession 与 append-only first-winner ledger。
- Broker Application 双读签发/重验、append-only repository、四节点 current/exact 校验与存量订单 `DECISION_REVIEW_REQUIRED` 迁移；没有这些交付前不得切换 `broker_order_evidence_integrated()`。

验证：

- 本地 contract + 既有 hard-gate 聚合 `22 passed`；standalone strict mypy `0 errors`；全仓 architecture scan（2666 files / 0 violations）、Black/isort/py_compile/diff-check 通过。未新增 Django/数据库面，因此本阶段没有声称 PostgreSQL first-winner 或生产授权证明。

### 2026-08-13：Portfolio canonical plan integrity 与 inactive approval 合同

- 将 `portfolio_canonical_v1` 的 payload、JSON bytes 与 SHA-256 算法从 Infrastructure 提升为 Portfolio Domain 唯一真源，严格保持既有字段、数组顺序、Decimal 字符串、原时区 offset、`ensure_ascii` 等历史字节语义，避免对存量 canonical 行做无声明 schema 漂移。
- Portfolio repository 保存复用 Domain hash；get、idempotent replay 和 approve 会从当前 ORM payload 重建 Domain 并与 stored `immutable_payload_hash` 做 exact compare，空 hash、失配或旁路篡改均失败关闭，不做静默回填。生命周期 status 变化不进入 immutable payload hash。
- 新增 strict receipt-eligibility 校验与 Portfolio-owned `TransitionPlanApprovalReceipt`：绑定 plan/version/hash、账户、decision snapshot、human staff actor、server time 与 plan expiry；但 `execution_permission=inactive`、`must_not_execute=true` 和稳定 blocker 固定不变，不接 ORM/API/submit/Broker。
- `portfolio_canonical_v1` 仍没有 plan identity、decision/portfolio/target snapshot 内容哈希及完整 policy artifact；后续如补这些字段必须新增 canonical v2 family/decoder，不能覆盖 v1 算法。存量空/错 hash 只能审计后重建新 plan，不得给当前可变行补背书。

未完成：

- Portfolio approval append-only ledger、可信 actor/clock Application command、exact/PIT provider、两人复核与 PostgreSQL first-winner；现有 caller-less approve 不自动签发 receipt。
- Risk Center order authorization、Broker issuer/revalidator 和四节点 exact current 校验仍未实现，Portfolio submit 与 Broker 总闸继续关闭。

验证：

- Domain integrity/receipt 与 submit hard-gate 聚合 `15 passed`；standalone strict mypy `0 errors`；全仓 architecture scan（2667 files / 0 violations）、Black/isort/py_compile/diff-check 通过。模块循环扫描确认本批无新增跨 App import，但共享工作区当前既存总边数/预算和 `account,portfolio,simulated_trading,strategy` cycle 仍超 allowlist，未通过抬高基线掩盖。

### 2026-08-13：Risk Center Broker order authorization Domain 合同

- 新增 Risk Center owner 的 `BrokerOrderRiskScope`、双人 approval subject 与 authorization record；零跨 App import，独立于现有只服务 Operator Spec activation 的审批 capability，避免把 Research spec approval 语义冒充订单风险授权。
- scope 精确绑定 account、Broker execution scope hash、Portfolio plan/hash/approval、order identity/version/hash、Risk policy id/version/hash 及四方有效期；订单 ID 必须 canonical UUID，所有 hash 只能是 lowercase SHA-256，本地 scope hash 对任一上游替换都会变化。
- subject 必须由 human staff 请求，record 必须由另一名 human staff 批准，同时比较 actor ID 与 user ID 禁止自批；有效期只能等于 plan/order/policy/execution scope 的最小值，PIT 采用 `issued_at <= as_of < valid_until`。
- authorization authority/capability/version 与 `permission_cap=execution_eligible` 固定；相邻 supersession 必须绑定 exact previous hash、同账户/订单并推进时钟。若风险不允许则不得签发 authorization，不能生成降级记录后仍被 Broker 当许可。

未完成：

- Risk policy artifact/provider、ID-only register/approve/get-exact Application、可信 server clock/双读防漂移、append-only subject/record ledger、current-head first-winner/CAS 与 PostgreSQL 并发证明。
- 本 Domain contract 没有签发或激活运行面；Broker receipt issuer/revalidator 与四节点 exact current 校验未接入，`broker_order_evidence_integrated()` 继续为 false。

验证：

- Risk contract、Broker inactive contract 与 hard-gate 聚合 `33 passed`；standalone strict mypy `0 errors`；全仓 architecture scan（2668 files / 0 violations）、Black/isort/py_compile/diff-check 通过。

### 2026-08-13：Risk Center Broker order authorization Application 合同

- 增加 consumer-owned Broker execution scope 与 Risk policy typed provider DTO/Protocol；Risk Application 不导入 Broker/Portfolio/Research Infrastructure，跨 owner 适配留在 composition root。
- subject register 与 authorization approve 写命令只接受 ID/version，刻意不接 caller `as_of`、account、hash、permission 或有效期；两个写用例在私有 repository atomic 内只取一次 Risk server clock，所有 scope/policy/actor/permission/validity 均来自可信 provider 和构造注入。
- register 对 Broker scope 与 Risk policy 各做首末双读、账户闭合和 current-head predecessor 绑定；approve 除双读 subject 外还重新双读并重建当前 scope/policy，注册后任一上游被替换、过期或 supersede 均失败关闭。
- repository Protocol 固定 immutable subject/authorization first-winner、logical account+order head、append CAS 与 exact identity/hash/PIT read；read facade 返回后再次重放 Domain hash、identity、version和 `issued <= as_of < valid_until`。

未完成：

- 本批使用 pure fake repository/provider 验证合同；尚无 Risk policy生产真源、Broker scope composition、Django append-only model/codec/repository、人工接口或 PostgreSQL current-head 并发 CAS。
- Domain 追加 `execution_scope_id` 作为 ID-only selector，不改变 Broker总闸；没有上述真实 owner/provider与持久化前仍不能签发生产 authorization。

验证：

- Risk Domain/Application、Broker inactive contract 与 hard-gate 聚合 `39 passed`；standalone strict mypy `0 errors`；全仓 architecture scan（2669 files / 0 violations）、Black/isort/py_compile/diff-check 通过。

#### Application first-winner/current-head 复核修正

- 后续只读验收发现首版 register/approve 会用新 server clock 重建 candidate，导致跨时钟幂等 replay 不可达；现改为 winner 存在时先重放 exact type/hash 与稳定 selector/source/actor，再直接返回 immutable first winner，只有新 identity 才构造新 candidate。
- approve 现在强制 repository subject first winner 与 trusted provider subject 完全相等；缺失或替换均拒绝，不能只信外部 subject provider。
- 保留历史 exact identity/hash/PIT read，同时新增 current-for-scope closed selector：逐项核对 execution scope/account/plan/order/policy identity/hash，并要求返回 record 等于该 cutoff 的 logical current head；已 supersede 但未过期的旧 authorization 不再可被执行 consumer 复活。
- 新增跨时钟 subject/approval replay、缺失 persisted subject 和 superseded old head 回归；Risk+Broker gate 聚合更新为 `41 passed`，全仓 architecture scan 为 2671 files / 0 violations。持久化 CAS 仍未完成，当前继续不可用于生产签发。

### 2026-08-13：Risk Broker authorization append-only persistence

- 新增 Risk Center 独立私有 UOW/token 与 exact insert claim、subject/authorization 两张 append-only ledger、strict codec 和 repository；不复用 Operator Spec approval 的私有写 authority，Model/QuerySet/bulk/raw/delete/update 旁路均 fail-closed。
- subject 与 authorization 同时保存 canonical payload、identity hash、content hash、冗余 headers 与 ledger header hash；restore 会重建 Domain 并逐项比对，payload/header/FK/clock/authority 任一篡改都按 corruption 失败。
- DB 约束固定单 root、每个 predecessor 单 successor、subject 单 authorization，以及 owner/capability/permission/human-staff/clock；repository append 在写前核对 logical current head，并把 expected predecessor 作为 CAS 语义，陈旧 predecessor 不得形成 fork。
- 新增 `0008_broker_order_risk_authorizations` schema-only/zero-seed migration，不回填或伪造任何历史订单授权；Risk model export 已接入，但无 Admin/API/composition/人工入口。

未完成与验证边界：

- component 测试已覆盖 exact append/PIT/codec、私有 UOW/mutation guard、successor/current head、future/tamper、schema-only 与 stale predecessor，但当前默认及 bundled Python 均缺 Django/pytest-django，未执行测试断言或 migration forward/reverse；不能将其计为通过。
- Black/isort/py_compile/diff-check、standalone mypy（ignore missing Django；codec/repository 0 issues）与全仓 architecture scan（2672 files / 0 violations）通过。PostgreSQL first-winner真实并发、Risk policy/scope production provider、人工审批与 Broker consumer仍未完成，总闸继续关闭。

#### Persistence chain/current-head 复核修正

- 只读验收发现首版 `get_current_head` 先按冗余 account/order header 过滤，坏 successor 的 selector header 被旁路篡改后可能从查询消失并复活旧 head；同时只找“未被引用”不足以证明单根、前驱存在、同链、时钟前向和全记录可达。
- current-head 现先 restore cutoff 前全部 authorization 并验证 payload/header seal，再按 Domain scope identity 分链；强制恰好一 root、每个 predecessor 存在于同链、issued clock 严格递增、无 fork/cycle/disconnected，最后才返回唯一 logical head。
- append 捕获 IntegrityError 后改为用 authorization identity/content/subject 四个唯一锚点恢复，并且只有 restored record 与 exact candidate 完全相等才允许幂等返回；不再按 ID 返回另一 first winner，也不再重新读取漂移 server clock。
- restore 增加 `persisted_at >= recorded_at`，并新增 successor selector header 直改与 stale predecessor 测试。静态验证、standalone mypy 和 architecture（2673 files / 0 violations）通过；Django component 与真实 PostgreSQL 双事务 race 仍未执行，故不能宣称数据库并发已验证。

### 2026-08-13：Portfolio inactive plan approval Application workflow

- 新增 Portfolio Application-owned `TransitionPlanDefinition` 与 inactive subject，精确封存 canonical-v1 plan content hash、账户、decision snapshot、human actor、server clock 和 plan expiry；所有对象固定 `execution_permission=inactive` 与 `must_not_execute=true`。
- register/approve 写命令只接受 subject/plan/receipt 的 ID/version，不接 caller hash、account、actor、clock 或 permission；actor由认证 composition构造注入，repository提供单一 server clock与私有 atomic。
- register 对 trusted plan provider 双读并核 persisted subject first winner；approve 对 persisted subject和绑定 plan各双读，禁止相同 user自批，跨 server clock重试直接返回原 subject/receipt first winner，不重建时钟漂移candidate。
- exact read按 receipt identity/hash/PIT重放 Domain hash与inactive状态；旧 `ValidateTransitionPlanUseCase`、repository approve、plan status/approved_at、Submit hard-gate和Broker均未接线，避免 caller-less legacy approval 被包装成 authoritative receipt。

#### 2026-08-13 subject seal 与两人复核修正

- 只读复核发现首版 receipt 只绑定 plan，没有把 persisted subject 自身封入 hash；现已补入 subject id/version/content hash、requester identity，并在 winner replay 与 exact read 中同时闭合 subject 和 plan selector，阻断同一 plan 下多 subject 互换。
- 两人复核从只比较 `user_id` 修正为 `actor_id` 与 `user_id` 任一相同均拒绝；register/approve winner replay 只允许原 requester/approver，其他 actor 必须走独立 exact read，不能借 approve 命令取回他人的 first winner。
- receipt 显式封存 `plan_status_at_issue=APPROVED`，但 canonical-v1 plan hash 有意不含可变 status，因此该字段只是签发时的 inactive 审计快照，不是内容寻址的 lifecycle approval event，不能用于恢复 submit/Broker 执行。

未完成与验证：

- 本批仍只有 Domain/Application 与 pure fake；Portfolio exact Django provider、独立private-UOW subject/receipt ledger、codec/migration、人工接口或PG first-winner另批提交。
- subject-seal 专属 Domain/Application `19 passed`；standalone strict mypy `0 errors`；architecture scan（2677 files / 0 violations）、Black/py_compile/diff-check通过。receipt保持inactive；缺 owner 的内容寻址 lifecycle approval event，不能满足Broker plan approval ref。

### 2026-08-13：Portfolio inactive approval append-only persistence

- 新增 Portfolio 独立 private UOW/token 与 exact insert claim、subject/receipt 两张 append-only ledger、strict canonical codec、first-winner repository 与 exact identity/hash/PIT reader；Model/QuerySet/bulk/raw/delete/update 旁路均 fail-closed。
- receipt 的 OneToOne 记录命名为 `subject_record`，与业务 `subject_id` 分离；ORM header/ledger seal 冗余核验 subject id/version/content hash、requester、approver、plan selector 与 `plan_status_at_issue`，防止 FK/JSON/header 任一替换。
- exact definition provider 只接受 canonical、stored hash exact、当前 status=APPROVED 且 `approved_at <= as_of < expires_at` 的 plan，并以 authoritative `approved_at` 作为 definition recorded_at；不再把 plan 创建时间洗成审批发生时间。
- migration `0017_transition_plan_inactive_approvals` 仅有两张表、约束与索引，AST 确认无 RunPython/RunSQL，zero-seed；旧 approve/submit、人工 HTTP 与 Broker 未接线。

未完成与验证：

- Django 5.2 最小 app registry/model check 证实 receipt 同时存在 `subject_record` 与业务 subject identity 字段；SQLite schema-editor exact append/codec/PIT 往返 `True / 1 subject / 1 receipt`。两项非 ORM production 文件 standalone strict mypy 通过，architecture 2677 files / 0 violations，Black/compileall/diff-check通过。
- 完整 `manage.py check/makemigrations --check` 被该 Django 5.2 环境缺 Celery 阻断；标准 pytest-django component、migration forward/reverse、PostgreSQL first-winner 并发和人工 actor composition 未验证。status 仍不是 canonical-v1 content hash 的一部分，receipt保持inactive，不能供执行授权。

### 2026-08-13：Risk-owned Broker execution policy Domain contract

- 代码复核确认现有 `AccountRiskPolicyModel`、floor/template/exception 与 `ResolvedRiskPolicy` 均为可变/即时对象，没有 exact version、统一 PIT source snapshot、content hash、activation/validity、supersession 或 execution-eligible authority；禁止用 `updated_at`、audit JSON 或临时 resolved dict hash 冒充 trusted provider。
- 新增 Risk-owned `BrokerOrderExecutionRiskControls` 与 `BrokerOrderExecutionRiskPolicy`：完整绑定 7 项有限 Decimal 风险比例、exact bool、排序唯一 exclusions、账户、source snapshot identity/hash、recorded/activated/valid clock、predecessor 与固定 authority/schema/permission。
- canonical JSON 使用 UTC `Z` 与 Decimal normalized text；任一 source/control/clock/authority 替换均改变 hash，successor必须绑定同账户 exact predecessor并推进 recorded clock。
- 本批只有 Domain contract 和 pure tests，不读现有 mutable policy表、不提供 active provider/ledger/API；zero-seed状态继续让 `RegisterBrokerOrderRiskAuthorizationSubject` 返回 unavailable，Broker四节点总闸不变。

未完成与验证：

- 新 Domain + Risk authorization + Broker inactive contract/hard-gate 聚合 `48 passed`；standalone strict mypy `0 errors`，architecture 2678 files / 0 violations，Black/isort/diff-check通过。
- 待独立实现 source snapshot、ID-only activation、append-only policy ledger/codec/current-head provider与PG并发；生产 source bundle 必须闭合 floor/template/account override/有效global+account exceptions，fallback未持久化时必须阻断。

### 2026-08-13：Broker order approval owner artifact

- 新增 Broker Domain 自有的 immutable approval artifact，精确绑定 canonical `client_order_id` UUID、positive order version、完整 `OrderApprovalSnapshot`、既有 `build_approval_digest`、账户、server-authenticated 批准人 identity/user/role、批准时点和 snapshot expiry。
- snapshot 进入工件前重验 exact enum/tuple/finite Decimal/canonical risk JSON、`estimated_amount == quantity * limit_price`、非空 recommendation lineage 及 aware validity；任一订单事实、source、actor、clock 或 seal 漂移都会改变 content hash 或失败关闭。
- 工件固定 `activation_available=false`、`must_not_execute=true`，不读取 ORM、不接 Application/四节点 consumer，也不把旧 approval digest 冒充 Portfolio、Research、Risk 或最终 Broker execution authorization。

未完成与验证：

- append-only artifact ledger、exact/PIT provider、Broker pre-risk scope、跨 owner composition 和 issuer 尚未实现；create/approve/lease/submitting 总闸保持关闭。
- 专属纯 Domain `21 passed`；standalone strict mypy、Black/isort/py_compile/diff-check通过。标准项目 pytest/mypy 仍受当前环境缺 Playwright 与 mypy Django plugin 阻断，本批没有声明 Django/PostgreSQL/生产验证。

### 2026-08-13：Risk execution policy Application workflow

- 新增只接受 policy/source ID+version 的激活命令；账户、controls、source hashes、validity、actor、server clock与predecessor全部来自可信 source provider、认证 composition与private repository，不接受调用方提交的内容或权限。
- source snapshot 不只封最终 controls，而是按固定顺序精确绑定 floor、template、account override、global exceptions、account exceptions 五类 component identity/version/hash/knowledge clock；snapshot validity 必须等于所有 component 窗口交集，fallback 或缺项不得伪造成完整 source。
- 激活在单一 server cutoff 对 source 首末双读，repository logical account head 决定 predecessor；successor重放 Domain相邻链规则，immutable activation seal另行绑定 human-staff actor与policy hash。相同identity跨时钟只允许原actor取回first winner。
- 提供给 Risk authorization 的 consumer-owned projection 只有在 exact policy identity仍为cutoff下logical current head且active时才返回；已supersede但未过期的旧policy返回None，expired head也不会回退旧版本。

未完成与验证：

- 本批只有Application协议与pure fake；五类source snapshot的Django生产器、append-only policy ledger/codec/repository、composition与真实PG root/successor race尚未实现，不能签发生产Risk authorization。
- Risk policy、Risk authorization、Broker inactive contract与两层hard-gate聚合 `66 passed`；standalone strict mypy、Black/isort/py_compile、architecture（2680 files / 0 violations）与diff-check通过。标准项目pytest/mypy环境缺项仍按未验证记录，Broker总闸继续false。

### 2026-08-13：Broker order approval artifact append-only persistence

- 新增 Broker 独立 private-UOW/exact insert claim、append-only ORM model、strict canonical codec与repository；identity、canonical order+version、identity/content hash任一唯一锚出现不同first winner即冲突，不用 `ignore_conflicts` 或update-on-conflict吞掉分叉。
- canonical payload与owner/type/schema、账户、order version、approval digest、actor identity/user/role、批准/有效/记录时钟、identity/content hash及ledger header seal逐项复核；QuerySet/Model/bulk/raw/update/delete路径均失败关闭。
- exact reader只提供 historical PIT：同时要求 `recorded_at <= as_of` 与 `approved_at <= as_of < valid_until`，不会把artifact非空或未过期解释为current execution authorization。migration `0008_order_approval_artifact`只有CreateModel，禁止RunPython/RunSQL且zero-seed。
- Django 5.2最小schema-editor往返发现并修复 `auto_now_add`数据库墙钟与authoritative repository clock漂移：`persisted_at`现由private repository显式写入并必须exact等于recorded_at；实测 `Django 5.2.10 / 1 row / exact PIT True / must_not_execute True`。

未完成与验证：

- 纯Domain回归 `21 passed`，strict codec roundtrip、Black/isort/compile/diff与architecture（2686 files / 0 violations）通过；完整pytest-django component、migration forward/reverse与PostgreSQL first-winner并发仍未执行。
- 这是Broker owner历史工件账本，不是Risk scope或最终Broker receipt；order-plan/policy/Evidence/benchmark绑定仍缺，create/approve/lease/submitting保持硬暂停。

### 2026-08-13：Risk execution policy append-only persistence

- 新增 Risk Center独立private-UOW/exact insert claim、完整五类source bundle ledger与actor-bound activation ledger；source identity只做first-winner，同内容不同source identity可合法共存，不能用content hash错误合并不同owner记录。
- activation同时封存完整policy与activation(actor seal) canonical payload，以FK和冗余headers闭合source identity/hash、账户、controls、validity；单账户单root、每predecessor单successor，append用repository-derived current head做CAS。
- `get_current_head` 先restore cutoff前全ledger再按Domain account分链，验证单root、同链前驱、clock前向、无fork/cycle/disconnected；identity/current PIT provider拒绝superseded旧policy，expired head不回退 predecessor。
- Application写流程在同一atomic、source首末双读相等后先exact-idempotent append source，再创建/重放activation winner；source或activation append返回替换值都稳定Conflict。migration `0009_broker_order_execution_policies`仅CreateModel，禁止RunPython/RunSQL且zero-seed。
- 两表`persisted_at`由private repository写authoritative transaction clock并exact等于recorded_at；Django 5.2.10最小schema-editor实测 `1 source / 1 activation / current head True`。

未完成与验证：

- Domain/Application `25 passed`；Black/isort/py_compile/diff、makemigrations drift与architecture（2686 files / 0 violations）通过。时钟修复后的完整pytest-django component与migration forward/reverse尚未跑，PostgreSQL root/successor双事务race仍未验证。
- 仍缺从floor/template/account override/global+account exceptions生成可信exact source snapshot的production composition；本migration不seed、不回填，故不会凭现有mutable policy自动授权。Risk authorization和Broker四节点总闸继续关闭。

#### Ledger contract audit修正

- 只读复核实证0008/0009后`makemigrations --check`会提出无意义constraint重建：Broker artifact model的owner/check Q deconstruct顺序与migration不同，Risk 既有authorization model同样偏离0008 state。现将model表达对齐既有migration，并把Broker `persisted_at == recorded_at`同时纳入model与0008 DB check，而非只依赖restore。
- Risk execution policy provider此前把actor-bound `activation.content_hash`错误投影成`policy_content_hash`；现拆为`policy_content_hash=policy.content_hash`与`policy_activation_hash=activation.content_hash`，并让Risk authorization scope、canonical codec/hash全链同时绑定二者，既不丢actor seal也不混淆策略内容身份。
- Risk/Broker hard-gate聚合`53 passed`，Black/isort/py_compile与architecture（2688 files / 0 violations）通过。完整项目migration drift复跑在Django5.2环境加载`account`时因缺`cryptography`阻断，未将该环境问题写成no-drift通过；PG并发和source identity双selector篡改的closed-world检测仍待后续修正。

#### Risk policy source identity closed-world修正

- source first-winner和activation source binding不再先按可篡改的冗余 identity headers筛选；repository先restore完整source ledger并核对canonical payload、identity/header/ledger seals，再按Domain identity选winner。即使数据库里同时改动source id/version与identity seal，坏行也不能从查询集合中隐身后允许原identity再次append。
- component回归新增双selector raw tamper场景，并同步修正policy provider对`policy_content_hash`与`policy_activation_hash`的双seal断言。该修正不改变zero-seed、Risk authorization availability或Broker执行总闸。

### 2026-08-13：Broker pre-Risk inactive scope 合同与 Application workflow

- 新增 Broker-owned、零跨 App import 的 `BrokerPreRiskExecutionScope`，精确封存 Portfolio plan、inactive approval receipt/subject 与 Broker order approval artifact 的 identity、version、content hash、有效期和订单批准时冻结的 Risk policy version；scope 的有效期只能等于三源窗口最小值。
- 该对象明确不是最终 execution authorization：permission 固定 `inactive`，`activation_available=false`、`must_not_execute=true`，并固定保留 Portfolio 执行审批 inactive、Broker order artifact inactive、plan/order binding 未证明、Portfolio/Broker account namespace 未证明、Risk policy identity 未绑定五个 blocker。没有把 Portfolio 字符串账户号转换成 Broker 整数账户号，也没有把历史 inactive receipt 升级为 current execution permission。
- Application 注册命令只接受 scope、plan、receipt、order artifact 的 ID/version；在单一 Broker server cutoff 对三个 owner projection 各首末双读，验证 receipt 精确绑定 plan，并由 repository logical `(broker_account_id, order_artifact_id)` head 派生 predecessor。相同 identity 仅在 first winner 仍为当前本地候选 head 时幂等重放，其他 scope 形成 exact supersession 链。
- 提供 historical exact/PIT reader 与带 plan/order/receipt identity+hash 的本地 current-head reader；这里的 `current` 只表示 Broker pre-Risk candidate ledger 的逻辑 head，不代表 Portfolio approval、Risk authorization 或生产执行 authority 当前有效。

未完成与验证：

- 纯 Domain/Application `36 passed`；standalone strict mypy 两个生产文件 `0 errors`，Black/isort/py_compile/diff-check与architecture（2688 files / 0 violations）通过；当前环境未安装ruff，项目mypy plugin仍缺失。
- 尚无 pre-Risk append-only ORM/codec/repository、Portfolio public composition、Portfolio↔Broker account owner binding或Risk adapter。后续 Risk adapter在本scope固定inactive时必须返回None；最终Broker issuer、Research/benchmark refs、四节点exact current重验和PostgreSQL并发均未完成，总闸继续false。

### 2026-08-13：Broker pre-Risk append-only persistence

- 新增独立private-UOW/exact insert claim、append-only model、strict canonical codec与repository；scope identity/content first-winner、每`(broker_account_id, order_artifact_id)`单root和每predecessor单successor由唯一约束与root claim封闭，migration `0009_pre_risk_execution_scope`仅CreateModel、无RunPython/RunSQL且zero-seed。
- repository所有安全关键读先按cutoff读取并restore完整visible ledger，逐行验证canonical payload、冗余headers、root claim、ledger seal及`persisted_at == recorded_at`，再按Domain account/order或identity/content分组；不再先信任可篡改的数据库selector。
- full-chain current head验证单root、predecessor存在、相邻successor同账户/订单且时钟前进、无fork/cycle/disconnected；链构建不会预先丢弃过期节点，expired successor只会使current返回None，不会回退或复活仍未过期的旧root。
- component覆盖已写入双account/order header篡改、双scope identity/content header篡改、first-winner/CAS、append-only绕行、payload/header/ledger/persistence clock、PIT与expired successor；Django 5.2.10最小schema-editor真实往返为`1 row / inactive / must_not_execute=True`，model/migration deconstruct核对为constraints/indexes/24 fields全部一致。

未完成与验证：

- Black/isort/py_compile/diff-check、standalone mypy（无Django stubs环境仅关闭ORM subclass Any/no-any-return）与architecture delta `0 violations`通过；默认Python无Django，完整pytest-django component未执行，PostgreSQL root/successor并发race未验证。
- Risk active provider不能消费这个固定inactive scope：Risk port只有ID/version，而Broker current reader要求完整closed selector，且新增Risk→Broker import会与既有Broker→Risk形成循环。本阶段不增加永远None的伪adapter；等待未来独立active scope/owner facade。Portfolio账户namespace binding、Research/benchmark、最终issuer与四节点重验继续未完成，总闸false。

### 2026-08-13：Broker/Portfolio 账户命名空间绑定 Domain 合同

- 新增 Broker-owned、零跨 App import 的账户命名空间绑定合同，分别保留 Broker `int` 账户 ID 与 Portfolio `str` 账户 ID；禁止通过 `int()` / `str()` 转换猜测两个 namespace 等价。
- binding 以独立 identity hash 和 content hash 封存 owner、identity/version、两侧 source owner/artifact type/id/version/content hash、human-staff 断言人双身份、签发/记录/有效期和 predecessor；账户身份真源固定归 `account/account_identity_snapshot`，Portfolio 仅消费字符串 namespace，不能用 plan 自签账户归属。任一 source 或 namespace 替换都会改变封印。
- 相邻 successor 必须绑定 exact predecessor、保持同一 Broker account logical subject 并推进 recorded clock。permission 固定 `inactive`，`activation_available=false`、`must_not_execute=true`，并保留两侧 owner provider 与人工 approval 未集成三个 blocker。

未完成与验证：

- 纯 Domain `47 passed`；standalone strict mypy、Black/isort/py_compile 与源码 AST 零跨 App 依赖检查通过。
- 当前只冻结 owner contract；尚无 Application ID-only 双读、append-only ledger、两侧真实 source provider、人工签发入口或 PostgreSQL first-winner。它不能消除 pre-Risk scope 的 namespace blocker，也不授权 Risk/Broker 执行；Plan→Order binding、benchmark、Research active aggregate、最终 issuer 与四节点重验仍待后续独立阶段，总闸继续 false。

### 2026-08-13：Broker Plan→Order inactive binding Domain 合同

- 新增 Broker-owned Plan→Order content-addressed seal，精确绑定 Portfolio canonical-v1 plan identity/version/hash、inactive approval receipt/subject seal、order ordinal 与该 ordinal 的 canonical-v1 单行 JSON bytes/hash，以及 Broker order approval artifact identity/content/approval digest/version。
- 绑定固定校验 Portfolio plan owner/type、receipt owner/capability 与 Broker artifact owner/type；三份 source expiry 全部进入 content hash，binding 的 `valid_until` 必须等于三者最小值，不能由 caller 延长或缩短。
- canonical-v1 单行继续使用历史 `json.dumps(..., sort_keys=True, separators=(",", ":"))` 字节语义，包括默认 ASCII escaping；这不会修改既有 plan-v1 hash，也不以资产、方向、数量近似推断映射。
- successor 必须绑定 exact predecessor，并保持 plan id/version、order ordinal、Broker order artifact id 和 Broker account logical subject。permission 固定 `inactive`，`activation_available=false`、`must_not_execute=true`，仍保留 execution inactive 与账户 namespace 未验证 blocker。

未完成与验证：

- 纯 Domain `59 passed`；standalone strict mypy、Black/isort/py_compile与AST零跨 App import检查通过。
- 当前仅冻结合同；尚无 owner provider、ID-only双读Application、append-only ledger或真实plan-order签发记录。它不能解除现有pre-Risk blocker；账户owner workflow、benchmark、Research active aggregate、最终issuer与四节点重验继续待办，总闸false。

### 2026-08-13：Broker/Account namespace binding Application workflow

- 增加 Broker consumer-owned 两侧 exact-current source DTO/Protocol；Broker source 固定为 `broker_execution/broker_account_identity_snapshot`，Portfolio 字符串 namespace 的账户身份 source 固定归 `account/account_identity_snapshot`。写命令只接受 binding 与两侧 source 的 ID/version，不接受 account、hash、owner、状态、permission 或时钟。
- register 在单一 Broker server cutoff 对两侧 source 首末双读，要求 exact type/identity/hash、aware validity、同一个正数 `owner_user_id`、`account_type=real` 且两侧 active；owner/account 状态由 source 提供，caller 不能升级。
- Application 使用 server-auth human-staff actor、repository first-winner 与 predecessor CAS；相同 identity 只允许原 actor 跨时钟幂等，current inactive read 闭合两侧 owner/type/id/version/hash、namespace/account、owner user、real/active 状态和 binding hash。
- Domain binding 同步封存 `owner_user_id`、固定 real account 与 source active 标志并纳入 content hash；successor 不得更换 Broker account 或 owner。

未完成与验证：

- Domain+Application 纯测试 `74 passed`；standalone strict mypy 两个生产文件、Black/isort/py_compile/diff-check通过。
- 现有 BrokerAccountBinding 和 unified account 仍是 mutable row，尚无上述两个 immutable source ledger/provider；因此真实 composition 不能签发 binding。本阶段只有协议与pure fake，仍固定inactive，后续须先补Account/Broker owner source、append-only binding ledger、人工入口和PostgreSQL并发，pre-Risk blocker与总闸不变。

### 2026-08-13：Broker/Account namespace binding append-only ledger

- 新增 binding strict codec、私有UOW/exact insert claim与append-only ORM；identity、root和predecessor first-winner及logical-head CAS封闭同一Broker账户链，精确幂等以完整Domain对象为准。
- repository先closed-world恢复全部记录并复核canonical payload、两侧source/header、actor、identity/content/ledger/root/link/persisted clock seals，再做exact/PIT/current selector匹配；orphan/fork/cross-account/clock倒置或双selector篡改均fail closed，最终expired successor不回退旧binding。
- `0011_portfolio_broker_account_binding`依赖0010，仅schema/zero-seed，无RunPython/RunSQL；permission仍固定inactive，未接真实Account/Broker source composition、API或执行闸。

未完成与验证：

- Domain/Application回归 `74 passed`；py_compile、Black/isort/diff-check、codec strict mypy与architecture `2723 files / 0 violations`通过。root用Django 5.2.10最小schema-editor补验zero-seed、append与exact round-trip通过。
- 当前Django5.2环境无pytest，完整component与migration drift未取得最终结果；PostgreSQL并发CAS未验证。真实facade/raw provider/key service/composition/actor仍缺，namespace/pre-Risk blocker与总闸不变。

### 2026-08-13：Portfolio policy benchmark snapshot Domain 合同

- 新增 Portfolio-owned、零跨 App import 的 policy benchmark snapshot candidate；封存 Account identity、Portfolio planning-policy activation、Portfolio benchmark definition 三个 exact source ref（owner/type/id/version/hash/recorded/validity），账户 namespace/字符串 ID、owner user、base currency、live inception/observed/recorded clock 与 predecessor。
- benchmark components 使用 exact finite `Decimal`、唯一代码与从 0 连续 ordinal；拒绝 float、bool、NaN/Infinity、负零、重复/乱序和权重不守恒，不做自动归一、四舍五入或运行时配置洗白。本 v1 固定 `cash_weight=0`，component 权重必须精确合计 1。
- snapshot `valid_until` 必须等于三个 owner source 的最小有效期，且只允许 `inception <= observed <= recorded < valid_until`；任一 source 在 recorded clock 尚不可知都会阻断。identity/content hash与相邻same-account successor规则已固定。
- 当前 planning policy active row、simulated-trading FloatField benchmark配置和临时行情都不是这些owner source；不能现场hash后冒充正式policy benchmark或每日valuation。permission固定inactive，四个blocker、`activation_available=false`与`must_not_execute=true`不可升级。

未完成与验证：

- 纯Domain `27 passed`；standalone strict mypy、Black/isort与AST零跨App/framework import检查通过。
- 尚缺Account identity、planning-policy activation和benchmark-definition owner合同/ledger/provider，也没有daily benchmark valuation、审批、Application/ORM或Broker issuer接线；本合同不能授予执行权限，总闸继续false。

### 2026-08-13：Portfolio policy benchmark definition Domain 合同

- 新增完整benchmark methodology definition，而不是把现有`code + float weight`列表改名：冻结ordered constituent code、price identifier、currency与exact Decimal weight（总和严格为1），base currency、valuation timezone/cutoff、evaluation window、price/FX最大陈旧度及missing price/FX=`fail_closed`。
- 强制五类exact owner methodology ref全部存在并按固定顺序封存：trading calendar、price fixing、FX fixing、corporate action、cost/tax；每个ref绑定owner/type/id/version/hash/recorded/validity。definition记录时全部source必须已knowable，有效期严格取五源最小值。
- identity/content hash覆盖所有组件、方法ref、窗口/陈旧度/缺失策略与时钟。合同固定definition-only、三项blocker、`activation_available=false`、`must_not_execute=true`，刻意不包含status/active/approved字段。

未完成与验证：

- benchmark definition + inactive snapshot组合 `34 passed`；standalone strict mypy、Black/isort/py_compile/diff-check和零跨App/framework import通过。
- 五类methodology目前只有consumer ref合同，尚无各owner ledger/exact provider；benchmark definition activation、daily valuation与approval也未完成。不得把现有R8 calendar、mutable component rows或临时行情直接投影成这些source。

### 2026-08-13：Portfolio benchmark trading-calendar methodology Domain 合同

- 新增Portfolio owner的benchmark valuation calendar methodology，而非复用R8 monitoring calendar或Data Center原始市场日历事实。合同冻结methodology identity/version、market calendar code、IANA timezone、coverage与逐日完整membership。
- 日期必须逐日连续、ordinal从0连续；valuation day必须有local open/close/cutoff且`open < close <= cutoff`，non-valuation day三项必须全空。标准库`zoneinfo`校验DST：nonexistent local time拒绝，ambiguous time必须显式fold=1，普通时间禁止非规范fold。
- recorded/valid clock要求发布早于coverage且有效期覆盖完整日历；identity/content hash封存全部day membership与cutoff。permission固定`methodology_definition_only`、`activation_available=false`、`must_not_execute=true`，不包含status/current/active。

未完成与验证：

- 纯Domain `8 passed`；strict mypy、Black/isort/compileall/diff-check与architecture `2728 files / 0 violations`通过；当前环境无ruff。
- 尚无calendar methodology ledger/两人activation/current provider；price/FX fixing、corporate-action、cost/tax其余四类owner methodology也未建立。五类均有exact-current activation前不得激活benchmark definition或生产daily valuation，总闸不变。

### 2026-08-13：Portfolio benchmark trading-calendar methodology ledger

- 新增strict codec、私有UOW/exact insert claim与append-onlyORM；identity/content first-winner仅允许精确幂等，save/update/delete/bulk/raw写绕过全部阻断。
- repository在selector匹配前closed-world恢复全表，复核完整逐日membership、DST fold、authority/header、identity/content/ledger与recorded/valid/persisted clock seals，再提供historical exact/PIT。Domain没有successor/current/activation，本账本也不自行发明这些语义。
- `0021_policy_benchmark_trading_calendar`仅CreateModel，依赖0020，zero-seed且无RunPython/RunSQL；不回填R8 calendar或Data Center市场事实。

未完成与验证：

- Django5.2.10 SQLite隔离component `7 passed`，Domain回归 `8 passed`；architecture `2734 files / 0 violations`，Black/isort/compileall/diff-check通过。mypy regression=0但环境缺mypy_django_plugin，PG并发未验证。
- 两人activation/current provider未完成；price/FX fixing、corporate-action、cost/tax其余四类methodology仍缺。benchmark definition/daily valuation不得提前active，总闸不变。

### 2026-08-13：Portfolio benchmark price-fixing methodology Domain 合同

- 新增Portfolio owner的price-fixing methodology，固定price field为`close/nav/settlement`显式枚举、adjustment basis v1仅`unadjusted`；封存price identifier namespace、venue、IANA timezone/local cutoff与有序exact source refs。
- source priority ordinal必须连续且每个source owner/type/id/version/hash/recorded/validity精确；`source_failure_policy=block`、`automatic_fallback=false`、positive stale threshold和`missing_price_policy=fail_closed`固定，禁止把非空旧价或自动fallback洗成成功。
- IANA/DST local cutoff、source recorded/min-validity与methodology recorded/validity进入canonical identity/content hash；permission固定definition-only、activation false、must-not-execute，不含status/current。

未完成与验证：

- 纯Domain `10 passed`；strict mypy、Black/isort/compileall/diff-check与architecture 0 violations通过，当前环境无ruff。
- price-fixing ledger/两人activation/current provider未完成；FX fixing、corporate-action、cost/tax三类methodology仍缺。benchmark definition和daily valuation不得提前active，总闸不变。

### 2026-08-13：Portfolio benchmark price-fixing methodology ledger

- 新增strict codec、私有UOW/exact insert claim与append-onlyORM；identity/content first-winner仅允许精确幂等，update/delete/bulk/raw写绕过全部阻断。
- repository在selector匹配前closed-world恢复全表，复核source refs、IANA/DST cutoff、authority/header、identity/content/ledger/persisted clock seals，再提供historical exact/PIT；Domain没有successor/current/activation，本账本不自行发明。
- `0022_policy_benchmark_price_fixing`仅CreateModel，依赖0021，zero-seed且无RunPython/RunSQL；不回填行情provider、mutable config或临时price facts。

未完成与验证：

- Django5.2.10 SQLite隔离component `8 passed`；architecture 0 violations，Black/isort/compileall/diff-check与codec strict mypy通过。项目mypy regression=0但环境缺plugin，PostgreSQL并发未验证。
- 两人activation/current provider未完成；FX fixing、corporate-action、cost/tax三类methodology仍缺，benchmark definition/daily valuation不得提前active。

### 2026-08-13：Portfolio benchmark FX-fixing methodology Domain 合同

- 新增Portfolio owner的FX-fixing methodology，精确封存base/quote currency、currency pair、`quote_per_base / base_per_quote`报价方向与显式inverse授权；v1 triangulation固定prohibited且不得携带pivot currency。
- IANA timezone/local cutoff逐日DST校验；有序唯一exact source refs、positive stale threshold、`source_failure=block`与`missing_fx=fail_closed`固定，source最早有效期和methodology clock进入canonical identity/content hash。
- permission固定definition-only/inactive、activation false、must-not-execute，不包含status/current；禁止自动倒数、自动三角换汇或旧非空FX洗白。

未完成与验证：

- 纯Domain `8 passed`；strict mypy、Black/isort/compile/diff-check与architecture 0 violations通过。
- FX ledger/两人activation/current provider未完成；corporate-action与cost/tax两类methodology仍缺。五类exact-current activation闭合前benchmark definition/daily valuation不得active。

### 2026-08-13：Portfolio benchmark FX-fixing methodology ledger

- 新增 strict codec、私有 UOW/exact insert claim 与 append-only ORM；methodology identity、identity/content hash 及 content first-winner只允许精确幂等，save/update/delete/bulk/raw写绕过均 fail closed。
- repository 在 selector 匹配前 closed-world 恢复全部 row，复核完整 currency pair/方向、ordered source refs、IANA/DST cutoff、authority/header、source/identity/content/ledger seals与recorded/valid/persisted clock，再提供 historical exact/PIT；Domain没有successor/current/activation，本账本不扩张语义。
- `0023_policy_benchmark_fx_fixing`只创建空表并依赖`0022`，无RunPython/RunSQL，不回填mutable FX配置、临时汇率或历史行情。

未完成与验证：

- Django 5.2.16 SQLite隔离component `7 passed`，Domain回归 `8 passed`；migration/runtime state组件比对、ruff、Black/isort、architecture（2754 files / 0 violations）与diff-check通过。
- 本阶段首次 app-wide migration 检查暴露的既有transition approval约束/时钟问题已在下一独立阶段修复；项目mypy plugin环境缺`mypy_django_plugin`，PostgreSQL并发first-winner未验证。两人activation/current provider、corporate-action与cost/tax两类methodology仍缺，benchmark不得提前active。

### 2026-08-13：Portfolio benchmark corporate-action methodology Domain 合同

- 新增Portfolio owner的corporate-action methodology definition，固定闭合`cash_dividend / stock_dividend / split / reverse_split / rights_issue`五类v1事件矩阵；定义本身不承载任何单次公司行动事实，也不发布current或activation。
- 现金分红仅在除权时确认一次应收与内部收益，支付日只结算应收、不二次计收益；送股在除权时一次确认应收股份与价格调整，支付日不二次调整；拆股/并股只调整数量和参考价且不制造收益。配股缺exact条款和投资者选择证据时固定阻断，不能推断参与或放弃。
- 方法学只接受`unadjusted`价格输入并固定`exact_event_once`；duplicate/pre-adjusted input、未知事件、缺失行动、source failure与非交易日全部fail closed。有序exact owner refs、issuer-market本地业务日、IANA timezone/cutoff逐日DST检查及source最早有效期进入canonical identity/content hash。
- permission固定`methodology_definition_only`、`activation_available=false`、`must_not_execute=true`；有序source列表不自动授予fallback，也不能把mutable event payload投影成正式事实。

未完成与验证：

- 纯Domain `9 passed`；standalone strict mypy、Black/isort、py_compile/diff-check与architecture（2758 files / 0 violations）通过。
- corporate-action ledger、两人activation/current provider和cost/tax methodology仍未完成；单次公司行动事实的owner ledger/provider也不在本阶段。五类exact-current activation闭合前benchmark definition/daily valuation不得active，总闸不变。

### 2026-08-13：Portfolio benchmark corporate-action methodology ledger

- 新增 strict codec、私有UOW/exact insert claim与append-only ORM；methodology identity、identity/content hash和content first-winner只允许精确幂等，save/update/delete/bulk/raw写绕过全部拒绝。
- repository在selector匹配前closed-world恢复全表，逐行复核五类closed event matrix、有序source refs、IANA/DST cutoff、防重复/unknown/missing策略、authority/header/identity/content/ledger seals及`persisted_at == recorded_at`，之后才提供historical exact/PIT。
- Domain没有successor/current/activation，repository也不增加这些接口；`0025_policy_benchmark_corporate_action`只创建一张空表并依赖`0024`，无RunPython/RunSQL，不回填mutable event payload、历史公司行动或现有行情。

未完成与验证：

- Django 5.2.16 SQLite component `9 passed`；Portfolio `makemigrations --check --dry-run`为`No changes detected`，ruff、Black/isort、architecture（2762 files / 0 violations）与diff-check通过。
- PostgreSQL first-winner race、完整项目回归和mypy plugin未验证；两人activation/current provider及单次公司行动owner fact ledger/provider仍缺。账本只保存definition，不使benchmark或执行链active。

### 2026-08-13：Portfolio benchmark cost/tax methodology Domain 合同

- 新增Portfolio owner的cost/tax methodology definition；不内嵌任何司法辖区税率或费用默认值，而是要求fee与tax exact owner definition逐项一一绑定并封存asset scope、jurisdiction、买卖方向、计费基数、确认时点、币种、rate/fixed/min/max形态、精度、rounding increment与mode。
- 所有rate/amount使用exact finite Decimal canonical text，拒绝float/bool、NaN/Infinity、负值与负零；显式owner rule可以发布零值，但缺source、未知asset/fee/tax、缺FX或source failure绝不静默转零、估算或自动fallback。
- 现金分红只允许在gross entitlement确认一次，支付日固定只结算、不二次收费；其他公司行动固定`exact_event_once`，already-net input和重复coverage均阻断。业务日直接复用exact benchmark trading-calendar date，币种转换只接受exact benchmark FX fixing，避免另造本地时钟或汇率语义。
- 每条rule必须与同ordinal exact source的kind/code/asset scope/jurisdiction完全一致；有序source最早有效期进入canonical identity/content hash。permission固定definition-only、activation false、must-not-execute。

未完成与验证：

- 纯Domain `46 passed`；standalone strict mypy、Black/isort与diff-check通过；相邻architecture扫描为2762 files / 0 violations。
- cost/tax ledger、两人activation/current provider和真实fee/tax owner definition producers未完成；本阶段不背书任何测试fixture费率，也不激活benchmark definition/daily valuation，总闸不变。

### 2026-08-13：Portfolio benchmark cost/tax methodology ledger

- 新增 strict codec、私有UOW/exact insert claim与append-only ORM；methodology identity、identity/content hash与content first-winner只允许精确幂等，save/update/delete/bulk/raw写绕过全部拒绝。
- repository在selector前closed-world恢复全表，复核fee/tax source与rule一一对应、Decimal canonical shape、scope/jurisdiction/event/side/basis/timing/currency/precision/rounding、fail-closed与防重复策略，以及authority/header/source/rule/identity/content/ledger/clock seals，再提供historical exact/PIT。
- fee/tax source/rule计数守恒同时由DB CHECK约束；`persisted_at == authoritative recorded_at`由DB和restore双重校验。`0026_policy_benchmark_cost_tax`只创建空表并依赖`0025`，无RunPython/RunSQL，不回填测试fixture费率、mutable配置或历史交易费用。
- Domain没有successor/current/activation，repository也不新增这些接口；该账本只封存定义，不让显式零费率或任何规则获得执行authority。

未完成与验证：

- Django 5.2.16 SQLite component `12 passed`；Portfolio `makemigrations --check --dry-run`为`No changes detected`，ruff、Black/isort、architecture（2765 files / 0 violations）与diff-check通过。
- PostgreSQL first-winner race、完整项目回归和mypy plugin未验证；真实fee/tax definition producers及统一五源两人activation/current provider仍缺，benchmark definition/daily valuation和执行总闸保持inactive。

### 2026-08-13：Portfolio benchmark methodology bundle activation Domain 合同

- 新增统一五源bundle activation，而非为calendar/price/FX/corporate-action/cost-tax建立五条可独立切换的current head；bundle按固定顺序封存benchmark definition原有五个exact methodology refs及canonical bundle hash，避免切换期间出现半新半旧组合。
- subject精确绑定benchmark definition ID/version/identity hash/content hash/recorded/validity和完整五源bundle；requester必须server-authenticated human staff。activation由第二名server human staff签发，并按actor ID与user ID双重禁止自批。
- root不得声明predecessor；successor保持同一definition ID logical benchmark，可替换definition version/content和五源refs，但必须精确绑定前一activation content hash，request/issue时钟严格前进。validity严格等于definition与五源最早有效期。
- activation固定Portfolio owner/capability/schema、permission=`benchmark_configuration_only`；只声明`activates_configuration_bundle=true`，同时固定`daily_valuation_authority=false`、`broker_execution_authority=false`与`must_not_execute=true`。原`PolicyBenchmarkMethodologyRef` schema不改，activation不冒充methodology ref或改写历史definition hash。

未完成与验证：

- 纯Domain `11 passed`；standalone strict mypy、Black/isort、architecture（2766 files / 0 violations）与diff-check通过。
- 尚无ID-only Application双读、subject/activation ledger、exact-current provider、真实staff composition或daily valuation；统一bundle合同本身不解除benchmark definition blocker或执行总闸。

### 2026-08-13：Portfolio benchmark methodology bundle activation Application workflow

- 新增ID-only subject注册、第二人审批、historical exact read与closed-current read；写命令不接收hash、methodology payload、actor、permission、时钟或predecessor，全部由owner provider、server actor与repository authoritative clock提供。
- 注册与审批在单一cutoff内对benchmark definition及固定五源methodology graph首末双读；subject和activation first-winner均绑定原actor，logical head必须属于同一definition，predecessor只由repository派生并由append CAS复核。
- 审批在Application边界稳定拒绝同actor ID或同user ID自批；current read同时要求historical exact activation、logical current head和五源exact-current graph一致。来源消失返回不可用，identity/content替换按corruption fail closed。
- workflow继续固定`benchmark_configuration_only`、`daily_valuation_authority=false`、`broker_execution_authority=false`和`must_not_execute=true`；不修改原methodology ref schema，也不把configuration activation解释为daily valuation或执行授权。


- Domain/Application纯测试 `20 passed`；standalone strict mypy、Black/isort、architecture与diff-check通过。
- 当前仅Protocol与pure fake；subject/activation append-only ledger、五类真实owner current readers、staff composition、daily valuation snapshot与PostgreSQL first-winner尚未完成，benchmark和Broker总闸保持inactive。

### 2026-08-13：Portfolio benchmark methodology bundle activation append-only ledger

- 新增subject/activation双账本、strict codec和私有UOW/exact insert claim；subject与activation identity均first-winner，每definition单root、每predecessor单successor，append以logical-head CAS拒绝fork、orphan和cross-definition替换。
- repository在任何identity/PIT/current selector前closed-world恢复两表，逐行复核完整definition与固定五源bundle、requester/approver、FK subject、canonical payload、identity/content/header/ledger seals及`persisted_at == recorded_at`。双selector或source/header篡改不能让坏行隐身。
- direct save/raw、QuerySet update/delete、bulk create/update等写绕过全部阻断；historical exact与logical-current读取分离，最终head过期不回退旧activation。`0027_policy_benchmark_methodology_activation`只创建两张空表，无RunPython/RunSQL/backfill。
- 账本继续封存`benchmark_configuration_only + daily_valuation_authority=false + broker_execution_authority=false + must_not_execute=true`，不接真实owner readers、staff composition、daily valuation或Broker gate。


- Django 5.2隔离SQLite component `13 passed`；Portfolio `makemigrations --check --dry-run`为`No changes detected`；增量mypy `0 regressions`，ruff、Black/isort、architecture（2772 files / 0 violations）与diff-check通过。
- 完整项目迁移测试曾在建库阶段超时，改用本批两表schema-editor隔离验证；PostgreSQL双事务root/predecessor race、真实五源owner current providers与生产staff composition仍未验证，总闸保持inactive。

### 2026-08-13：Portfolio inactive approval authoritative persistence clock 修复

- 修复既有 transition-plan inactive approval subject/receipt 使用 ORM wall-clock `auto_now_add` 写 `persisted_at`、但restore又拿它与注入的 authoritative `recorded_at`比较而导致合法新记录自判腐败的问题；repository现在显式写入 `persisted_at == recorded_at`，restore要求精确等值。
- runtime model与`0017`既有constraint deconstruction顺序对齐；新增`0024_align_transition_approval_persistence_clock`仅把两列改为显式DateTimeField并增加两项数据库等值约束，不回填、不生成业务记录。

未完成与验证：

- Django 5.2.16 SQLite隔离 persistence `5 passed`；Portfolio `makemigrations --check --dry-run`恢复`No changes detected`，ruff、Black/isort与diff-check通过。
- PostgreSQL migration/race及全项目回归未验证；本修复不改变inactive/must-not-execute，不连接旧审批入口或Broker执行闸。



### 2026-08-13：Portfolio policy benchmark definition append-only ledger

- 新增 definition strict codec、私有 UOW/exact insert claim 和 append-only ORM 账本；identity/content first-winner 只允许精确幂等，save/update/delete/bulk/raw 写绕过全部拒绝。
- repository 在按 identity/content selector 匹配前先 closed-world 恢复全表，逐行复核 canonical payload、Decimal 文本、ordered constituents/methodology refs、分段 hash、authority/header/identity/content/ledger seals，以及 recorded/valid/persisted clock；双 selector header 篡改不能让坏行隐身。
- 只发布 historical exact/PIT 读取；definition 仍固定 `definition_only + must_not_execute`，本阶段没有自行发明 current/activation facade。`0020_policy_benchmark_definition` 仅 `CreateModel`、zero-seed，无 `RunPython/RunSQL`，不背书现有 Float 配置。

未完成与验证：

- Django 5.2.10 + SQLite 隔离 component `11 passed`，Domain 回归 `7 passed`；migration/runtime model state 精确一致，architecture `2723 files / 0 violations`，Black/isort/compileall/diff-check 与 codec strict mypy 通过。
- PostgreSQL 并发 first-winner、完整项目 `makemigrations --check` 和全目标 mypy plugin/ruff 未验证；五类 methodology owner provider、definition activation、daily valuation、审批与 Broker issuer 仍未完成，总闸不变。

### 2026-08-13：Broker Plan→Order binding Application workflow

- 新增 Broker consumer-owned 的 exact Portfolio plan-order row、inactive receipt与Broker order artifact DTO/Protocol；写命令只接受 binding、plan/version/ordinal、receipt和artifact的ID/version，不接受hash、账户、row、时钟、permission或predecessor。
- register 在单一Broker server cutoff对三源首末双读，逐项复核固定owner/type/schema、plan/receipt/account闭合、canonical-v1 ordinal row bytes/hash、artifact identity/content/digest与inactive markers；Portfolio字符串账户和Broker整数账户分别保留，不做转换或近似匹配。
- predecessor只能由repository同一plan id/version/ordinal/order artifact logical head派生；first-winner与append返回必须exact，历史exact/PIT和closed-current读会闭合plan/receipt/subject/row/artifact全部selector。当前账户namespace未证明，因此Domain blocker继续保留。

未完成与验证：

- Domain+Application `90 passed`；standalone strict mypy、Black/isort/compileall与Application零Portfolio/Infrastructure import检查通过。
- 三个owner public reader仍未实现：Portfolio plan provider尚未公开Application facade且需owner内派生ordinal row，receipt/artifact现有read均为hash-heavy或Infrastructure私有并丢recorded clock。当前只有协议+pure fake，没有真实composition、binding ledger或签发记录，总闸不变。

### 2026-08-13：Broker Plan→Order binding append-only ledger

- 新增strict codec、私有UOW/exact insert claim与append-only ORM；logical subject固定为`plan id/version + order ordinal + order artifact id`，每subject单root、每predecessor单successor，append使用logical-head CAS并仅允许完整Domain对象精确幂等。
- 账本同时封存canonical-v1原始order-row JSON字节、row content hash与canonical byte hash；repository closed-world恢复全部记录后复核三方source、raw bytes/header、identity/content/root/link/ledger/persisted clock seals，再做exact/PIT/current selector匹配。orphan/fork/cross-subject/clock倒置、双selector篡改与row字节漂移全部fail closed，expired successor不回退旧binding。
- `0012_plan_order_binding`依赖0011，仅schema/zero-seed，无RunPython/RunSQL；仍固定inactive、保留namespace blocker，不接owner adapters/composition/API或执行闸。

未完成与验证：

- Domain/Application回归 `90 passed`；py_compile、Black/isort/diff-check、codec strict mypy与architecture `2728 files / 0 violations`通过。root用Django5.2.10最小schema-editor补验zero-seed、append与exact round-trip通过。
- Django5.2环境无pytest，完整component/migration drift和PostgreSQL并发CAS未验证；三个owner public reader/composition/真实签发仍缺，pre-Risk与执行总闸不变。

### 2026-08-13：Portfolio exact-active transition plan order owner reader

- 新增Portfolio Application owner reader，ID-only query仅含plan ID/version、order ordinal与调用方cutoff；provider Protocol由owner返回exact approved definition，reader不自行调用`now()`，不接受caller hash/account/row/permission。
- Portfolio owner从canonical-v1 plan payload中投影指定ordinal的严格canonical JSON与SHA-256，并发布plan identity/content/account、recorded/valid clock及固定`portfolio/transition_plan_definition` authority；ordinal越界、未批准/未记录/已过期、type或selector替换均fail closed。
- 本reader定义“指定immutable plan identity/version在cutoff已记录且未过期”，不声称logical latest/current head；无Infrastructure/Broker/composition/API依赖，可供Plan→Order与pre-Risk后续薄adapter复用。

未完成与验证：

- 新增及相邻纯测试 `29 passed`；Black/isort、standalone strict mypy、py_compile/diff-check与Application架构依赖测试通过，当前解释器无ruff。
- owner Infrastructure factory/公共composition尚未接线；Portfolio inactive receipt与Broker order artifact仍缺ID-only owner reader，Plan→Order真实三源双读与签发尚不可用，总闸不变。

### 2026-08-13：Portfolio inactive approval receipt ID-only owner reader

- 新增Portfolio Application ID-only receipt query，只接受receipt ID/version与PIT cutoff；owner repository提供identity winner，caller不提交hash、subject/plan/account、permission或时钟，既有hash-heavy exact facade继续只作历史审计。
- reader重验exact Domain类型、receipt/subject/plan/account/decision snapshot全部sealed anchors与content hash；`recorded_at`严格取封存`issued_at`，执行`recorded_at <= as_of < valid_until`，固定owner/capability/schema/approved state、inactive blocker、`execution_permission=inactive`和`must_not_execute=true`。
- 空content hash或type/identity替换不能依赖Domain自动修复，统一fail closed；不提供logical current/head，只表达指定immutable receipt在cutoff已记录且未过期。

未完成与验证：

- 新增及相邻纯测试 `29 passed`；strict mypy、Black/isort、py_compile、AST架构与diff-check通过，当前解释器无ruff。
- owner Infrastructure factory/composition尚未接线；Plan→Order三源仅剩Broker artifact owner reader需接真实repository，真实签发与执行总闸仍关闭。

### 2026-08-13：Broker order approval artifact ID-only owner reader

- 新增Broker Application ID-only artifact query，仅接受artifact ID/version与PIT cutoff；identity-winner repository返回artifact及独立sealed `recorded_at`，caller不提交hash/account/permission/clock，旧hash-heavy历史reader保持不变。
- DTO封存identity/content hash、account/order version、approval digest、risk policy version、approved/recorded/valid clocks与固定Broker owner/type/schema、approval-evidence-only/inactive markers。严格`approved_at <= recorded_at < valid_until`和`recorded_at <= as_of < valid_until`，批准后但落库前不可见。
- repository type/identity替换fail closed；reader无Infrastructure/composition/ORM依赖，可由Plan→Order和pre-Risk薄adapter复用。

未完成与验证：

- 纯测试 `20 passed`；strict mypy、ruff、Black/isort、py_compile、AST架构和diff-check通过。
- identity-winner Infrastructure实现及owner factory/composition尚未接线；三源owner reader合同虽已齐，但真实同cutoff双读/签发未完成，总闸不变。

### 2026-08-13：Plan→Order Portfolio owner reader adapters/composition

- 新增Portfolio owner adapters：plan reader复用`DjangoExactTransitionPlanDefinitionProvider`并原样传递exact identity/version/PIT cutoff；receipt adapter只暴露identity winner，不暴露append、writer或hash-heavy historical read。
- 公共runtime只包含两个Application reader facade；composition模块顶层不导入Infrastructure，仅在显式Django builder内延迟装配并原样传递database alias。注入factory缺失或返回None时fail closed，不把exact historical命名为current。
- 该runtime可供Plan→Order/pre-Risk薄adapter复用，仍只表达exact immutable source在cutoff已记录且未过期，不做跨App签发或执行授权。

未完成与验证：

- 纯factory与既有reader测试 `25 passed`；strict mypy、Black/isort、py_compile/diff-check及architecture delta 0 violations通过。
- Django5.2 ORM component已编写但当前系统Python无Django/pytest-django，未执行；Broker artifact owner runtime与跨App fail-closed registry尚未接入同一composition，真实三源签发与总闸不变。

### 2026-08-13：Plan→Order Broker artifact owner adapter/composition

- 新增Broker identity-winner repository adapter，先全量restore sealed artifact model再按ID/version匹配；PIT严格使用权威row `recorded_at <= as_of < artifact.valid_until`，保留artifact原始`approved_at`，不调用旧hash-heavy `get_exact`。
- 双selector SQL篡改仍会在closed-world restore/header seal处失败；naive/future cutoff fail closed。app-root factory只暴露read-only owner reader graph，不暴露append/atomic/get_exact写面。

未完成与验证：

- Application+composition纯测试 `22 passed`，Django5.2 SQLite隔离component `4 passed`；ruff、strict mypy、Black/isort、py_compile/diff-check通过。
- 全仓component启动约54秒无输出后终止；跨App fail-closed registry/Plan→Order三源composition尚未实现，执行总闸不变。

### 2026-08-13：Portfolio planning policy definition Domain 合同

- 将 planning policy 的不可变定义语义从 legacy ORM `status` selector 中分离：新 Portfolio-owned definition 只封存 policy ID/version、positive buy lot size，以及 fee、slippage、minimum rebalance、max asset weight、max volume participation 五个 exact finite Decimal。
- Decimal 使用无 exponent 的canonical plain text，拒绝float/bool、NaN/Infinity、负零与越界；max weight/participation限制在 `(0,1]`，其他三项允许exact zero但不允许负数。recorded/validity与identity/content hash全部进入合同。
- definition 固定 `definition_only` 与 `must_not_execute=true`，刻意不包含 `status/current/activation/supersession`；旧 `PortfolioPlanningPolicyModel.status=active` 可被Admin/QuerySet改变，只能视为legacy runtime selector，不能投影成正式activation。

未完成与验证：

- 纯Domain `75 passed`；standalone strict mypy、Black/isort/compileall与零跨App/framework import检查通过。
- Benchmark definition需另行覆盖日历、FX/价格fixing、公司行动、缺价/陈旧度、费用税费与评估窗口，不能用现有component+weight缩水冒充。

### 2026-08-13：Portfolio planning policy definition append-only ledger

- 新增strict canonical codec、独立Portfolio ORM model、私有UOW/exact insert claim和first-winner repository；直接save/save_base(raw)、QuerySet update/bulk update、bulk create、instance/query delete全部阻断。
- 模型冗余封存authority/schema/permission、policy identity、全部lot/Decimal定义、recorded/valid clocks、canonical payload、identity/content hash与ledger header seal；`persisted_at`必须aware且exact等于server `recorded_at`。
- append和exact/PIT读都先closed-world恢复整个ledger，再按Domain identity/content selector匹配；同时篡改policy tuple、identity hash和content hash不会让坏行隐身或允许二次插入。first-winner只有exact candidate可幂等返回。
- `0018_planning_policy_definition`只创建空表，无RunPython/RunSQL/backfill；它不读取或升级legacy mutable policy，也不提供current/activation语义。

未完成与验证：

- Domain纯测试 `75 passed`；Django 5.2.10 SQLite隔离schema-editor zero-seed→append→exact PIT→drop往返通过；agent隔离组件 `13 passed`，migration/runtime state逐字段、索引、约束一致；Black/isort/compileall/diff-check、codec strict mypy与架构扫描 `2706 files / 0 violations`通过。
- 完整`manage.py makemigrations --check`因Django 5.2环境缺Celery无法启动，未验证；PostgreSQL并发first-winner未验证。activation subject/record persistence、真实composition和legacy迁移仍未完成。

### 2026-08-13：Portfolio planning policy activation Domain 合同

- 新增 Portfolio-owned 的 exact definition activation subject/record：subject 封存policy ID/version、definition identity/content hash、definition recorded clock、server requester、请求时钟、有效期与前序activation hash；activation再封存完整subject、第二名server approver与issued clock。
- requester与approver都必须是human staff，并同时按actor ID与user ID禁止自批。请求时definition必须已knowable且未过期；activation有效期严格等于definition/subject有效期，issued clock必须落在subject窗口内。
- activation固定authority=`portfolio/planning_policy_activation`、permission=`policy_configuration_only`与`must_not_execute=true`。它只证明一个规划配置被两人激活，不是Portfolio计划审批、Risk授权或Broker执行许可。
- successor必须保持同一logical policy，精确绑定前序activation content hash且issued clock严格前进；真正的single-head/fork约束留给后续append-only repository。

未完成与验证：

- PlanningPolicy definition + activation Domain组合 `83 passed`；standalone strict mypy、Black/isort/py_compile/diff-check和零跨App/framework import通过。
- 仅Domain合同完成；definition ledger正在独立收口，activation尚无Application ID-only workflow、subject/activation ledger、exact/current provider或legacy status迁移。不得用本合同解除benchmark、plan、pre-Risk或Broker总闸。

### 2026-08-13：Portfolio planning policy activation Application workflow

- 新增两个ID-only写命令：subject注册只接subject/policy identity，approval只接subject/activation identity；hash、definition字段、actor与时间均来自trusted provider、server actor和repository clock。
- 注册在同一server cutoff首末双读exact definition，读取logical current activation head并由repository派生predecessor；first-winner重放仅允许原requester，换actor、definition drift或append替换稳定fail closed。
- approval先读取persisted subject first winner，再对subject与definition各做首末双读；第二名human staff由Domain按actor/user双重非自批校验，append以predecessor CAS闭合。跨时钟幂等只允许原approver，历史/被supersede/过期activation不会被current reader复活。
- closed-current读要求activation ID/version/content、policy ID/version与definition content hash全selector相等，并额外核对logical head；Application无ORM、Infrastructure或跨App implementation import。

未完成与验证：

- definition + activation Domain/Application组合 `92 passed`；standalone strict mypy、Black/isort/py_compile/diff-check通过。
- 当前仅Protocol与pure fake。definition ledger尚在收口，activation subject/record repository、真实composition、actor interface与PostgreSQL first-winner均未完成；legacy status、benchmark和执行总闸不变。

### 2026-08-13：Portfolio planning policy activation append-only ledger

- 新增subject与activation双账本、strict codec、私有UOW/exact insert claim；subject/activation各自first-winner，每policy单root、每predecessor单child，append使用logical-head CAS并拒绝fork、orphan、cross-policy与非前进时钟。
- repository先closed-world恢复全部subject/activation并复核FK、canonical payload、冗余header、identity/content、ledger和persisted clock seals，再做identity/PIT/current匹配；同时篡改selector header不能隐藏坏行。
- exact/PIT/current-head区分历史与有效状态；最终head过期只返回None，不回退旧activation。直接save/raw/update/bulk/delete全部阻断，Domain两人审批仍按actor/user拒绝self approval。
- `0019_planning_policy_activation`只创建两张空表，依赖0018，无RunPython/RunSQL/backfill；legacy mutable status完全未接入。

未完成与验证：

- Django 5.2.10 SQLite隔离组件 `15 passed`，activation Domain/Application回归 `17 passed`；model system checks、migration/runtime state、architecture `2716 files / 0 violations`、Black/isort/compileall/diff-check及codec strict mypy通过。
- PostgreSQL root/predecessor并发race未验证；完整manage.py drift因环境缺Celery未跑，已用migration state精确对照；ruff未安装。真实composition、actor interface、legacy迁移及benchmark消费仍未完成。

### 2026-08-13：Account-owned account identity snapshot Domain 合同

- 新增 Account-owned、零跨 App import 的 canonical账户identity evidence：Portfolio消费的字符串账户namespace/ID与底层unified账户namespace/整数ID分别保留，只建立provenance，不做字符串/整数转换或身份猜测。
- snapshot封存source ID/version、underlying mutable source ID/version/content hash、正数owner user、固定real+active、underlying source时钟、Account policy TTL、issued/recorded时钟与predecessor；`valid_until`必须等于underlying source与TTL的最小值。
- provenance显式区分`authoritative`与`manual_reclaim`。曾被legacy migration默认分配user的账户只能走manual reclaim，并必须绑定Account-owned reclaim receipt owner/type/id/version/hash；当前非空user_id不能自动获得背书。
- identity/content hash和same-account successor规则已固定；permission=`identity_evidence_only`、status=`inactive`、provider blocker、`activation_available=false`与`must_not_execute=true`不可升级。

未完成与验证：

- 纯Domain `61 passed`；standalone strict mypy、Black/isort/py_compile/diff-check与零跨App import通过。
- 现有simulated-trading账户行仍mutable且user历史可能受默认回填污染；尚无trusted raw provider、ID-only发行workflow、reclaim receipt、append-only ledger或exact/current facade，不能作为namespace binding真实source，总闸不变。

### 2026-08-13：Account-owned raw identity source Domain 合同

- 新增 Account owner 的 raw identity source evidence，分别封存字符串 Account namespace/ID 与整数 underlying unified provenance，禁止通过类型转换推断同一身份；row source 以 owner/type/id/version/content hash 进入 canonical seal。
- owner assignment 改为 `authoritative / legacy_default / unknown` 三态。authoritative 必须有 Account owner-assignment exact evidence与正数owner；legacy-default必须有legacy marker且不得声称owner；unknown不得携带owner/evidence，也不能被下游静默当成authoritative。
- observed/recorded、row validity、TTL与有效期最小值全部使用aware clock；identity/content hash、相邻predecessor与同logical subject supersession已冻结。inactive/expired successor仍是链head，不允许回退旧source；合同固定`source_evidence_only + inactive + must_not_execute`。

未完成与验证：

- 纯Domain `27 passed`；standalone strict mypy、ruff、Black/isort、py_compile/diff-check与零跨App/framework import通过。
- 尚无raw capture Application、append-only ledger、simulated-trading observation adapter或owner-assignment provider；`0013`默认user回填不能被当前mutable row洗白。manual reclaim receipt需在raw artifact可验证后另做两人制owner合同，总闸不变。

### 2026-08-13：Account raw identity source Application workflow

- 新增ID-only capture命令与consumer-owned exact unified-row observation、Account assignment-evidence DTO/Protocol；caller不能提交owner、hash、assignment state、clock、permission或predecessor。
- Application在同一server cutoff对row observation与assignment evidence首末双读，以human-staff actor、repository authoritative clock、first-winner和logical predecessor CAS封存raw source；相同identity跨时钟仅原actor可幂等。
- authoritative必须精确绑定正数owner与row seal；legacy-default只有exact legacy marker才可封存且owner必须为空；unknown或legacy缺marker均Unavailable并保持零写。inactive real row可诚实记录，non-real拒绝；exact/PIT/full-selector current reader均保持inactive。

未完成与验证：

- Application纯测试 `13 passed`，Domain+Application `40 passed`；strict mypy、ruff、Black/isort、py_compile/diff-check与AST无Django/ORM/simulated-infrastructure检查通过。
- 尚无raw append-only ledger、simulated-trading observation adapter、assignment evidence owner provider、composition或actor interface。现mutable row仍不能直接供Account snapshot/reclaim与namespace binding签发，总闸不变。

### 2026-08-13：Account raw identity source append-only ledger

- 新增strict codec、私有UOW/exact insert claim与append-only ORM；source identity与字符串logical account单root/每predecessor单successor，append以repository head做CAS并仅允许完整Domain对象精确幂等。
- repository closed-world恢复全表后复核authoritative/legacy/unknown assignment矩阵、row/evidence refs、actor binding、identity/content/root/link/header/ledger/persisted clock seals，再做exact/PIT/current selector匹配；inactive或expired successor仍是head，不回退旧source。
- `0038_account_identity_raw_source_ledger`仅CreateModel/constraints/index，依赖0037，无RunPython/RunSQL/backfill；不把mutable simulated row或0013默认user自动变成证据。

未完成与验证：

- Account-only Django5.2.16 SQLite component `11 passed`；`makemigrations account --check --dry-run`显示No changes，strict mypy、ruff、Black/isort、py_compile/diff-check通过。
- 全仓pytest启动超过60秒无输出后终止；真实0038 migrate与PostgreSQL并发race未验证。simulated adapter、assignment evidence provider、composition与actor interface仍缺，Account snapshot/reclaim和namespace binding不能真实签发。

### 2026-08-13：Account-owned account identity snapshot Application workflow

- 新增普通Issue与legacy Reclaim两个ID-only命令：调用方只能提交snapshot/raw source identity，reclaim额外提交receipt identity；account、owner、hash、provenance、clock与permission均由trusted providers、server actor和repository派生。
- 普通Issue遇到legacy default-user source直接Unavailable且零写入。Reclaim必须在同一server cutoff首末双读raw source和exact Account-owned reclaim receipt；receipt需绑定raw source全部identity/hash、账户namespace/ID、底层整数ID和server actor，nullable legacy owner不会被静默信任。
- 写入封存human-staff actor，first-winner跨时钟重放仅允许原actor；同一字符串Account identity的successor predecessor由repository logical head派生并CAS。Account字符串ID与底层整数provenance从不cast。
- exact/PIT与closed-current reader复核完整authority/schema、provenance/receipt、underlying source、owner/real/active及logical head；superseded snapshot不复活，所有结果仍identity-evidence-only/inactive/must-not-execute。

未完成与验证：

- Account identity Domain/Application组合 `95 passed`；strict mypy、Black/isort/ruff/compileall/diff-check及Application无Infrastructure/跨App implementation import检查通过。
- 当前仍只有Protocol与pure fake；simulated-trading raw adapter、manual reclaim receipt owner ledger/provider、Account snapshot账本、composition、真实actor入口和PG并发未完成，不能供Broker namespace binding真实签发。

### 2026-08-13：Account identity snapshot append-only ledger

- 新增actor-bound snapshot账本、strict codec、私有UOW/exact insert claim；封存完整provenance、manual reclaim receipt refs、underlying source、owner/real/active、identity/content/header/actor-binding/ledger/persisted clock seals。
- 每个字符串Account namespace/ID只允许单root、每predecessor单successor；append按logical head CAS，closed-world全表restore后再做identity/hash/PIT/current匹配，拒绝orphan/fork/selector隐藏和clock倒置。最终head过期不回退旧snapshot。
- 直接save/save_base(raw)、update/bulk update/create及instance/query delete全部阻断。`0037_account_identity_snapshot_ledger`仅CreateModel/constraints/index，依赖0036，无RunPython/RunSQL/backfill；不会把legacy默认user或mutable simulated account自动写成可信证据。

未完成与验证：

- Django 5.2.10 minimal SQLite zero-seed→append→exact PIT→drop往返通过；Django5.2.16环境的Black/isort/ruff/compileall及3生产文件standalone strict mypy通过。共享完整pytest-django组件启动超过33秒无结果后按边界终止，因此组件断言尚无最终通过证明。
- 主Python缺Django/stubs时mypy仅报6个subclass-Any环境假阳性；完整makemigrations/migrate和PostgreSQL并发未验证。raw adapter、manual reclaim receipt owner ledger/provider、composition与真实actor仍缺，不能接namespace binding。

### 2026-08-13：Broker-owned broker account identity snapshot Domain 合同

- 新增 Broker-owned identity evidence，精确封存Broker整数account namespace/ID、正数owner user、固定real+active、Account-owned identity source owner/type/id/version/hash/字符串namespace/账户ID/owner/real-active，以及Broker binding revision/content与Agent identity/version/content/owner。
- Account字符串ID与Broker整数ID只分别保留，不做cast或相等比较；但Account source owner user、Broker binding owner、Agent owner必须全部与snapshot owner一致，任一替换失败关闭。
- QMT broker account reference不写明文，也不接受plain SHA-256；只允许带key ID的`hmac-sha256`或`blake2b-keyed-256` digest。heartbeat、credential与连接readiness不进入identity合同，避免把短时运行状态冒充长期身份。
- snapshot有效期严格取Account source有效期与Broker TTL最小值，封存issued/recorded、binding revision与predecessor；identity/content hash及same Broker account+owner successor规则已固定。authority=`identity_evidence_only`、permission=`inactive`、`activation_available=false`、`must_not_execute=true`。

未完成与验证：

- 纯Domain `34 passed`；standalone strict mypy、Black/isort/py_compile/diff-check与零跨App import通过。
- 现有Broker binding/Agent仍mutable，尚无Account exact facade、Broker trusted raw provider、keyed digest service、ID-only issuance、append-only ledger或exact/current reader；本合同不能供namespace binding真实composition，总闸不变。

### 2026-08-13：Broker account identity snapshot Application workflow

- 新增ID-only发行命令：只接snapshot identity、Account source identity与Broker整数account selector，不接受account owner、hash、clock、QMT reference或permission。Account exact source和Broker binding/Agent raw projection均在同一server cutoff首末双读。
- Account consumer DTO保留字符串namespace/ID、owner/real/active/hash/PIT/current；Broker raw DTO保留独立整数namespace/ID、binding revision/hash/owner、Agent identity/hash/owner与broker category。两类ID分别封存，从不cast或相等比较；三处owner必须一致。
- QMT原值只允许作为trusted raw DTO中的non-empty exact bytes进入注入的keyed digest service；Domain、persisted record、current selector与输出只保留algorithm/key ID/digest，测试证明明文不进入snapshot payload。plain SHA或digest类型替换fail closed。
- server human-staff actor、first-winner跨时钟原actor重放、logical-head predecessor CAS、exact/PIT与closed-current完整selector均已编排；结果固定inactive/must-not-execute。

未完成与验证：

- Broker account identity Domain/Application组合 `54 passed`；strict mypy、Black/isort/py_compile/diff-check与架构扫描 `2706 files / 0 violations`通过；当前环境无ruff，未验证该项。
- 仅Protocol+pure fake；真实Account facade、Broker binding/Agent raw provider、keyed digest key service、snapshot账本/composition、actor入口与PG并发未完成，不能供namespace binding真实签发或解除总闸。

### 2026-08-13：Broker account identity snapshot append-only ledger

- 新增actor-bound snapshot账本、strict codec、私有UOW/exact insert claim；封存Broker整数namespace/ID、Account source完整ref、binding revision/hash/owner、Agent identity/hash/owner、keyed QMT digest、authority与全部clock/header/identity/content/ledger seals。
- 每个Broker namespace+整数account只允许单root、每predecessor单successor；repository closed-world恢复全表后验证单链、orphan/fork/cross-account/clock，再做identity/hash/PIT/current匹配。最终expired successor不回退旧snapshot，双selector header篡改不能隐藏坏行。
- 直接save/save_base(raw)、update/bulk update/create及instance/query delete全部阻断。`0010_broker_account_identity_snapshot`依赖0009且只CreateModel，无RunPython/RunSQL/backfill；mutable binding/Agent/QMT reference不会被自动升级。

未完成与验证：

- 主线Django 5.2.10 minimal SQLite zero-seed→append→exact PIT→drop往返通过；Black/isort/py_compile/diff-check通过，组件测试文件覆盖写绕过、expired head、selector tamper与closed-world异常。
- 完整component pytest、migration state/full drift、Infrastructure strict mypy与ruff未取得最终证明；PostgreSQL并发未验证。真实Account facade、Broker raw provider、keyed digest key service、composition与actor入口仍未完成，不能接namespace binding或总闸。

### 2026-08-13：M0 Transition Plan legacy writer 隔离首批

已完成：

- 代码审计确认 legacy 与 canonical repository 共用 `decision_portfolio_transition_plan` 表，但 orders、snapshot、expiry、idempotency 与 approval 生命周期契约不兼容，不能把 replacement 当作可直接互换的实现；本批保持 `PORTFOLIO_CANONICAL_PLANNER_ENABLED` 默认关闭，不切路由、不改 TUI/SDK/MCP payload。
- 补登记此前漏掉的 `ExecutionApprovalRequestRepository.update_status`：它会在 plan-linked approval approve/reject 时连带更新 plan 状态和 `approval_request_id`。Transition Plan writer 分母由 9 修正为 10（legacy 6、canonical 4）。
- 6 个 legacy writer 在 canonical 模式下统一 fail-closed；审批状态入口仅在 `model.transition_plan is not None` 时阻断，普通 unified/legacy recommendation 审批不受影响。机器守卫同时验证这个条件分支，避免只在函数其他位置出现 guard 的假阳性。
- approve/reject Interface 只捕获专用 `LegacyTransitionPlanWriteDisabledError` 并返回稳定 409；其他 `ValueError` 不被误报为切换冲突。

仍未完成：

- 存量 family 分类审计、PostgreSQL 并发、owner/snapshot/policy/人工审批验收仍未完成；同表 schema family 与 cross-family read/write 首批防线已完成，但不得据此翻转 canonical planner 默认开关。
- 当前 Python runtime 缺 Django 与 mypy Django plugin；新 API/ORM 行为测试已写但未在完整项目 runtime 执行，PostgreSQL 并发与零副作用阻断也待 CI/项目环境验证。

本阶段验证：

- writer freeze 专属纯测试 `8 passed`；CLI 为 Transition Plan writers `10`、HTTP `54`、SDK `15`、TUI decision `25`、TUI mutation `23`、MCP position-write `32`。
- Architecture delta/full verify 均 `0 violations`；module audit `207 edges / 0 cycles`；Black、isort、`py_compile`、JSON 与 diff check 通过。
- `check_mypy_regression.py` 报 `Mypy regressions: 0`，但项目 mypy plugin 因环境缺 `mypy_django_plugin` 未启动；API 测试加载阶段因缺 Django 未执行，不计为通过。

### 2026-08-13：M0 Transition Plan 同表 contract-family 隔离

已完成：

- 为共用的 `decision_portfolio_transition_plan` 增加 nullable、indexed `plan_contract_family`，仅允许 `decision_rhythm_legacy_v1` 与 `portfolio_canonical_v1`；migration `0016` 只有一个 `AddField`，无 `RunPython/RunSQL`、无 default、无存量回填。
- legacy repository 的所有新写入显式标记 legacy family；存量 `NULL/blank` 仅按保守 legacy 兼容读取，任何已标 canonical 行在 decode、overwrite、status update、approval create/update 前失败关闭。
- canonical repository 的新写入显式标记 canonical family，并以 `plan_id` 与 `idempotency_key` 双身份加锁查询；read/replay/approve 只接受 canonical family，拒绝消费 legacy 或未分类 payload。
- 共享 family 规则放在 `core/integration`，没有让 Portfolio 反向依赖 Decision Rhythm；一次中间实现被 module-cycle gate 抓到并撤销，最终恢复为原有 207 条 App 边、0 cycle。

仍未完成：

- 存量 `NULL` 行的受控分类/审计迁移、cross-family attempt 指标与日志、PostgreSQL first-winner 并发验证；当前 canonical `select_for_update` 对不存在行不能替代数据库并发 first-winner 证据。
- 完整 Django runtime 下 migration forward/reverse、legacy/canonical repository round-trip 与 cross-family 零副作用 component 测试尚未运行；canonical flag 继续默认关闭，路由/TUI/SDK/MCP 未切换。

本阶段验证：

- family/migration 静态规则与 writer freeze 聚合纯测试 `16 passed`；migration AST 证明单一 nullable `AddField` 且无数据操作。
- Architecture delta/full verify 均 `0 violations`；module audit `207 edges / 0 cycles`；writer freeze 仍为 `10 / 54 / 15 / 25 / 23 / 32`。
- Black、isort、`py_compile` 与 diff check 通过；`check_mypy_regression.py` 因缺 Django plugin 只报告 regressions `0`，不作为完整 mypy 通过证明。

### 2026-08-13：M1 Risk Center 人工 subject / 审批写入面

已完成：

- 新增只接受 subject/operator ID 与版本的 subject 注册用例；可信 definition 由 Research Infrastructure 按 canonical Operator Spec 与 activation chain 解析，调用方不能提交 definition hash、权限或 supersession。
- subject 与 approval 分两次 append-only 写入，分别保留服务端注册/审批时钟；已有 exact subject 可幂等重放，first-winner 冲突和知识时钟倒置均失败关闭。
- composition root 只从 Django `request.user` 构造 human staff actor；注册人和审批人同时按 actor ID 与 user ID 禁止自审批。
- 增加 SessionAuthentication、CSRF、authenticated staff、POST-only 的注册/审批端点；serializer 精确拒绝 caller 提交 actor、hash、`as_of` 或任何未声明字段，Interface 不直接导入 ORM。

仍未完成：

- 当前默认 Python 缺 DRF，备用环境又不满足项目 Django/Celery 声明，因此新增 HTTP 与数据库 component 测试尚未在完整项目 runtime 取得通过证明；不得把纯测试当作生产 HTTP 验收。
- PostgreSQL 真实并发 first-winner、用户/租户 owner scope、生产角色治理和真实人工审核记录仍待完成。

本阶段验证：

- 纯 Application 测试 `13 passed`；architecture delta 与全量 architecture verify 均为 `0 boundary / 0 audit violations`。
- 4 个非 DRF 生产文件 standalone strict mypy `0 issues`；13 个目标文件 Black/isort 通过，compileall 通过。
- 未验证：完整项目 DRF/API/component、DRF 项目级 mypy、PostgreSQL 并发。跨 App approval projection 已移入 `core/integration` composition root，Research Application 只保留数据型投影和自身 Protocol；带 allowlist 的 module-cycle gate 恢复为 207 条边、0 cycle。

仍未完成：

- M0 尚需扩展 R7/R8、Broker 以外其余动态 dict/TypedDict/interface/query payload、mixed/variant 分类，以及其余 MCP read 的 raw/governed 语义；owner/接口矩阵、HTTP/SDK/TUI/MCP 写入口、10 个 Transition Plan 内部 writer、54 个显式高风险输出、18 个动态 query/GET/presenter 面及 18 个 MCP P0 发布面已冻结。
- M1 的用户/租户 scope 模型与 owner-scoped 授权、人工审批写入面的完整项目 runtime/component 证明、并发 first-winner PostgreSQL 验证和其余 App Application adapter 仍未完成；staff-only exact read API、Operator Spec lifecycle、Risk Center approval provider、Research↔Risk read composition、人工 subject/审批写入面代码，以及 Data Center quote/Broker approval snapshot 两个 legacy adapter 已完成。
- M2–M5 全部交付及真实生产切换证据。

本阶段验证：

- `python scripts/check_decision_write_surface_freeze.py`：通过，Transition Plan writers `10`、HTTP `54`、SDK `15`、TUI decision `25`、TUI mutation `23`、MCP position-write `32`。
- `python scripts/check_evidence_output_surfaces.py`：通过，outputs `54`、direct-position `11`、marker-discovered `45`、dynamic `18`；最新专属纯 Python `9 passed`。
- Domain 与 freeze guard 聚合纯测试：`22 passed`。
- Django 5.1/SQLite 内存库逐项执行 persistence component 场景：`8 passed`；覆盖 exact replay/fork、三模型 ORM mutation/delete shortcut、raw SQL tamper、公共 reader 写隔离与 future PIT 拒绝。
- Django 4.2/DRF 3.16 最小 settings 下 exact read API/facade：`18 passed`；覆盖 staff 权限、精确 selector、未来 cutoff、非枚举 404、三类 payload 和全部写方法 405。
- Operator Spec lifecycle 纯 Domain/Application/codec 与 migration 静态测试：`11 passed`、standalone strict mypy `0 errors`；Django 5.1/SQLite lifecycle component 场景：`3 passed`，覆盖原子激活/幂等读取、空 ledger/直接 ORM 写阻断及数据库级并发 root/child fork 拒绝。
- `EvidenceSummaryDTO` 纯 Application 测试：`5 passed`、standalone strict mypy `0 errors`；覆盖四种 Track Record 可用态及 operator/track substitution 拒绝。
- `black --check`、`isort --check-only`、`compileall` 与 `git diff --check`：通过；Domain/codec standalone strict mypy：`0 errors`。
- 未验证：当前机器没有同时具备完整项目依赖与 pytest-django 的 runtime，标准项目 settings 下的 component/API pytest、完整 `manage.py check`、`makemigrations --check`、PostgreSQL 并发 first-winner 与真实 Risk Center provider 集成仍待项目 runtime/CI 和后续批次执行。

## 一、目标与既定决策

把现有分散的 PIT、freshness、Promotion、OOS、`must_not_execute`、Scoreboard 和人工证伪能力，统一成贯穿研究输出、TUI、组合决策和执行的硬约束。

已确定：

- 覆盖 R1–R8 及 Regime、Policy、Pulse、Alpha、Signal、Strategy 等全部决策链路。
- 正式切换后立即硬阻断，不保留“只警示仍可执行”的生产模式。
- 所有既有模型和研究输出初始均为 `SHADOW`，不继承旧权限。
- 任何增加主动风险或人工 Override 都必须签署不可变理由和证伪条件。
- 每个账户只有一个事前确定的主政策基准。
- 采用保守风险额度；所有阈值存在 Risk Center 数据库中，版本化、可审计，代码无默认金融参数。
- 不修改现有 R1–R8 的 `blocked/research-only` 结论，也不通过回填伪造历史证据。

## 二、核心架构与公共合同

### 1. Research：统一输出级 Evidence Envelope

在 Research Domain 建立正交合同，不增加单一 `evidence_tier`：

- `ClaimKind`：`OBSERVATION / DERIVED / ESTIMATE / FORECAST / RECOMMENDATION`
- `MethodKind`：`IDENTITY / DETERMINISTIC / STATISTICAL / SIMULATION / HUMAN_JUDGMENT`
- `GovernanceState`：`RESEARCH_ONLY / PROMOTED / DEGRADED / RETIRED / BLOCKED`
- `DecisionPermission`：`DISPLAY_ONLY / ADVISORY / DECISION_ELIGIBLE / EXECUTION_ELIGIBLE`
- `DependencyFlag`：估计输入、预测输入、模拟输入、人工判断输入
- reliability 直接复用现有 fresh/stale/missing/conflict 等合同，不另造一套状态。

核心不可变对象：

- `ArtifactRef`：owner、类型、ID、版本、内容哈希。
- `EvidenceOperatorSpec`：声明输出 claim/method、研究 family、必需输入、PIT/freshness 条件、最大权限和 Track Record 政策。
- `EvidenceEnvelope`：输出分类、治理状态、有效权限、完整 lineage、依赖 flags、Track Record 引用、blockers、有效期和哈希。
- `TrackRecordSnapshot`：绑定精确 artifact 版本、target、horizon、样本政策和评估时点。

传播规则：

- lineage 和不确定性依赖取并集。
- 只有 `DecisionPermission` 是有序轴，取算子上限、必需输入、当前 Promotion、监控和 Track Record 中最严格者。
- 任一必要输入 stale、missing、conflict、PIT 失败或 hash 不符，输出降为 `DISPLAY_ONLY`。
- Promotion 不向下游自动继承。
- claim/method 由已激活的 Operator Spec 决定，调用方不能填写。
- Track Record 不得跨模型版本、target 或 horizon 借用。
- `valid_until` 取输入、Promotion、监控、Track Record 和算子合同最早到期时间。
- 兼容布尔字段统一由 Envelope 派生，禁止出现互相矛盾的双真源。

例如 R8：

```text
claim_kind       = RECOMMENDATION
method_kind      = DETERMINISTIC
dependency_flags = ESTIMATED_INPUT + FORECAST_INPUT
permission       = 所有上游和自身证据的最严格交集
```

Research 新增 append-only Operator Spec、生命周期、Track Record、Envelope 和 Lineage 表；外部 App 只保存 identity/hash，不建跨 App ORM 外键。迁移为 schema-only、zero-seed、zero-backfill。

### 2. Track Record

统一快照至少包含：

- artifact/version/hash、target、horizon、样本政策；
- OOS 窗口、评估时点和有效期；
- eligible、resolved、unresolved、censored、invalidated 完整分母；
- `n_eff`、coverage、市场状态覆盖；
- 主指标、单位、方向、事前基准、skill delta、置信区间；
- drift、Promotion、原始 outcome 引用和内容哈希。

约束：

- 分母状态必须完整守恒。
- `n_eff` 不得超过可评分样本。
- `eligible=0` 时不得生成绩效或置信区间。
- 决策时固定当时可见的 Track Record；未来成绩不能回写历史 Envelope。
- Signal/Data Center 保留原始事实，Audit 负责计算，Research 封存可用于决策的版本化快照。
- 现有 Forecast Scoreboard 继续作为诊断页面，不能直接作为 Risk Gate 真源。

指标按能力分别定义：

- R1/R3：MAE、RMSE、WAPE、修订误差、相对简单基准改善。
- R4：风险预测兑现误差和目标风险偏差。
- R5：金样本对账与扣成本相对价值表现分开。
- R6：log loss、balanced accuracy、持续期和转移校准。
- R7：Brier、log loss、校准和相对基准 skill。
- R8：扣成本主动收益、跟踪误差、回撤、换手和成本。
- R2 默认为描述性能力，不包装成预测。

### 3. TUI Evidence Strip

TUI metadata 墁加：

```json
{
  "evidence_binding": {
    "mode": "required",
    "claim_kind": "forecast",
    "track_record": "required"
  }
}
```

规则：

- 所有影响决策的 primary action 必须声明证据绑定。
- `FORECAST/RECOMMENDATION` 必须绑定 Track Record。
- 证据缺失、损坏或版本不匹配时，整个结果进入 blocked view，不允许正常展示后继续操作。
- Evidence Strip 固定放在标题之后、业务结果之前，不可关闭或折叠；必须同时使用文字和颜色。
- `n=0` 显示“无已兑现样本外记录；仅供研究展示；不得据此增加仓位或执行交易”。
- 查询失败显示“历史记录不可核验”，不能冒充 `n=0`。
- 现有把行数、字段数称为“当前证据”的文案改为“结果规模”。
- 自定义 renderer 也必须由 Workbench 外壳统一包裹 Evidence Strip。

所有决策输出 DTO 内嵌紧凑 `EvidenceSummaryDTO`；详细信息通过认证、owner-scoped 的只读 Evidence API 查询。旧读客户端保持兼容，旧执行客户端缺少新 receipt 时返回稳定 blocker code 并拒绝执行。

### 4. Risk Center：证据授权与主动风险额度

新增版本化数据库对象：

- `AuthorizationTier`：`SHADOW / ADVISORY / LIMITED / QUALIFIED`
- `EvidenceRiskAuthorizationPolicy`
- `EvidenceRiskAuthorizationReceipt`
- `RiskBudgetReservation/Event`
- 可从事件重建的预算余额投影

升级规则：

- 所有 artifact 切换时统一为 `SHADOW`。
- 升级必须同时满足 Evidence policy、有效 Promotion、健康监控，并由有权限用户显式批准；不自动升级。
- 证据过期、漂移、版本变化、证伪或 lineage 不完整时自动降级。
- `SHADOW/ADVISORY` 的模型归因主动风险额度均为 0。

首个数据库策略 `evidence-risk-conservative-v1`：

| 条件/额度 | LIMITED | QUALIFIED |
|---|---:|---:|
| `n_eff` | ≥24 | ≥60 |
| Coverage | ≥70% | ≥85% |
| 市场状态覆盖 | ≥2 | ≥3 |
| 相对基准 skill | 90% CI 下界 ≥0 | 95% CI 下界 >0 |
| 健康监控期 | ≥30天 | ≥90天 |
| 单 artifact 主动权重增量 | 2% NAV | 5% NAV |
| 同 research family 合计 | 5% NAV | 10% NAV |
| 单资产主动偏离增量 | 1% NAV | 2% NAV |
| 年化 Tracking Error 增量 | 0.50% | 1.50% |
| 单日相关换手 | 3% NAV | 8% NAV |

V1 不允许模型增加杠杆。最终限制始终取证据额度、账户政策、全局风险 Floor、Broker 限制和市场流动性限制中的最小值。

多个模型共同产生一个计划时，V1 将完整风险增量分别计入每个 artifact 和 family，调用方不能自行填写归因比例。计划批准时原子预约额度，成交后转为已消费额度，取消、拒绝、过期时释放，防止拆单绕过。

所有阈值通过受治理的 Application Use Case/TUI 管理并落库，保存 actor、理由、版本、内容哈希、生效时间和 supersedes 引用；运行时无代码 fallback，缺少 active policy 即阻断。

### 5. Portfolio、Signal 与 Broker 硬闸

Portfolio 新增不可变 `DecisionRationaleAttestation`：

- plan及其 payload hash；
-账户、决策和组合快照；
- 政策基准快照；
- 人工理由、投资假设；
- 结构化证伪条件和人工描述；
- review_by；
- Evidence 和授权 receipt 引用；
- `human/ai_assisted` 来源；
- 签署人、服务器时间、版本和内容哈希。

规则：

- 任何增加主动风险或人工 Override 必须签署。
- AI 可以提供独立草稿，但人工理由字段必须由用户填写并显式签署。
- 原记录不可编辑；修正只能 supersede。已生成 Broker 批准订单后必须重建计划。
- Override 只能覆盖系统的软建议，不能覆盖 Evidence 权限、`n=0`、SHADOW、过期/缺失证据、基准缺失、kill switch、现金约束或硬风控上限。
- 人工独立计划可以走现有账户风险政策，但不得继承或一键复制 SHADOW/ADVISORY 输出的目标权重。

纯风险降低按指标判断，不按 BUY/SELL 文本判断。缺少协方差时仅允许严格 safe harbor：减少或关闭已有多头、不新开仓、不加仓、不做空、不减少现金、不在同一计划复投卖出资金。

Signal 的证伪检查改为三态：

```text
TRIGGERED / CLEAR / INDETERMINATE
```

缺数据或 provider 不可用必须返回 `INDETERMINATE`，不能伪装为 CLEAR。Portfolio 保存 append-only 检查 receipt 和复核案件；Task Monitor 只调度、聚合和告警，不拥有业务判断。

Broker Order 必须绑定：

- plan ID/hash；
- attestation ID/hash；
- authorization receipt ID/hash；
- benchmark snapshot；
-有效期。

在创建、人工批准、Agent lease 和 submitting 四个节点重新核验。证伪、过期或授权失效时，未提交订单进入 `DECISION_REVIEW_REQUIRED`；已提交或已成交订单只产生 P0 人工复核，不自动撤单或平仓。

### 6. 账户级 Policy Benchmark

Portfolio 新增独立的长期政策基准，不能复用当前配置候选或现有可覆盖 benchmark component。

每个账户同时只能有一个 active 主基准，定义锁定：

- 资产代理、目标权重、现金和 fallback；
- 生效时间、基础币种；
- 再平衡日历和节假日规则；
- 估值时钟、价格和 FX fixing；
- 费用、滑点、税费；
- 现金收益率；
- 公司行动；
- 缺价和最大陈旧度；
- 主比较指标及评估窗口。

定义和每日影子估值账本均 append-only。修改只能开启新 epoch，不回写历史；新 epoch 重新开始裁决窗口。

估值规则：

- 入金/出金属于外部现金流，通过单位份额中和。
- 股息、利息和现金利息属于内部收益。
- 拆并股调整数量但不制造收益。
- 实盘和基准使用相同币种、估值截止时间、共同有效日期和可比成本。
- 缺关键价格、FX 或公司行动时 fail closed。
- Live shadow 不做历史可信回填；历史 replay 独立标记并绑定 PIT manifest。
- 无 active 政策基准的账户不得授权新增主动风险。

Audit 展示扣成本 TWR、主动收益、波动、下行风险、最大回撤、Tracking Error、Information Ratio、换手和成本。系统只陈述指定期间是否观察到净增益，不自动宣称“有/无 alpha”。

### 2026-08-13：Account owner assignment evidence Domain 合同

- 新增Account-owned两人制assignment evidence，显式区分字符串canonical Account identity与整数SimulatedTrading row provenance，禁止cast推断身份；raw row observation与creation/migration/manual-reclaim精确receipt均绑定owner/type/id/version/hash。
- authoritative assignment必须由claimant本人声明并由另一名human staff按actor ID与user ID双重隔离审批；legacy-default不得声称owner，且只能绑定exact migration receipt。issued/approved/recorded/valid时钟与identity/content hash全部封存。
- 相邻successor保持同一Account、underlying row与row-observation identity，精确绑定predecessor并推进version/clock。合同固定`evidence_only + inactive + must_not_execute`，不提供激活或执行权限。

未完成与验证：

- 纯Domain `25 passed`；standalone strict mypy、Black/isort、architecture（2750 files / 0 violations）与diff-check通过。项目mypy配置因环境缺`mypy_django_plugin`未直接运行。
- 尚无ID-only Application workflow、assignment ledger/provider、simulated observation adapter、人工接口或composition；现有mutable account row与0013默认user仍不能获得owner背书，总闸不变。

### 2026-08-13：Account raw-source assignment evidence 类型收口

- raw identity source 不再为 `legacy_default` 接受旧的专用 artifact type；authoritative 与 legacy-default 均只接受 Account owner 的正式 `account_owner_assignment_evidence`，由 `assignment_state` 表达语义差异，避免跨层 adapter 改写类型或伪造 hash/header。
- 同步收紧 Domain、Application DTO、ORM constraint 与 zero-seed `0038` migration state；authoritative 仍必须携带正数 owner，legacy-default 仍禁止声称 owner，unknown 仍禁止携带任何 assignment evidence。
- `0038` 尚无 seed/backfill 或生产 composition，因此本次是未激活合同的前向修正，不升级任何 mutable account row，也不为历史 `0013` 默认用户生成证据。

未完成与验证：

- raw-source Domain/Application 纯测试 `40 passed`；standalone strict mypy、Black/isort 与 diff-check 通过。当前默认 Python 缺 Django，完整 migration state/no-drift 与 Django component 未在本环境复跑。
- 正式两人 assignment Application 的 subject/evidence 双账本、exact migration/manual-reclaim provenance provider、SimulatedTrading observation adapter 和 composition 仍未完成；无 exact provenance 时必须零写，总闸不变。

### 2026-08-13：Account owner assignment 两阶段 Application workflow

- 新增 ID-only subject 注册与 staff 审批用例。注册命令只携 evidence、row observation 与 provenance receipt 的 ID/version；claimant 只能来自 exact-current Account provenance receipt，不能由命令或审批者代填。审批者只来自当前 server-authenticated human-staff actor，并按 actor ID 与 user ID 双重禁止自批。
- Application 在同一 repository transaction 与单一 authoritative cutoff 内，对 exact row observation、provenance receipt 和 persisted subject 首末双读；provider 缺失、过期、替换、二读漂移、legacy 缺 exact migration receipt均在 append 前 fail closed。first-winner replay绑定原 claimant/approver，successor predecessor由 logical head 推导并交给 repository CAS。
- subject 对完整 row、receipt、claimant 与时钟建立 canonical content hash，最终 Domain Evidence显式封存 `subject_content_hash`；exact/current readers补齐 exact command validation，superseded head或语义selector替换不能作为current返回。
- 最终 Evidence仍固定 `evidence_only + inactive + must_not_execute`，该流程仅封存账户owner事实，不提供账户激活、Broker namespace绑定或执行权限。

未完成与验证：

- Domain/Application 纯测试 `37 passed`；standalone strict mypy、Black/isort、architecture（2754 files / 0 violations）与diff-check通过。
- subject/evidence append-only ledger、owner-side exact creation/migration/manual-reclaim receipt ledgers/providers、SimulatedTrading row observation adapter、composition与认证Interface仍未完成；`0013`无逐账户migration receipt，legacy路径默认保持Unavailable/零写，总闸不变。

### 2026-08-13：Account owner assignment subject/evidence append-only ledger

- 新增独立subject/evidence两表账本：subject完整封存exact row observation、Account provenance receipt、claimant与requested/valid clock，并对identity、row binding、provenance binding和canonical content建立first-winner；Evidence以OneToOne FK和独立`subject_content_hash`双重绑定获批subject，不能把同一plan/account事实下的另一个申请替换进来。
- repository只在私有UOW/exact insert claim内允许写入；save/update/delete/bulk/raw全部阻断。Evidence同一Account字符串identity、underlying整数row及row observation logical chain只允许单root和单predecessor successor，append使用current-head CAS。
- 所有identity/hash/PIT/current读取都先closed-world恢复完整subject表，再恢复完整Evidence表并复核canonical payload、actor、provenance、FK、header/identity/content/ledger seals及`persisted_at == authoritative recorded_at`，之后才按selector和cutoff分链；过期或inactive的最终successor仍是logical head，不回退旧记录。
- `0039_account_owner_assignment_evidence_ledger`只创建两张空表并依赖`0038`，无RunPython/RunSQL，不为mutable account row或`0013`默认user补写任何subject/Evidence。

未完成与验证：

- Django 5.2.16 SQLite component `12 passed`；Account `makemigrations --check --dry-run`为`No changes detected`，ruff、Black/isort、architecture（2762 files / 0 violations）与diff-check通过。
- PostgreSQL双事务root/predecessor race、完整项目回归及全目标mypy plugin仍未验证；owner-side creation/migration/manual-reclaim receipt provider、SimulatedTrading observation adapter、composition和认证Interface均未完成。账本固定inactive/evidence-only，不解除namespace或执行总闸。

### 2026-08-13：Account physical account-row observation Domain 合同

- 新增Account-owned immutable physical-row observation，逐项封存canonical字符串Account identity、整数underlying row provenance、exact SimulatedTrading raw-source ref，以及row当前nullable user、原始account type、active状态与created/updated时钟；字符串与整数namespace不做cast。
- 无论row_user_id为空或已有值，`owner_assignment_state`都固定为`unknown`；当前user、staff/system标记或历史`0013`默认回填不能被本合同解释成authoritative owner。该合同只提供后续provenance receipt/assignment workflow可精确引用的物理事实锚。
- observed/recorded、raw-source validity和TTL进入canonical hash，validity取严格最早值；同一logical row successor必须推进observation/raw-source version和时钟并绑定前序hash。PIT final head若inactive或过期返回None，绝不回退旧active行。
- 合同固定`evidence_only + inactive + must_not_execute`与provider blocker；它不是owner assignment evidence、账户激活或Broker execution identity。


- 纯Domain `25 passed`；standalone strict mypy、ruff、Black/isort、architecture（2768 files / 0 violations）与diff-check通过。
- 尚无ID-only capture Application、append-only observation ledger、SimulatedTrading typed row provider、creation/manual-reclaim/migration provenance receipt或composition；mutable row与历史默认user继续不可签发owner evidence，总闸不变。

### 2026-08-13：Account physical account-row observation Application workflow

- 新增8字段ID-only capture selector，只接受observation/raw source/Account字符串/underlying整数身份；hash、nullable row user、raw account type、active、row时钟、actor、server cutoff与predecessor都不能由调用方填写。
- consumer-owned exact physical Simulated row DTO逐项保留nullable user、原始account type/active、row created/updated、source identity/content/validity；assignment state继续固定unknown，不把当前user或real/active瞬时状态解释为owner。
- capture在单一repository cutoff对raw row首末双读，server human-staff actor绑定first-winner replay；logical head和predecessor由repository读取并交给append CAS。exact historical PIT与closed-current reader分离，inactive/expired final head不回退旧记录。
- Application仅依赖Domain与注入Protocol，无ORM或跨App implementation import；结果继续固定inactive/evidence-only/must-not-execute。


- Domain/Application纯测试 `40 passed`；standalone strict mypy、ruff、Black/isort与architecture（2772 files / 0 violations）通过。
- 当前仅Protocol+pure fake；append-only observation ledger、SimulatedTrading owner adapter/composition、真实staff actor与creation/manual-reclaim/migration provenance receipt仍未完成，owner assignment和执行总闸不变。

### 2026-08-13：Account physical account-row observation append-only ledger

- 新增strict codec、单表append-only model与私有UOW/exact insert claim；observation identity/content、raw-source identity和logical physical row root/predecessor均first-winner，append以current-head CAS拒绝fork与orphan。
- repository在任何identity/hash/PIT/current selector前closed-world恢复全表，复核raw row/source、captured actor、canonical payload、identity/content/root/predecessor/header/ledger seals及`persisted_at == recorded_at`；双selector/header篡改不能隐藏坏行或重放旧head。
- direct save/raw、QuerySet update/delete、bulk create/update全部阻断；historical exact与logical current分离，final inactive或expired observation不回退旧记录。`0040_physical_account_row_observation_ledger`仅CreateModel、zero-seed，无RunPython/RunSQL，不回填SimulatedAccount历史行。
- 账本固定unknown owner、inactive/evidence-only/must-not-execute；不接SimulatedTrading adapter、provenance签发、owner assignment或Broker execution identity。


- Django 5.2 `--no-migrations` SQLite component `21 passed`；Account `makemigrations --check --dry-run`为`No changes detected`；增量mypy `0 regressions`，ruff、Black/isort、architecture（2777 files / 0 violations）与diff-check通过。
- 真实0040 migrate/rollback、PostgreSQL双事务root/predecessor race、SimulatedTrading typed provider/composition和生产staff actor未验证；无exact owner provenance receipt时assignment继续零写，总闸不变。

### 2026-08-13：Account owner-assignment provenance receipt Domain 合同

- 新增单一closed discriminated Account receipt，统一封存`creation / manual_reclaim / migration`三类claimant-side provenance；共享identity、物理row、clock、hash和successor规则，只由branch invariant映射固定artifact type与语义，避免三套类型漂移。
- receipt精确绑定Account-owned `physical_account_row_observation`的owner/type/id/version/identity/content hash、row validity，以及Account字符串identity和underlying整数row identity；可选helper会对完整Physical observation做exact重验。
- creation/manual reclaim为authoritative claimant声明，assigned owner必须等于claimant user；migration只允许当前human-staff reviewer声明`legacy_default`且assigned owner恒为None。它不追认`0013`执行者、first superuser/system user或当前row user为历史owner。
- issued/recorded/valid时钟与row有效期闭合，canonical identity/content hash、root/successor与PIT final过期不回退完成；固定`evidence_only + inactive + activation_available=false + must_not_execute=true`。第二人审批仍由后续owner-assignment Evidence workflow持有，不塞进claimant receipt形成伪两人制。


- provenance+physical-row Domain组合 `57 passed`；standalone strict mypy、ruff、Black/isort、architecture（2773 files / 0 violations）与diff-check通过。
- 尚无provenance receipt Application、append-only ledger、真实creation/manual-reclaim/migration签发入口/provider或与现assignment DTO的adapter；没有exact receipt时legacy/owner assignment继续Unavailable并零写，总闸不变。

### 2026-08-13：Account owner-assignment provenance receipt Application workflow

- 新增5字段ID-only签发命令，只接受receipt ID/version、closed provenance kind和physical observation ID/version；hash、账户、owner、row事实、actor、clock、validity与predecessor均由trusted owner source和server边界提供。
- exact-current Physical observation provider在同一repository cutoff首末双读；creation/manual-reclaim使用当前authenticated claimant，migration只允许当前human-staff legacy reviewer且不会声称owner。row source缺失、过期、替换或二读漂移均在append前fail closed。
- persisted wrapper封存原authenticated issuer，跨时钟first-winner仅允许同actor replay；logical receipt head与predecessor由repository派生并以append CAS闭合。historical exact PIT和full-selector closed-current inactive readers分离，superseded/expired final head不回退。
- Application复用Account assignment稳定错误taxonomy，只依赖Domain与注入Protocol，无ORM或跨App implementation import；所有receipt继续inactive/evidence-only/must-not-execute。


- provenance/physical Domain+Application组合 `75 passed`；增量mypy `0 regressions`，ruff、Black/isort与diff-check通过。
- 当前仅Protocol+pure fake；append-only provenance ledger、真实physical row owner provider/composition、认证签发入口和assignment consumer adapter仍未完成。`0013`没有逐账户receipt，legacy路径继续Unavailable/零写。

### 2026-08-13：SimulatedTrading simulated-account row source Domain 合同

- 新增SimulatedTrading-owned immutable row source，固定owner/type/schema并精确封存source ID/version、canonical Account字符串identity、underlying整数row identity，以及nullable row user、原始account type/active、created/updated时钟；字符串与整数不做cast。
- owner assignment state固定unknown，不携带owner/provenance claim；当前user、`0013`默认回填、staff/system标记或mutable row状态不能由本合同升级为Account owner evidence。
- observed/recorded、source validity与TTL进入canonical hash并取严格最早有效期；显式`is_present/is_tombstone`表达row删除，不用缺行或请求时钟伪造事实。successor绑定前序hash、同logical row、推进source version与时钟且row clock不倒退。
- PIT final source若inactive、tombstone或expired返回None且不回退旧版本；固定`evidence_only + inactive + activation_available=false + must_not_execute=true`，不直接实现Account consumer adapter或签发owner assignment。


- 纯Domain `29 passed`；standalone strict mypy、ruff、Black/isort、architecture（2780 files / 0 violations）与diff-check通过。
- 尚无Application capture、append-only source ledger、覆盖所有SimulatedAccount create/update/delete路径的事务性writer、Account adapter/composition或历史backfill；禁止用`str(pk)`、`updated_at`、请求`now()`、临时hash/TTL冒充本source，总闸不变。

### 2026-08-13：SimulatedTrading simulated-account row source Application workflow

- 新增6字段ID-only capture selector，只接受source ID/version、canonical Account字符串identity与underlying整数row identity；hash、nullable row user、raw account type/active/row clocks、actor、validity和predecessor均来自typed owner observation与server边界。
- consumer-owned raw observation必须已经携带owner-issued observation ID/version/content hash、observed_at和source validity；Application只原样封存，不允许从`updated_at`、请求`now()`、ORM pk或临时JSON计算这些authority字段。
- capture在单一repository cutoff首末双读raw observation，server human-staff actor绑定first-winner；logical head/predecessor由repository派生并交给append CAS。historical exact PIT与closed-current reader分离，final inactive、tombstone或expired不回退旧source。
- Application只依赖SimulatedTrading Domain与注入Protocol，无ORM或跨App implementation import；结果继续unknown-owner/inactive/evidence-only/must-not-execute。


- Domain/Application组合 `47 passed`；增量mypy `0 regressions`，ruff、Black/isort、architecture（2779 files / 0 violations）与diff-check通过。
- 当前仅Protocol+pure fake；append-only source ledger、统一覆盖create/update/delete的owner writer、production adapter/composition和Account physical observation映射仍未完成，任何provider缺失必须Unavailable/零写。

### 2026-08-13：Account owner-assignment provenance receipt append-only ledger

- 新增单表strict codec/model/repository，完整封存receipt identity/content、physical-row exact binding、claimant/issuer、authority/header/ledger与authoritative persisted clock seals；issuer必须与Domain claimant逐字段一致。
- 私有UOW与exact insert claim阻断direct save、raw save、update/delete、bulk路径；`(receipt_id, receipt_version)` first-winner、每`receipt_id`单root、每predecessor单successor，并以repository CAS闭合相邻链。
- 所有winner/exact/PIT/current与append冲突恢复均先closed-world恢复全表canonical payload和冗余seals，再按Domain selector过滤。current读取返回最终recorded successor，即使其已过期也不回退旧receipt。
- `0041_account_owner_assignment_provenance_receipt_ledger`只含`CreateModel`，zero-seed且无`RunPython/RunSQL`；迁移ModelState与live model逐字段、index、constraint同构验证通过。

验证与剩余边界：

- Django 5.2隔离组件 `10 passed`；既有provenance Domain/Application回归 `50 passed`；standalone strict mypy三生产文件0 issues，ruff、Black/isort、architecture（2782 files / 0 violations）与diff-check通过。
- PostgreSQL双事务root/predecessor race、真实`0041` migrate/rollback、production physical-row provider/composition、认证签发入口及assignment consumer adapter仍未完成；账本固定inactive/evidence-only，`0013`历史默认user不得回填或自动签发，总执行闸不变。

### 2026-08-13：SimulatedTrading simulated-account row source append-only ledger

- 新增SimulatedTrading owner单表strict codec/model/repository，封存nullable row user、raw account type/active/presence/tombstone、row/source/TTL clocks，以及identity/content、actor、row-fact、header/ledger与persisted-clock seals。
- 私有UOW/exact insert claim阻断direct/raw save、update/delete和bulk路径；`(source_id, source_version)`first-winner、完整logical-row selector单root、每predecessor单successor，并以current-head CAS闭合相邻revision。
- winner/exact/PIT/current和append冲突恢复均先closed-world恢复全表后再过滤；final inactive/tombstone/expired head不回退。`0021`仅`CreateModel`、zero-seed且无`RunPython/RunSQL`，migration state与live model同构。

验证与剩余边界：

- Django 5.2隔离组件 `3 passed`；既有Domain/Application回归 `47 passed`；standalone strict mypy三生产文件0 issues，ruff、Black/isort、architecture（2785 files / 0 violations）与diff-check通过。
- PostgreSQL双事务race、真实0021 migrate/rollback、统一覆盖SimulatedAccount create/update/delete的owner writer与raw observation provider未完成，因此production ledger保持zero-seed。下一可诚实阶段是owner侧Account physical-row provider：只能消费本ledger exact/current事实，空账本稳定返回None，不能从mutable ORM row临时发明hash/clock/validity。

### 2026-08-13：SimulatedTrading owner-side Account physical-row provider

- 新增owner-side read-only adapter：同一PIT先按`source_id/source_version`读取first winner，再按完整logical-row selector读取最终head；只有两者exact相等且source仍present、非tombstone、active、未过期时，才逐字段无改写映射为Account consumer DTO。
- final bad/expired successor、missing winner/head或winner已被supersede均返回None，不回退旧source；selector被owner repository替换时稳定报corruption。adapter不暴露append/UOW，也不从`SimulatedAccountModel.pk/updated_at`、请求clock或现场JSON发明authority字段。
- composition保留在SimulatedTrading owner侧，避免Account反向import SimulatedTrading形成app cycle；当前zero-seed ledger下provider诚实返回None，Account capture继续零写。

验证与剩余边界：

- provider pure tests `3 passed`；ruff、py_compile、architecture（2786 files / 0 violations）通过。
- owner raw observation/outbox与全create/update/delete事务writer仍未完成，故尚无production source rows；真实composition启动回归因本隔离环境缺Celery未执行。总执行闸与所有inactive权限保持不变。

### 2026-08-13：SimulatedTrading raw account-row observation Domain

- 新增 owner-owned immutable raw observation：精确封存 observation id/version/hash、物理row PK、nullable row user、原始account type、active/presence/tombstone、row create/update clock、owner observed clock与validity；固定`evidence_only/inactive/must_not_execute`，不声明账户owner或执行权限。
- root/successor合同要求同一observation id、row PK和row created clock，version、row updated与observed clock单调推进并精确绑定predecessor hash。PIT resolver返回最终可知raw head；最终tombstone/inactive仍保留为raw事实，最终过期则返回None且不回退旧head。
- 本阶段不把请求clock、consumer `recorded_at/TTL`或mutable ORM `updated_at`冒充owner issuance，也不从既有行自动回填。consumer source v1虽然读取raw `content_hash`，但尚未把它封进source envelope；后续必须新增source v2精确绑定raw hash，禁止静默改写v1。

验证与剩余边界：

- pure Domain tests `23 passed`；strict mypy、ruff、Black/isort、py_compile与architecture（2787 files / 0 violations）通过。
- owner Application、append-only raw ledger、exact-current provider/outbox，以及覆盖repository/gateway/portfolio writer、position valuation反写、Admin、management与delete tombstone的同事务writer均未完成；production source ledger继续zero-seed，总闸不变。

### 2026-08-13：SimulatedTrading raw account-row observation Application

- 新增 owner Application append/read contract：future owner writer只可提交exact Domain observation；`observation_version`固定承担owner transaction/outbox event identity，重试复用同version、另一已提交mutation必须使用新version。没有HTTP散乱row/hash/clock command。
- persisted envelope独立封存repository authoritative `recorded_at`，不修改owner `observed_at/valid_until/content_hash`。record use case以单一server clock完成identity first-winner、logical-head predecessor CAS、root/successor校验及append返回exact复核。
- exact PIT与closed-current read分离：tombstone/inactive可作为raw历史事实读取；current必须exact winner等于logical final head，superseded或final expired均None且不回退。

验证与剩余边界：

- Domain/Application组合 tests `31 passed`；strict mypy、ruff、Black/isort、py_compile与architecture（2788 files / 0 violations）通过。
- 当前仅Protocol+pure fake；append-only raw ledger、owner exact adapter/source v2 raw-hash binding与全writer同事务outbox仍未完成，production继续zero-seed且总闸不变。

### 2026-08-13：SimulatedTrading raw account-row observation ledger

- 新增strict codec、无mutable-row FK的单表append-only ledger与Application Repository实现；canonical payload、identity/content、fixed authority、row/clock、record/ledger及persisted-clock seals均在restore时闭合校验。
- private UOW/exact insert claim阻断instance/queryset/bulk/raw写删旁路；identity first-winner、每`(observation_id,row_pk)`单root、predecessor单successor与CAS完成。所有read先closed-world恢复全表再做selector/PIT，最终tombstone/expired logical head不回退旧版本。
- `0022`为schema-only、zero-seed单CreateModel迁移，无RunPython/RunSQL；UTC codec把等价offset统一为canonical `Z`，`recorded_at==persisted_at`由DB constraint与restore双重校验。

验证与剩余边界：

- Django 5.2 isolated component tests `5 passed`；codec/repository strict mypy、ruff、Black/isort、py_compile、migration state与architecture（2791 files / 0 violations）通过。
- PostgreSQL并发first-winner、真实0022 migrate/rollback、raw owner exact provider/source v2和全部账户writer同事务outbox仍未完成；账本保持zero-seed，既有行不回填，总闸不变。

### 2026-08-13：SimulatedTrading raw-bound account-row source v2 Domain

- 新建与v1完全隔离的`simulated_account_row_v2 / simulated-account-row.v2`合同；不改v1 canonical payload、hash或ledger，v1 consumer不会误收v2。
- v2显式封存raw observation的固定owner/type/schema、ID/version、identity/content hash、observed/valid clock和raw predecessor hash，全部进入source content hash。
- source ID/version强制等于raw observation ID/version，`observed_at`和`source_valid_until`强制原样绑定raw clock，`valid_until`只能取raw validity与server TTL的最早时点，禁止identity alias和请求时钟洗白。
- v2 root要求source与raw predecessor均为None；successor同时绑定前一v2 source content hash与前一raw observation content hash，两条CAS链不混用。PIT final inactive、tombstone或expired均不回退旧source。

验证与剩余边界：

- pure Domain tests `41 passed`；standalone strict mypy、ruff、Black/isort与architecture（2793 files / 0 violations）通过。
- 当前仅Domain；Application capture/exact-current raw revalidation、独立0023 zero-seed ledger、owner adapter、Account v2 consumer和全writer同事务outbox仍未完成。不允许v2查不到时fallback v1，生产仍zero-seed，总闸不变。

### 2026-08-13：SimulatedTrading raw-bound account-row source v2 Application

- 新增v2独立ID/hash-only capture；command只接受source/raw同源ID/version、expected raw content hash和Account/underlying选择子，row payload、hash、clock、validity与predecessor均不由caller提供。
- consumer-owned raw DTO会重建owner Domain observation，闭合固定owner/type/schema、identity/content/predecessor hash、row facts与owner clocks；provider只能返回exact identity/hash且等于logical final raw head的PIT事实。
- capture以单一server cutoff首末双读raw owner source，在私有UOW内处理first-winner、source logical head与predecessor CAS；root/successor同时检验source链与raw链相邻性。
- historical exact与current读面分离；current不仅要求source为final head，还会重读其封存raw identity/hash并要求raw仍为final head。raw已前进、source投影滞后、tombstone、inactive或expired均fail closed且不回退。

验证与剩余边界：

- Domain/Application组合 `56 passed`；standalone strict mypy、ruff、Black/isort与architecture（2793 files / 0 violations）通过。
- 当前仅Protocol+pure fake；0023 zero-seed ledger、raw owner adapter、Account v2 provider/composition和全writer同事务outbox仍未完成。v1仅保留historical兼容，不得作current fallback，总闸不变。

### 2026-08-13：SimulatedTrading raw-bound account-row source v2 ledger

- 新增独立strict codec、无v1/raw外键的单表append-only model与Application Repository实现；canonical payload与DB header双写闭合，raw binding、row fact、logical binding、clock、record与ledger seals全部restore重验。
- private UOW/exact insert claim阻断instance/raw、QuerySet update/delete和bulk create旁路；source identity、raw binding、logical root与predecessor均first-winner，append用current-head CAS拒绝fork/orphan。
- winner/exact/PIT/current和IntegrityError恢复都先closed-world恢复完整v2表，再按Domain selector过滤；无关行或双selector篡改不能隐身。final tombstone/inactive/expired logical head不回退。
- `0023_simulated_account_row_source_v2_ledger`仅`CreateModel`，依赖0022，zero-seed且无`RunPython/RunSQL`；不Alter/复用0021，不回填v1或mutable account rows。

验证与剩余边界：

- Django 5.2 isolated component `5 passed`；Domain/Application回归 `56 passed`；codec/repository strict mypy、ruff、Black/isort、architecture（2796 files / 0 violations）与module-cycle（206 edges / 0 cycles）通过。
- PostgreSQL并发race、真实0023 migrate/rollback、raw-ledger owner adapter、Account v2 consumer/provider和全writer同事务outbox仍未完成；production v2账本保持zero-seed，v1不作current fallback，总闸不变。

### 2026-08-13：SimulatedTrading raw observation → source v2 owner provider

- 新增owner-side只读adapter：在同一PIT先取raw observation identity first winner，再取`(observation_id, row_pk)` logical final head；只有两者exact同一record才继续。
- observation ID/version/content hash/row PK与recorded/observed/valid clocks逐项闭合，无改写映射为v2 consumer DTO；tombstone作为owner raw事实可读，missing、superseded、expired或future cutoff返回None且不回退。
- raw ledger的type/selector/closed-world腐败稳定翻译为v2 corruption；composition仅构造read-only provider，不暴露`append/atomic/now`，不构造Capture或writer graph。

验证与剩余边界：

- owner provider unit tests `8 passed`；strict mypy、ruff、Black/isort、architecture（2798 files / 0 violations）与module-cycle（206 edges / 0 cycles）通过。
- raw ledger与v2 source ledger均仍zero-seed；Account v2 consumer/provider、production canonical account selector与全writer同事务raw outbox仍未完成，因此provider当前诚实fail closed，总闸不变。

### 2026-08-13：Account physical-row observation v2 Domain

- 新增独立`physical_account_row_observation_v2`/`physical-account-row-observation.v2`，不修改或fallback既有v1；Account原样封存Simulated source v2与raw observation两层owner/type/schema、identity/content/predecessor hashes、知识时钟、有效期和present/tombstone事实。
- Domain重算source与raw两层canonical content hash，修复source v2此前仅校验raw hash格式、无法证明hash与封存行事实一致的缺口；root要求Account/source/raw三重predecessor均为空，successor逐层精确绑定前序hash。
- 三层时序与有效期固定为raw observed/valid、source recorded/effective valid、Account recorded/effective valid；final inactive、tombstone或expired均不回退旧active head，v1/v2类型替换fail closed。

验证与剩余边界：

- raw/source-v2/Account-v2 Domain回归`101 passed`；strict mypy、ruff、Black/isort与architecture（2799 files / 0 violations）通过。
- Account v2 Application、0042独立zero-seed ledger、Simulated owner-side provider与全writer同事务raw outbox仍未完成；既有provenance receipt仍只消费v1，执行总闸不变。

### 2026-08-13：Account physical-row observation v2 Application

- 新增ID/hash-only capture，用consumer-owned typed DTO完整接收source v2与raw observation headers/hashes/clocks/presence；provider分离`get_exact_final`与`get_exact_current`，前者允许terminal事实进入Account successor，后者只发布live decision read。
- Capture在同一Account server cutoff对source首末双读，first-winner replay绑定原actor，logical head派生三重predecessor并由repository CAS；exact PIT与full-observation closed-current reader分离，source/raw projection lag、substitution与final terminal均fail closed且不回退。
- Application保持零ORM/零跨App implementation import，不复用v1 DTO或table，也不提供任何执行权限。

验证与剩余边界：

- Account v2 Domain/Application pure tests `43 passed`；strict mypy、ruff、Black/isort通过。
- 0042独立zero-seed ledger、Simulated owner-side v2 provider/composition、production canonical selector和全writer同事务raw outbox仍缺；既有provenance v1与执行总闸不变。

### 2026-08-13：Account physical-row observation v2 ledger

- 新增独立strict codec、append-only model与closed-world repository；canonical payload与Account/source/raw/row/clock/actor/record/ledger冗余seals逐项复核，任何非目标行或selector header篡改也fail closed。
- private UOW/exact insert claim阻断direct save、update/delete、bulk/raw路径；identity first-winner、source binding、单root与单predecessor successor CAS由数据库约束和repository双层闭合，final terminal/expired head不回退。
- `0042_physical_account_row_observation_v2_ledger`仅CreateModel、zero-seed、无RunPython/RunSQL，不修改0040 v1表或历史行。

验证与剩余边界：

- Django 5.2 isolated SQLite component `2 passed`；Account v2 Domain/Application与owner provider pure回归`52 passed`；ruff、Black/isort、architecture（2805 files / 0 violations）通过。
- PostgreSQL并发race、真实0042 migrate/rollback、owner provider composition接入与全writer同事务raw outbox仍未完成；production账本保持zero-seed，provenance v1和执行总闸不变。

### 2026-08-13：SimulatedTrading source v2 → Account v2 owner provider

- 新增owner-side只读adapter：source v2 identity first winner必须与同PIT完整logical final head exact一致，才逐字段原样映射Account consumer DTO；ID/version/content hash、source/raw双层headers/link、row与三层时钟/validity均不改写。
- `get_exact_final`允许inactive/tombstone终态作为Account successor输入，`get_exact_current`仅对present、active、非tombstone、未过期head返回；missing、superseded、expired/future或projection substitution均None/Corruption且不回退。
- 独立composition仅构造read-only provider，不暴露source/raw ledger UOW、append、clock或Capture/writer graph；Account Application不import Simulated Infrastructure。

验证与剩余边界：

- owner provider unit tests `9 passed`；strict mypy、ruff、Black/isort、architecture（2805 files / 0 violations）与module-cycle（206 edges / 0 cycles）通过。
- source/raw/Account v2三账本仍zero-seed；production canonical account selector、Account composition wiring与全writer同事务raw outbox仍未完成，因此provider诚实返回None，总闸不变。

### 2026-08-13：SimulatedAccount raw mutation writer 安全前置

- raw Application新增typed physical-row mutation DTO与repository `database_alias/get_physical_row_head`契约；Django repository先closed-world恢复全账本，再跨opaque observation ID解析同一row的final head，防止新stream制造第二root。
- 新增transaction-bound writer：显式要求owner外层同DB alias事务，opaque observation ID作为稳定row stream、mutation version作为retry-stable event；create/update/delete分别构造present root、present successor与tombstone successor，并通过raw first-winner/predecessor CAS追加。
- 本批未接任何`SimulatedAccountModel`生产写入口、Admin、cascade或任务，未开启seed；缺owner外层transaction时稳定Conflict，不用post-save/on_commit或请求时钟伪造owner事实。

验证与剩余边界：

- raw Application/writer unit `11 passed`；Django 5.2 raw repository component `5 passed`；ruff、Black/isort通过。
- 上线前仍需一次性原子切换所有账户create/update/reset/delete、position valuation反写、gateway/portfolio、Admin、management与User cascade，并封死QuerySet/bulk/raw旁路；部分接入会让旧raw head被误报current，因此三账本继续zero-seed，总闸不变。

### 2026-08-13：Account v2 自动证据 recorder 语义修正

- Account physical-row v2不再复用v1 human-staff actor，改为独立fixed service recorder：`kind=service`、`is_automated=true`、`role=evidence_projector`；自动raw/source outbox无需伪造人工staff身份。
- Persisted envelope、strict codec、0042 model/migration与repository headers/seals统一改为`recorded_by`，recorder ID/service name/role/kind/automated状态全部进入recorder binding、record与ledger seal；DB fixed constraint拒绝human或非自动recording。
- 这只修正“谁记录技术证据”的provenance，不改变Account/source/raw owner、不声明owner assignment、不提升evidence-only/inactive权限，也不授予执行资格；v1人工actor合同保持不动。

验证与剩余边界：

- Account v2 Domain/Application pure `43 passed`、Django 5.2 component `2 passed`；strict mypy、ruff、Black/isort与diff-check通过。
- 0042仍为未部署zero-seed最终schema；production pipeline、canonical identity输入与全writer原子cutover仍未完成，总闸不变。

### 2026-08-13：SimulatedAccount 三账本 Evidence Pipeline 安全前置

- 新增未激活的Infrastructure pipeline，在调用方已经开启的同alias外层事务中固定按raw observation → source v2 → Account v2顺序投影；create/update/delete共用同一条编排，delete tombstone不会被降级成旧present版本。
- pipeline把raw observation ID/version/content hash原样交给source v2，再把source content hash原样交给Account v2；返回值逐阶段要求exact Domain type并重跑不变量，adapter替换对象稳定报corruption，不允许fallback v1。
- canonical-form Account namespace/string ID与underlying integer identity保持为显式`UnverifiedCanonicalAccountReference`，pipeline只校验shape及其与physical row selector闭合，绝不把typed input冒充Account owner authority，也不通过`str(pk)`或`int(account_id)`推导身份。pipeline不重复声明Account capture内部的service recorder，避免制造无法独立证明的provenance。

验证与剩余边界：

- pipeline unit `8 passed`；strict mypy、ruff、Black/isort、architecture（2807 files / 0 violations）与diff-check通过。缺外层事务时三阶段零调用；source失败不会调用Account阶段；每阶段返回对象替换均fail closed。
- 本批没有composition、model hook、Admin/cascade、任务或生产writer接线；typed canonical Account reference仍由未来Account-owner exact provider提供，当前不可由caller自报进入production。三账本继续zero-seed，总执行闸不变。

### 2026-08-13：Account owner-assignment claimant provenance receipt v2 Domain

- 新增独立v2 claimant receipt，固定绑定Account physical-row v2 owner/type/schema、ID/version/identity/content/predecessor、recorded/valid clock，以及source/raw content hashes、row user与active/present/tombstone事实；validator重新执行完整physical v2不变量并逐字段闭合，拒绝v1对象或仅格式正确的替代hash。
- `claimed_owner`与`legacy_default_claim`明确只是human claimant声明，不使用`authoritative`命名。creation要求claimant=claimed owner=live row user；manual reclaim只能claim claimant自己但不冒充旧row user；migration只能由human staff reviewer声明legacy default且owner保持空。
- 新签发只允许exact live row；terminal/expired head只保留历史审计语义并且不回退旧claim。receipt固定`evidence_only/inactive/must_not_execute`，不能发布authoritative identity；root/successor同时绑定receipt predecessor与相邻physical v2 row predecessor，issued/recorded clock必须推进。

验证与剩余边界：

- pure unit `22 passed`；strict mypy、ruff、Black/isort、architecture（2808 files / 0 violations）与diff-check通过。
- 本批仅Domain；ID/hash-only Application、0043 zero-seed ledger、独立staff approval evidence v2与authoritative canonical identity provider仍未完成，production pipeline不得接受caller自报身份，总闸不变。

### 2026-08-13：Account owner-assignment claimant provenance receipt v2 Application

- 新增严格6字段ID/hash-only issuance command，只接受receipt ID/version/kind与physical v2 observation ID/version/expected content hash；account、claimed owner、row payload、permission、validity和业务时钟全部由exact-current owner source、authenticated actor与server clock派生。
- issuance在repository UOW内用同一cutoff首末双读完整physical v2，重跑Account/source/raw三层hash与selector；creation/manual/migration actor矩阵在Application入口及Domain双重校验。first-winner replay绑定原authenticated actor与logical head，successor predecessor由repository head派生并交给append CAS。
- exact与closed-current reader均重新读取physical v2 exact-current head；upstream supersede、terminal、expiry或hash替换立即返回不可用/腐败，不回退v1或旧receipt。Application只签发claimant receipt，不发布authoritative Account identity。

验证与剩余边界：

- pure Application unit `9 passed`；strict mypy、ruff、Black/isort、architecture（2809 files / 0 violations）与diff-check通过。
- 本批仍只有Protocol+pure fakes；0043 zero-seed ledger、owner provider/composition、独立staff approval evidence v2与authoritative canonical identity provider仍未完成，production pipeline与writer cutover继续禁用。

### 2026-08-13：Account owner-assignment claimant provenance receipt v2 ledger

- 新增独立0043 append-only单表账本，strict codec封存完整physical/source/raw v2 row reference、claimant与authenticated issuer、fixed inactive authority、canonical payload、identity/content、row/actor/header/record/ledger seals和authoritative persisted clock；0043只CreateModel且zero-seed，不回填v1或mutable账户行。
- repository private UOW/exact insert claim阻断直接save、raw、update、delete与bulk路径；receipt identity first-winner、每receipt ID单root及每predecessor单successor由数据库unique与Application CAS共同闭合。root claim只绑定domain-separated logical receipt ID，不含候选content/version，竞争root必碰撞。
- exact/PIT/head与IntegrityError恢复均先按PK恢复并校验全表，再按canonical receipt selector和recorded cutoff分链；冗余ID/header双篡改不能隐藏successor并复活旧head。expired final successor不回退旧receipt。

验证与剩余边界：

- Django 5.2 isolated SQLite component `5 passed`，覆盖codec、first-winner/root/successor CAS、expiry no-fallback、全mutation guards、closed-world selector tamper与schema-only migration；migration/model state autodetect无漂移。strict mypy（隔离环境关闭Django第三方Any伪诊断）、ruff、Black/isort、architecture（2812 files / 0 violations）与diff-check通过。
- PostgreSQL双事务root/successor race与真实0043 migrate/rollback尚未验证；owner provider/composition、独立staff approval evidence v2与authoritative canonical identity provider仍未完成，production pipeline/writer继续禁用，总闸不变。

### 2026-08-13：Account owner-assignment staff approval evidence v2 Domain

- 新增独立v2 subject与staff approval evidence。subject持有并重新验证完整physical-row v2与claimant provenance receipt v2，只表示待审批claim；最终Evidence必须由不同actor ID且不同user ID的当前human staff approver签署，claimant receipt本身不会被提升成authority。
- `claimed_owner`经独立审批后才映射为`authoritative`且owner必须等于claimant；`legacy_default_claim`只映射为owner为空的`legacy_default`。Account字符串identity与underlying整数identity各有candidate-independent、domain-separated root claim，禁止双向多重映射。
- approval TTL可以缩短但不能延长两个upstream的最早有效期；Evidence successor精确绑定前序Evidence，并在physical或receipt推进时要求其predecessor精确闭合。最终过期或失效head不回退旧Evidence，固定`evidence_only/inactive/must_not_execute`。

验证与剩余边界：

- pure Domain unit `28 passed`；strict mypy、ruff、Black/isort、architecture（2813 files / 0 violations）与diff-check通过。
- 本批仅Domain；两阶段Application、0044 subject/evidence append-only账本、双向current provider与PostgreSQL并发尚未完成，因此production pipeline仍只能接收unverified canonical reference，全writer cutover与执行总闸保持禁用。

### 2026-08-13：Account owner-assignment staff approval evidence v2 Application

- 新增两阶段Application：注册命令只携带evidence、physical-v2与claimant-receipt-v2的ID/version/expected hash；审批命令只携带evidence ID/version与expected subject hash。账户、owner、权限、payload、approver和时钟均不能由caller提交。
- subject注册与staff审批都在repository UOW内使用同一server cutoff首末双读physical与receipt exact-current owner source。审批者由composition构造注入，必须human staff且actor ID/user ID均与claimant不同；换approver不得重放他人的first winner。
- 审批同时读取Account字符串identity与underlying整数identity两个logical head，必须双空或精确同一record；split head稳定报corruption。append用前序content hash CAS。历史exact reader与current reader分离；current还会重验双head及两个upstream final current，supersede/terminal/expiry不回退旧Evidence且无v1 fallback。

验证与剩余边界：

- Application unit `8 passed`，Domain+Application合跑`36 passed`；strict mypy、ruff、Black/isort、architecture（2814 files / 0 violations）与diff-check通过。
- 本批只有Protocol与pure fakes；0044 subject/evidence账本、数据库双root唯一约束、authoritative current provider/composition及PostgreSQL竞争测试仍缺，production pipeline和全writer cutover继续禁用。

### 2026-08-13：Account owner-assignment staff approval evidence v2 strict codec

- 新增独立strict codec，完整嵌套编码subject、physical-row v2、claimant provenance receipt v2与最终staff Evidence，不把上游对象压缩为caller提供的header/hash。decode会重建并重新执行三层physical与receipt/Evidence Domain不变量。
- 顶层与嵌套字段采用exact mapping/type、UTC `Z`与canonical encode→decode→encode相等校验；unknown key、非canonical datetime、bool/int替换以及physical/receipt/subject嵌套篡改均fail closed。

验证与剩余边界：

- codec unit `9 passed`；strict mypy、ruff、Black/isort与diff-check通过。
- 本批没有ORM/model/repository/migration；0044双表schema、双root DB约束、closed-world repository/component/PG race与authoritative provider仍未完成，不能把codec视为可签发或可查询账本。

### 2026-08-13：Account owner-assignment staff approval evidence v2 0044 schema

- 新增0044 schema-only双表：subject表封存完整canonical payload及physical/receipt exact headers；Evidence通过OneToOne PROTECT精确绑定subject，并封存approval、mapping、fixed authority、record与ledger seals。两表均使用私有UOW/exact insert claim，instance/QuerySet/bulk/raw update/delete路径固定阻断。
- Evidence root同时持有`account_root_claim_hash`与`underlying_root_claim_hash`，两列分别partial unique；successor必须两列均空并持有unique predecessor。DB check强制root/successor形态互斥、fixed v2 authority、staff approver与persisted clock；0044只有两项CreateModel且zero-seed。

验证与剩余边界：

- Django 5.2 isolated SQLite model/component `4 passed`，system check、ruff、Black/isort、architecture（2816 files / 0 violations）与diff-check通过。isolated设置刻意禁用migration modules，因此`makemigrations --check`只报告环境不支持、未作为no-drift证据。
- 本批没有repository；canonical payload/header/seal的restore、closed-world exact/PIT/双head链、IntegrityError恢复、真实0044 migrate/rollback与PostgreSQL四类竞争仍未验证，authoritative provider与production pipeline继续禁用。

### 2026-08-13：Account owner-assignment staff approval evidence v2 repository

- 新增Django repository，精确实现两阶段Application的8个Protocol方法。每次subject/evidence winner、exact/PIT、Account head、underlying head与append冲突恢复都先恢复全表canonical payload并逐列复核upstream/subject/approver/mapping/fixed authority/record/ledger seals和persisted clock，再按Domain selector分链；冗余header篡改不能隐藏successor。
- Account字符串identity与underlying整数identity分别构建完整单root链，验证predecessor存在、相邻successor、无fork/cycle/disconnect，逻辑head即使过期也不回退旧值。append要求两个方向的当前head精确相同并执行predecessor CAS；IntegrityError只在所有锚点恢复为exact candidate时幂等返回。
- 同步修正0044 migration的nested `Q` state表示，使migration state与当前两模型约束精确一致，不改变数据库约束语义或增加数据操作。

验证与剩余边界：

- Django 5.2 isolated models+repository component `9 passed`，完整Domain/Application/codec pure `45 passed`；ruff、Black/isort、architecture（2817 files / 0 violations）、migration state与diff-check通过。
- PostgreSQL双事务同Account、同underlying、交叉映射及同predecessor四类race、真实0044 migrate/rollback、authoritative current provider/composition仍未验证；因此账本zero-seed且production pipeline仍不得把caller reference视为权威，writer cutover继续禁用。

### 2026-08-13：Account authoritative mapping v2 read-only facade

- 新增Account Application只读facade：caller只能提交underlying namespace/id与aware PIT cutoff。facade先读Evidence v2最终underlying head，再委托既有current reader重验Account/underlying双head、physical-v2及claimant receipt-v2的最终current状态。
- 输出只包含canonical Account↔underlying mapping、approved owner与Evidence ID/version/content hash/validity；权限固定`identity_mapping_only`、`inactive`、`execution_allowed=false`。`legacy_default`、missing、superseded、terminal、expired或任一上游替换均返回None或稳定corruption，无v1/caller fallback。

验证与剩余边界：

- pure unit `11 passed`；strict mypy、ruff、Black/isort、architecture（2818 files / 0 violations）与diff-check通过。
- 本批不做production composition也不修改pipeline。首次create仍有硬循环：authoritative mapping依赖已存在physical-v2，而physical-v2 pipeline又需要canonical Account reference。在Account owner发布先于physical row的canonical identity allocation/creation artifact前，不得用`str(pk)`、caller自报或本facade自证解循环；production writer、pipeline与执行总闸保持禁用。

### 2026-08-13：Account canonical creation allocation/binding Domain

- 新增Account-owned `CanonicalAccountCreationAllocation`：在physical row存在前由server allocator保留opaque canonical Account ID。自助请求者必须是authenticated human `account_creator`且与requested row user一致；allocation不包含尚未存在的underlying row ID，request fingerprint只用于幂等，不得生成Account ID。
- 新增一次性`CanonicalAccountCreationBinding`：完整重验allocation与Physical-v2 live root，强制Account label、underlying row、row user、raw account type逐项一致，并产生candidate-independent Account/underlying双claim hash。非root、terminal、过期allocation或任一替换均拒绝。
- allocation固定`identity_allocation_only`，binding固定`identity_binding_evidence_only + pending_owner_approval`；两者都是`inactive`、`activation_available=false`、`must_not_execute=true`，不代替后续claimant声明、独立staff owner approval或执行激活。

验证与剩余边界：

- pure Domain unit `5 passed`；strict mypy、ruff、Black/isort、architecture（2819 files / 0 violations）与diff-check通过。
- 本批仅Domain，既有Physical-v2 canonical payload尚未封存allocation exact header，claimant creation receipt也未绑定creation binding。必须继续完成ID-only Application、allocation/binding append-only ledger、source/Physical/receipt新schema及全writer同alias原子cutover；在此之前现pipeline仍不得接受unverified caller reference，三账本zero-seed与执行总闸不变。

### 2026-08-13：Account canonical creation allocation/binding Application

- allocation命令仅携带allocation ID/version、request fingerprint和业务account type，不接受canonical Account ID、user、clock或权限。authenticated requester、opaque Account ID generator、allocator service、authoritative clock与validity TTL全部由composition注入；`(requester, fingerprint)` first-winner可跨时钟幂等重放，identity或request替换稳定conflict。
- binding命令仅携带binding、allocation与Physical-v2的ID/version/expected hash。用例在同一server cutoff首末双读exact-current-unconsumed allocation与exact-final Physical-v2 root，先核对allocation/Account/underlying/physical四个唯一锚，再用四锚幂等append；已消费allocation、source漂移、selector替换或不同first winner均fail closed。

验证与剩余边界：

- Domain+Application pure unit `9 passed`；strict mypy、ruff、Black/isort、architecture（2820 files / 0 violations）与diff-check通过。
- 本批仅Application Protocol与pure fakes；无ORM/ledger/composition，也未把allocation exact header纳入Physical-v2 canonical schema或把creation binding纳入claimant receipt。在后续新schema、allocation/binding账本及全writer同alias原子cutover前，现pipeline、production writer与执行总闸保持禁用。

### 2026-08-13：Account canonical creation strict codec

- Allocation codec完整编码/解码requester、allocator service、Account identity、request fingerprint、fixed authority、时钟及identity/content hashes；Binding codec嵌套完整Allocation与Physical-v2 canonical payload，解码时重建并重跑两层Domain不变量，不把上游压缩为caller提供的hash。
- 顶层及嵌套对象使用exact keys/types、UTC `Z`与encode→decode→encode canonical相等校验；unknown/missing key、bool伪int、非canonical clock、nested allocation/physical/claim/seal替换均fail closed。

验证与剩余边界：

- codec unit `12 passed`；strict mypy、ruff、Black/isort与diff-check通过。
- 本批无ORM/model/repository/migration/composition；0045 allocation/binding schema、closed-world repository/component、Physical-v2 allocation seal、claimant creation binding与全writer原子cutover仍缺，pipeline和执行总闸保持禁用。

### 2026-08-13：Account canonical creation 0045 schema

- 新增0045 schema-only双表：Allocation表封存canonical payload、requester/allocator、fixed authority及identity/content/record/ledger seals；Binding表以OneToOne PROTECT唯一消费allocation，并封存完整canonical payload、Physical root header、binder及对应seals。两表都使用private UOW/exact insert claim，instance/QuerySet/bulk/raw update/delete路径固定阻断。
- DB约束阻断allocation identity、canonical Account ID、`(requester actor/user, request fingerprint)`重复；Binding阻断allocation、Account claim、underlying claim和Physical content重放。fixed authority、self-service user一致、service role与`persisted_at == allocated_at/recorded_at`时钟封印也下沉到DB check。

验证与剩余边界：

- Django 5.2 isolated model/component `3 passed`，覆盖private claim/mutation guards、关键unique/check与0045 migration state/zero-seed；py_compile、ruff、Black/isort、architecture（2822 files / 0 violations）与diff-check通过。
- 0045只有两项CreateModel，无RunPython/RunSQL。本批尚无repository；canonical payload/header/seal restore、closed-world exact/current/first-winner、IntegrityError exact replay、真实migrate/rollback与PostgreSQL同allocation/Account/underlying/Physical竞争仍未验证，Physical allocation seal、claimant binding和pipeline/writer保持禁用。

### 2026-08-13：Account canonical creation repository

- 新增Django repository，精确实现Application全部Protocol：allocation identity/request/exact/current-unconsumed/append与binding identity/any-four-anchor/exact/append。每次读取、append前冲突复原都先恢复全表Allocation与Binding canonical payload，重建Domain后逐列核对requester/recorder/fixed/clock/hash/seals及OneToOne关系，再做PIT/selector。
- current-unconsumed只在exact allocation已记录、未过期且全账本中没有任一binding消费时返回；最终消费/过期不回退。append使用同DB alias事务、private UOW/exact claim及savepoint；IntegrityError仅在所有唯一锚恢复为exact candidate时幂等返回，否则稳定conflict。Binding append同时重验allocation仍current-unconsumed且allocation/Account/underlying/Physical四锚未被占用。

验证与剩余边界：

- Django 5.2 isolated models+repository component `9 passed`，其中repository `6 passed`，覆盖roundtrip/request/exact/PIT、consume no-fallback、four anchors、allocation/binding first-winner、header/canonical tamper及双表rollback。strict mypy（隔离follow-imports）、ruff、Black/isort、py_compile、architecture（2823 files / 0 violations）与diff-check通过。
- PostgreSQL双事务同allocation identity、request idempotency、Account claim、underlying claim、Physical root及同一消费竞争、真实0045 migrate/rollback尚未验证。更重要的是，现有Physical-v2未封存allocation exact header，claimant creation receipt未封存binding，因此账本zero-seed且pipeline/production writer/执行总闸继续禁用。

### 2026-08-13：Account allocated Physical-v3 creation-root Domain

- 新增独立`AllocatedPhysicalAccountRowObservationV3`，以组合而非修改/继承v2的方式完整封存exact `CanonicalAccountCreationAllocation`与exact `PhysicalAccountRowObservationV2`。固定owner/type/schema、`evidence_only/inactive/must_not_execute`，不改动0042、0045的既有payload或hash。
- 本批只定义creation-root分支：`identity_anchor_kind=creation_allocation`，不存在binding字段；inner Physical-v2、source-v2及raw observation的predecessor必须全空，row必须live/present/non-tombstone。Account label、underlying namespace、row user和raw account type必须逐项与allocation一致，recorded/valid时钟取allocation、Physical与Account TTL的严格交集。
- identity/content hash封存完整nested allocation与Physical-v2 canonical payload，非格式正确的header替代；PIT helper在recorded前/有效期后返回None且无fallback。root可先于durable Binding-v2产生，因此解除“Physical要封存allocation，Binding又在Physical之后产生”的循环。

验证与剩余边界：

- pure Domain unit `28 passed`；strict mypy、ruff、Black/isort、architecture（2824 files / 0 violations）与diff-check通过。
- 本批不定义update/delete successor，因为它们必须先依赖尚未实现的durable `CanonicalAccountCreationBindingV2`；也尚无Application/codec/ledger/provider。旧Physical-v2/claimant receipt-v2/staff Evidence-v2仅作历史或nested技术证据，不做authoritative fallback；pipeline、production writer与执行总闸保持禁用。

### 2026-08-13：Account durable canonical creation Binding-v2 Domain

- 新增独立`CanonicalAccountCreationBindingV2`，完整持有并重验exact allocation v1与exact allocated Physical-v3 creation root，不复用0045短TTL Binding-v1。Account/underlying双claim、root v3 identity/content、inner Physical-v2、source-v2及raw observation content hashes、binder service及签发时钟全部进入canonical hash。
- Binding-v2只要求在`recorded_at`时allocation和root v3已记录且未过期；提交后不发布`valid_until/current`能力，Account ID↔underlying row的耐久一一映射不因上游短TTL而失效或允许复用。决策当前性仍由当前Physical-v3与后续owner Evidence-v3判定。
- root allocation、Account label、underlying ID、row user/type、v3/v2/source/raw hash及双claim任一替换都fail closed。固定`identity_binding_evidence_only/inactive/bound_pending_owner_approval/unknown`、`activation_available=false`、`must_not_execute=true`，不构成owner approval或execution authority。

验证与剩余边界：

- pure Domain unit `10 passed`；strict mypy、ruff、Black/isort、architecture（2825 files / 0 violations）与diff-check通过。
- 本批仅Domain，无Application/codec/model/repository/migration/provider；Physical-v3 update/delete successor尚未实现。旧Binding-v1仅保留为创建时兼容/审计合同，不得用作durable update/delete anchor或自动升级旧receipt/Evidence-v2；pipeline/writer/执行总闸保持禁用。

### 2026-08-13：Account durable canonical creation Binding-v2 Application

- 新增ID/hash-only binding用例：命令只携带binding、allocation与allocated Physical-v3 root的ID/version/expected hash，不接受Account/underlying claim、binder、clock、payload或权限。Account exact-current-unconsumed allocation与Physical-v3 exact-final root均由owner provider读取。
- 用例以单一server cutoff在原子边界前后双读两个upstream，要求allocation、root、Account/underlying双claim以及v3/v2/source/raw全部hash逐项一致；server service binder与repository authoritative clock构造candidate，identity first-winner和allocation/Account/underlying/root四锚共同闭合幂等与冲突。
- exact reader只按`recorded_at <= as_of`发布永久identity-binding evidence的历史可知性，不用已过期allocation/root回退，也不把`inactive/bound_pending_owner_approval`解释为current owner或execution authority。旧0045 Binding-v1不进入本Protocol，也没有v1 fallback。

验证与未完成：

- Domain+Application纯测试`29 passed`；ruff、Black/isort、strict mypy、architecture（2826 files / 0 violations）与diff-check通过。
- 本批仅Application Protocol与pure fakes；durable Binding-v2独立codec/ledger/provider、跨0045 Binding-v1与Binding-v2的一次性allocation消费约束、Physical-v3 Application/账本、claimant receipt-v3、staff Evidence-v3及全writer同alias原子cutover仍缺。pipeline、production writer与执行总闸保持禁用。

### 2026-08-14：Account allocated Physical-v3 creation-root Application

- 新增ID/hash-only creation-root capture：命令只携带v3 observation、allocation与Physical-v2的ID/version/expected hash，不接受Account/underlying identity、row facts、TTL、clock、recorder或nested payload。
- 首次append以单一server cutoff双读exact-current-unconsumed allocation与exact-final Physical-v2 root，并在repository UOW内复核identity winner与完整allocation/Account/underlying/Physical root anchors；独立fixed automated `allocated_physical_creation_projector` recorder避免把技术投影冒充canonical binder。
- winner replay先校验命令全部selectors、projector和logical head，不再要求allocation仍未消费或upstream仍live；因此同一create事务后续Binding-v2消费allocation后，Physical-v3幂等重试仍能返回原winner。exact PIT与closed-current严格要求exact hash/head，过期或替换不回退v2或旧root。

验证与未完成：

- Physical-v3 Domain/Application、Binding-v2 Domain/Application组合纯测试`61 passed`；ruff、Black/isort、strict mypy、architecture（2827 files / 0 violations）与diff-check通过。
- 本批仅Application Protocol与pure fakes；0046 Physical-v3 root ledger、0047跨Binding-v1/v2统一consumption claim、durable Binding-v2 ledger/provider、Physical-v3 update/delete successor、receipt/Evidence-v3与全writer同alias原子cutover仍缺。pipeline与执行总闸保持禁用。

### 2026-08-14：Account durable canonical creation Binding-v2 strict codec

- 新增独立Binding-v2 strict codec，完整嵌套allocation、allocated Physical-v3 root及其Physical-v2/source/raw canonical payload与service binder；不把格式正确的ID/hash投影当作上游对象，也不复用0045 Binding-v1 codec/schema。
- 顶层与每层nested payload均执行exact keys/types、UTC `Z`、bool伪int拒绝、Domain重建和encode→decode→encode canonical相等；任一allocation/root/physical/source/raw/claim/recorder/clock/fixed authority/hash替换都fail closed。

验证与未完成：

- codec unit `48 passed`；ruff、Black/isort、strict mypy与diff-check通过。
- 本批没有model/repository/migration/provider；0047统一consumption claim与Binding-v2 ledger、跨v1/v2并发、真实migrate/rollback仍缺，codec不得被视为可签发或可消费allocation的账本。

### 2026-08-14：Account allocated Physical-v3 creation-root 0046 ledger

- 新增独立0046 schema-only单表账本，完整封存nested allocation + Physical-v2/source/raw canonical payload与独立`allocated_physical_creation_projector` recorder；identity、allocation、Account、underlying与Physical root五类锚分别由DB unique和domain-separated claim hash防重。
- model使用private non-nestable UOW、exact insert claim及instance/QuerySet/bulk/raw mutation/delete阻断；repository在winner、head、exact/PIT与IntegrityError恢复前先restore全表，逐列复核canonical/header/allocation/physical/projector/fixed/clock/record/ledger seals。冗余Account或selector header被SQL篡改时不能隐藏坏root。
- root-only CAS拒绝predecessor；logical head在过期后仍保持最终root，不回退或生成第二root。`persisted_at == recorded_at`由DB check与restore共同封印；0046仅CreateModel且zero-seed，不改0042/0045 canonical bytes或回填mutable row。

验证与未完成：

- Django 5.2 isolated component `4 passed`，覆盖roundtrip/first-winner/PIT、完整五锚head、私有UOW/写删改旁路、closed-world header tamper以及migration字段/constraint/index同构与zero-seed；ruff、Black/isort、py_compile、隔离strict mypy、architecture（2831 files / 0 violations）及diff-check通过。
- PostgreSQL五锚并发、真实0046 migrate/rollback与全项目回归尚未验证。更关键的0047统一consumption claim + Binding-v2 ledger仍缺，因此0046只提供创建根证据，不消费allocation，不允许pipeline/production writer或执行总闸开启。

### 2026-08-14：Account canonical creation unified Consumption Claim Domain

- 新增Account-owned统一消费合同，服务Binding-v1与Binding-v2共享allocation消费与Account/underlying/Physical排他。Claim完整持有并重验exact allocation与exact consumer，但canonical payload只嵌完整allocation及非递归consumer ref，避免claim↔consumer hash循环。
- 分支矩阵固定：v1 consumer必须是exact 0045 Binding-v1且`physical_v3_root_content_hash=None`；v2 consumer必须是exact durable Binding-v2且root hash精确等于其allocated Physical-v3 creation root。两分支均重算Physical-v2 hash、Account/underlying raw keys与candidate-independent claim hashes。
- claim与consumer强制使用同一`recorded_at`，allocation在该时点必须有效；固定`evidence_only/inactive/must_not_execute`，只证明一次性消费与永久mapping anchors，不构成owner approval、current physical状态或execution authority。

验证与未完成：

- pure Domain unit `30 passed`；strict mypy、ruff、Black/isort、architecture（2832 files / 0 violations）与diff-check通过。
- 本批仅Domain；strict codec、0047 expand schema、v1 dual-write/backfill审计、Binding-v2 repository与0048 NOT NULL contract仍缺。生产是否zero-seed尚未逐alias验证，不能据本地fresh migration假设空表或直接启用v2 writer。

### 2026-08-14：Account canonical creation unified Consumption Claim strict codec

- 新增strict codec，完整decode nested allocation；consumer因claim canonical只持非递归ref，由repository先按ref恢复完整Binding-v1/v2，再以`decode(payload, consumer=...)`注入并逐项核对owner/type/schema/id/version/identity/content hash。
- 顶层、allocation与consumer ref均使用exact keys/types、UTC `Z`、固定false/true语义与encode→decode→encode canonical相等；unknown/missing、bool伪int、generation/consumer替换、Account/underlying/Physical/root/clock/hash篡改均fail closed。

验证与未完成：

- codec unit `32 passed`；strict mypy、ruff、Black/isort与diff-check通过。
- 本批无model/repository/migration；0047 expand、closed-world consumer恢复、v1 dual-write/backfill与0048 contract仍缺，不构成跨版本数据库排他证明。

### 2026-08-14：Account canonical creation consumption 0047 expand schema

- 新增0047纯expand migration：创建统一Consumption Claim与durable Binding-v2两张append-only表，并只给旧Binding-v1添加nullable `consumption_claim` OneToOne PROTECT FK。migration仅`CreateModel + CreateModel + AddField`，无RunPython/RunSQL、无回填且不启用v2 writer。
- Claim表以allocation OneToOne、Account raw key、underlying raw key、Physical-v2 hash及v2条件Physical-v3 root hash提供跨generation原始锚唯一性；branch DB check固定v1无root/v2有root，fixed authority与`persisted_at == recorded_at`下沉数据库。完整claim authority字段与allocation/consumer/fixed/record/ledger seals预留给closed-world repository。
- Binding-v2表以Claim OneToOne、allocation FK、0046 creation-root OneToOne闭合，完整封存v3/v2/source/raw hashes、Account/underlying claims、service binder与fixed/persisted clocks；model及两表均使用private UOW/exact insert claim和全mutation/delete guard。

验证与未完成：

- Django 5.2 isolated new+0045 component `6 passed`，覆盖schema state与migration字段/constraint同构、zero-seed、private guard、cross-anchor unique、branch/clock DB check及旧v1 nullable expand；ruff、Black/isort、py_compile、architecture（2834 files / 0 violations）与diff-check通过。
- nullable expand不是生产排他证明：v1 repository尚未dual-write统一Claim，既有0045数据尚未逐alias盘点或backfill，Binding-v2 repository尚未实现，0048 NOT NULL contract与PostgreSQL v1/v2交叉竞争仍缺。旧v1和新v2 writer都保持禁用，pipeline/执行总闸不变。

### 2026-08-14：Account canonical creation unified Claim Application workflows

- Binding-v1保持既有ID/hash-only命令和Domain/codec bytes不变；两代Consumption Claim身份都由exact allocation identity与consumer generation确定性派生，不接受caller任选claim token。两条路径都先读取并验证Binding+Claim first-winner，再访问current-unconsumed上游，确保allocation已消费或上游已过期后仍可精确重放原winner。
- 无winner时先按server cutoff读取上游，进入repository atomic后取得authoritative `recorded_at`、按该时点重查winner并二读上游；Binding与Claim以完全相同的`recorded_at`构建。Application Protocol移除单Binding append语义，改为跨generation claim-anchor读取及Binding+Claim原子pair append，返回值仍保持原Binding对象。
- v1 claim identity resolver、v1/v2 Persisted pair及replay校验均封存allocation、consumer、Account/underlying raw key、Physical-v2和v2 creation-root矩阵；任一claim selector、binder、source或append pair替换均fail closed。

验证与未完成：

- Binding-v1、Binding-v2、Consumption Domain/codec聚合pure tests `85 passed`；Ruff、Black/isort、standalone strict mypy与architecture（2834 files / 0 violations）通过。
- 本批仍仅Application Protocol+pure fakes；0045旧repository尚未实现Claim dual-write，0047 Binding-v2/Claim closed-world repository、逐alias inventory/backfill、0048 NOT NULL contract和PostgreSQL v1/v2交叉竞争仍缺。production composition/writer、pipeline与执行总闸继续禁用。

### 2026-08-14：Account canonical creation Binding-v2 unified Claim repository

- 新增0047 production repository，所有winner/exact/anchor/append路径先closed-world恢复allocation、0046 creation root、Binding-v1、Binding-v2与Consumption Claim，再以完整consumer重建非递归claim canonical payload；任何非目标行、FK、canonical/header/seal或claim-link篡改都会使全次读取fail closed。
- winner返回强类型Binding-v2+Claim pair；claim anchor按identity、allocation、consumer、Account、underlying、Physical-v2及Physical-v3任一独立锚判占用。0048前的legacy Binding-v1 null-claim FK被显式视为已占用，绝不因尚未backfill而重新消费。
- append要求private同alias transaction，先锁全allocation父行以闭合空claim并发窗口，核对exact allocation/root与所有raw anchors后按Claim→Binding-v2顺序双写；IntegrityError只允许完整pair exact replay，其余均稳定Conflict且双表回滚。

验证与未完成：

- Django 5.2 isolated repository component `8 passed`，与0045/0047 schema/repository组合 `17 passed`；覆盖pair roundtrip/PIT、永久exact、9类anchor、legacy占用、非目标tamper、private/nested UOW、selector substitution、claim-link tamper与事务rollback。Ruff、Black/isort、py_compile及isolated strict mypy通过。
- 旧Binding-v1 repository仍未dual-write统一Claim；逐alias inventory/backfill、0048 NOT NULL contract与PostgreSQL v1/v2双事务竞争尚未完成。因此本repository仍为dormant production implementation，不注册composition、不启用writer/pipeline/执行总闸。

### 2026-08-14：Account Binding-v1 unified Claim dual-write repository

- 旧0045 repository现与0047统一Claim表共享同一alias、同一outer transaction和双private UOW；allocation、request、binding及claim读取全部先closed-world恢复allocation、Binding-v1/v2、0046 root与Claims，legacy null-FK可作为历史exact evidence读取，但winner replay明确Corruption且绝不伪造Claim。
- current-unconsumed allocation同时检查所有unified Claims与未backfill legacy Binding；任一generation已消费均返回None。新Binding-v1写入口只接受Binding+Claim pair，旧null-claim append seam稳定拒绝；append先锁共同allocation父行，再核对跨generation anchors，按Claim→Binding-v1顺序双写并设置nullable FK，IntegrityError仅允许完整pair exact replay。
- 0047兼容期保留legacy null-FK占用检测，供inventory/backfill前fail closed；新写必须非null。historical exact Binding读仍按recorded knowledge保留，不因上游TTL过期回退或消失。

验证与未完成：

- Django 5.2 isolated v1 repository `6 passed`，与Binding-v2/0047组合 `17 passed`；覆盖allocation回归、pair append/replay/PIT、8类anchor、current-unconsumed、legacy占用、nested tamper、三表rollback及header/canonical fail-closed。Ruff、Black/isort、py_compile、isolated strict mypy与architecture（2835 files / 0 violations）通过。

### 2026-08-14：Account canonical creation consumption 逐 alias 盘点与回填预览

- 新增显式database alias的只读盘点服务；PostgreSQL使用`REPEATABLE READ READ ONLY`，SQLite明确标记只具本地降级证据。盘点要求0045/0046/0047精确migration名称，并逐表核验当前model全部列、nullability、命名Unique/Check约束和FK后才进行closed-world canonical restore。
- 报告冻结五账本count/PK区间/authoritative clock区间、v1 null/non-null claim链接、跨generation anchor碰撞与稳定SHA-256；未知alias、伪migration名、缺列/约束/FK或任一非目标坏行均fail closed。
- 新增Binding-v1 deterministic backfill预览：在单一一致性快照中重建候选Claim并检测全部anchor冲突，不修改旧Binding bytes或任何数据库行。由于当前Claim schema只有历史`recorded_at/persisted_at`，尚未建模真实`backfilled_at`与maintenance writer-freeze，写模式稳定阻断，避免把今天插入的Claim洗成历史时点已存在。
- Django 5.2 isolated component `10 passed`；Ruff、Black/isort与standalone strict mypy通过。没有访问任何生产alias，未取得生产row count、zero-seed、writer freeze或0048 readiness证据；0048、回填写入和v1/v2 PostgreSQL交叉竞争继续阻断。

### 2026-08-14：Account canonical creation consumption 运维命令边界

- 新增inventory与Binding-v1 backfill两个management command；都要求显式database alias并输出稳定单行JSON，batch-size目前明确标记为reserved/all-or-nothing，不伪装已实施分批事务。
- Inventory可发布只读报告，但`--require-0048-ready`即使本地结构和计数合格也会因缺writer-freeze稳定失败。Backfill默认仅dry-run；`--write`先校验lowercase inventory SHA与PostgreSQL backend，随后仍无条件以`writer_freeze_proof_unavailable`阻断，写服务保持不可达。
- 纯命令测试`14 passed`，Ruff、Black/isort、standalone strict mypy与architecture（2839 files / 0 violations）通过。命令不接Celery/Task Monitor，不提供0048、生产回填或writer cutover授权。

### 2026-08-14：Account canonical creation consumption writer-freeze 前置

- 新增database-scoped transaction advisory lock；Binding-v1与Binding-v2 repository的每个atomic writer UOW在PostgreSQL事务内取得同一signed-bigint shared lock，maintenance未来使用同key exclusive lock，避免只靠“空claim预查”宣称跨代排他。
- Exclusive maintenance默认只允许PostgreSQL；SQLite必须显式开启test degradation，且不构成生产或并发证明。当前backfill仍在进入任何写事务前稳定阻断，因此尚未取得exclusive lock，也不存在shared→exclusive升级死锁路径。
- 两repository与lock组件组合`18 passed`；Ruff、Black/isort、standalone strict mypy通过。尚未做真实PostgreSQL两连接阻塞/竞争测试，writer-freeze只完成代码前置，不足以解除backfill/0048阻断。

### 2026-08-14：Account canonical creation consumption knowledge clock expand

- 保留Claim Domain `recorded_at == consumer.recorded_at`及全部canonical payload/hash/seals不变；新增0048纯AddField migration：nullable、indexed `knowledge_at`只表达系统真实获得Claim的时点，无RunPython/RunSQL、无seed、无NOT NULL/contract。
- v1/v2 live双写令`knowledge_at == recorded_at`；restore要求aware且不早于业务recorded clock。winner、claim anchor与allocation current-unconsumed的PIT visibility改按knowledge clock，延迟知识在`as_of < knowledge_at`时不可见，NULL/naive/clock rollback会使closed world fail closed而不是回退旧状态。
- Inventory与dry-run preflight现在要求0048精确migration名；运维CLI的readiness语义从特定“0048 contract”改为generic future contract，保留旧flag仅作兼容alias。组件`29 passed`、命令`14 passed`、architecture 2840/0，Ruff/Black/isort/strict mypy通过。
- 既有Claim迁移后保持NULL且不可发布；真实knowledge backfill、exclusive maintenance、NOT NULL/clock Check contract与PG迁移往返仍未完成。完整`makemigrations --check`被当前隔离环境缺Celery阻断，migration/model state已由Django5.2 component精确比对。

### 2026-08-14：Account canonical creation consumption knowledge backfill engine

- Backfill service现区分三类过渡态：已链接Claim但knowledge NULL、legacy Binding-v1 FK NULL且已有exact Claim、以及完全无Claim。专用transitional closed-world只允许knowledge恰为NULL，其余canonical bytes、seals、FK与跨代anchors仍完整恢复；常规reader保持NULL即corruption。
- 写路径不经shared writer UOW升级，而是在唯一outer transaction开头直接取得同key exclusive advisory lock；随后在锁内复核0047/0048、取得PostgreSQL `clock_timestamp()`，再以完整PK/identity/content/allocation/consumer anchors做NULL CAS。新Claim保留历史Domain recorded/persisted bytes，只把真实运行时钟写入knowledge_at；Binding-v1链接CAS还用EXISTS重验Claim generation与consumer hashes，任一rowcount异常整批回滚。
- Service默认仍无写授权；调用方必须注入exact write-authorization，production command继续稳定阻断。SQLite写只允许显式component degradation。组合组件`34 passed`，Ruff/Black/isort、standalone strict mypy与architecture 2840/0通过。
- 尚无production alias inventory SHA授权实现、真实PG双连接shared/exclusive阻塞测试或实际回填签字；因此不生成NOT NULL/check contract migration，不把engine存在解释为生产可运行。
- 代码现在具备dormant双代写路径，但生产各alias的0045存量尚未盘点或backfill，0048 contract与PostgreSQL v1/v2交叉竞争仍缺；因此composition/writer/pipeline继续禁用，不能宣称生产排他已闭合。

### 2026-08-14：Account owner-assignment creation claimant receipt v3 0049账本

- 新增独立0049 append-only Receipt-v3账本，完整封存durable Binding-v2、allocation、allocated Physical-v3、Physical-v2/source/raw、Account/underlying claims、claimant/issuer、authority/header/chain/record/ledger seals与authoritative persisted clock。Binding-v2使用`PROTECT`外键，successor使用self `OneToOne(PROTECT)`；root按`receipt_id`唯一，predecessor以exact content hash相邻CAS。
- 所有read/append先恢复整个Receipt-v3表并验证每个receipt chain，再通过Consumption repository恢复完整allocation/root/v1/v2/Claim closed world；Binding-v2只有在Receipt记录时点已经由非NULL且不晚于该时点的Claim `knowledge_at`获知才可签发，查询时点不能向后洗白该前置知识。
- 0049仅包含schema操作且zero-seed，无RunPython/RunSQL或旧v1/v2/mutable row回填。Django5.2 isolated component `7 passed`，覆盖roundtrip/PIT、private append、NULL/late knowledge、无关header篡改、IntegrityError savepoint、过期successor最终头不回退及migration边界；Ruff、Black/isort、py_compile、repository strict mypy与architecture 2846/0通过。
- 未完成真实PostgreSQL双事务竞争、真实0049 migrate/rollback、owner provider/composition与production actor入口；账本和所有上游账本仍zero-seed，不能视为authoritative identity已上线。

### 2026-08-14：Account owner-assignment staff approval Evidence v3 Domain

- 新增creation-only subject与staff approval Evidence-v3。Subject重新验证exact Receipt-v3、Binding-v2与allocated Physical-v3，并把receipt/binding/creation-root identity/content、Account/underlying claim及Physical/source/raw content共11项显式seal写入canonical hash；任一重复header替换均fail closed。
- 最终Evidence只允许独立human staff approver，按actor ID与user ID双维禁止自批；approved authoritative owner必须等于Receipt-v3 claimant。Account字符串identity与underlying整数identity使用不同domain且candidate-independent的root hashes，Evidence固定`evidence_only + inactive + must_not_execute`。
- 本合同root-only且不接manual reclaim/migration/successor；historical exact在recorded后永久保留，current才要求subject/receipt/root TTL。Receipt-v3与Evidence-v3 pure组合`33 passed`，Ruff、strict mypy与architecture 2846/0通过。
- 仍缺Evidence-v3 Application/codec/0050账本、authoritative current mapping facade、独立staff composition与production入口；不得把Domain对象或Receipt-v3 claimant声明直接提升为账户owner authority。

### 2026-08-14：Account owner-assignment staff approval Evidence v3 Application

- 新增ID/hash-only Subject-v3注册与staff审批用例。Subject注册先重放历史first winner；新注册以单一server cutoff双读exact-current Receipt-v3与allocated Physical-v3，并封存exact durable Binding-v2及11项上游seals。审批者只来自当前authenticated human-staff provider，caller不能提交owner、approver、payload、permission或时钟。
- 审批在同一UOW中双读subject、Receipt-v3、Physical-v3和approver；按actor ID与user ID双维禁止自批，并要求Account/underlying双mapping root同时为空后原子append root-only Evidence。winner-first重放绑定原approver，历史exact在recorded后永久读，closed-current才重验双root及Receipt/Physical当前状态；无v2 fallback或Application→Infrastructure依赖。
- Application pure `7 passed`，Receipt-v3/Evidence-v3 Domain+Application组合`48 passed`；历史winner不依赖当前approver，且新写在authoritative `recorded_at`再次复核upstream、approver与双heads；Ruff、Black/isort、strict mypy及architecture 2848/0通过。仍缺0050双表repository、production provider/composition、PG双root竞争与真实staff入口。

### 2026-08-14：Account owner-assignment staff approval Evidence v3 strict codec

- 新增公开Subject-v3与Evidence-v3严格codec。Subject decoder完整重建Receipt-v3、Binding-v2与allocated Physical-v3；Evidence decoder再重建完整Subject和approver，不把上游对象压缩为外部header。两者均执行exact keys/types、UTC-Z、fixed booleans、Domain hash/seal重算与encode→decode→encode canonical equality。
- codec pure `24 passed`，与Application组合`30 passed`；Ruff、Black/isort与strict mypy通过。无ORM/model/migration；0050账本必须使用公开Subject decoder，并逐行闭合Receipt→Binding→Physical FK与Consumption Claim knowledge。

### 2026-08-14：Account owner-assignment staff approval Evidence v3 0050双表账本

- 新增独立Subject-v3与Evidence-v3 append-only双表。Subject以`PROTECT` FK分别绑定exact Receipt-v3、Binding-v2和allocated Physical-v3，持久化11项显式upstream seals、账户/underlying selectors、claimant与receipt/root clocks；Evidence以OneToOne Subject FK封存独立staff approver、authoritative owner、双mapping root和approval clocks，不提供predecessor/successor字段。
- Repository每次read/append先完整恢复全部Subject/Evidence canonical rows，再逐Subject调用0049 Receipt closed-world与Consumption Claim knowledge重验，并核对Receipt→Binding、Subject→Binding/root、Binding→root的每一条FK和nested Domain对象。Subject/evidence first-winner、Receipt/Subject单消费、Account/underlying各自unique root、private UOW、inner savepoint exact replay及全部mutation guards闭合；上游taxonomy统一翻译为Account corruption。
- 0050直接依赖0049且仅schema operations，zero-seed、无RunPython/RunSQL/旧Evidence回填。Django5.2 isolated本批component `4 passed`，与0049组合`11 passed`；覆盖permanent exact、exact replay、private guard、future cutoff、无关header tamper、NULL Claim knowledge与migration边界。Ruff、Black/isort、py_compile、repository strict mypy、Django check及architecture 2850/0通过。
- 尚未做真实0050 migrate/rollback、PostgreSQL双连接同Subject/双mapping/Receipt-successor竞争、production owner/Physical providers、staff composition与authoritative mapping facade；zero-seed且执行总闸不变。

### 2026-08-14：Account authoritative mapping v3 read-only facade

- 新增纯Application只读facade，caller只提交underlying namespace/id与aware PIT。facade先读取0050最终underlying Evidence-v3 root，再仅以evidence ID/version/content hash调用current reader，要求服务端current结果与head exact equality后才投影canonical Account identity、underlying row与owner user。
- 输出固定`identity_mapping_only + inactive + execution_allowed=false`；缺失、legacy-only无v3 head、expired、upstream superseded、双root不一致或任何非authoritative状态均返回None，不回退Evidence-v2或mutable Account row。pure `6 passed`，Ruff、Black/isort、strict mypy及architecture 2851/0通过。
- facade尚未组装production provider；最小诚实composition可完全使用Account 0046/0047/0049/0050 repositories与Application exact/current usecases，不能反向import SimulatedTrading造成app cycle。现Receipt/Physical current command仍携完整对象，composition需exact-first适配，未来再独立收窄为ID/hash-only。

### 2026-08-14：Account Evidence-v3 Account-only只读composition

- 新增Account app-root只读组装点，统一以同一database alias组装0047/0048 durable Binding-v2、0046 allocated Physical-v3、0049 Receipt-v3与0050 Evidence-v3 repositories。Physical-v3与Receipt-v3均先用ID/version/hash读取exact Domain对象，再交给现有full-object current use case复核最终逻辑头；不存在scalar签名冒充或v1 fallback。
- Binding/Physical专属异常在只读边界翻译为公共Account owner-assignment taxonomy：Unavailable保持不可用，Conflict/Corruption统一fail closed为Corruption。最终只公开current Evidence-v3 reader与authoritative mapping v3 facade，不公开atomic、append、actor或approval能力，也不import SimulatedTrading，避免形成反向app依赖。
- composition与mapping pure组合`18 passed`；真实Django5.2空账本组件`1 passed`，证明zero-seed 0046/0047/0049/0050图稳定返回None；Ruff、Black/isort、strict mypy与architecture 2852/0通过。
- 这只完成production可构造的只读图，不代表存在authority数据。所有相关账本仍zero-seed；真实staff认证/审批写入口、SimulatedAccount全writer同事务cutover、knowledge backfill/contract、PostgreSQL迁移与双连接竞争仍未完成，execution总闸不变。Receipt/Physical current command的full-object形状保留为后续独立API收窄债务。

### 2026-08-14：Account Physical/Receipt-v3 current ID/hash-only边界

- 将allocated Physical-v3与claimant Receipt-v3的current commands从caller提交完整Domain对象收窄为`id + version + expected_content_hash + as_of`。Application在服务端先执行exact PIT恢复并重验canonical对象，再从该对象派生logical-head、TTL、Binding与Physical selectors；caller不能再注入expected object。
- Account-only composition同步改为把scalar selector直接交给current readers；Physical provider仍保留独立exact方法供Receipt协议使用，Receipt current构造器仍保留Binding-v2 provider依赖。final terminal/expired/superseded head仍返回None且不回退旧版本。
- Application/Evidence/composition/mapping定向pure `41 passed`；0049/0050与真实composition组件链`12 passed`；Ruff、Black/isort、3 production files strict mypy及architecture 2852/0通过。
- 无schema/migration变化，也未扩大到write/approval。zero-seed、staff认证入口、knowledge backfill/contract、PostgreSQL竞争与SimulatedAccount全writer cutover仍是production authority前置，execution总闸不变。

### 2026-08-14：Account owner-assignment v3 actor authority Application合同

- 新增纯Application请求principal与exact-current Account actor authority合同。principal只携server-authenticated principal ID、user ID、authentication-context hash及有效窗；每次`get_current(as_of)`都重新调用注入的authority reader，不缓存或冻结`request.user` actor，因此Receipt/Evidence workflow的cutoff/recorded-at二读仍能发现撤权、停用、会话失效或RBAC漂移。
- claimant仅接受current authenticated+active且nonstaff/nonsuperuser authority，并固定投影`account_owner_claimant`；approver必须同时为current active staff与normalized Account admin，固定投影`account_owner_assignment_approver`。selector/hash/future-recorded替换报公共corruption，诚实的revoked/inactive/expired返回None。
- actor authority与Receipt/Evidence Application定向pure `32 passed`；Ruff、Black/isort、strict mypy及architecture 2853/0通过。Domain/Application双维防自批仍为最终两人边界。
- 本批仅Protocol/DTO/provider规则与fakes，不含Django ORM authority reader、request principal adapter、write composition或HTTP/TUI入口。mutable User/Profile row不能被现场hash冒充owner-issued exact authority；在正式Account actor source与专属审批权限适配完成前，不得接写路由或称production staff authorization已上线。

### 2026-08-14：Account owner-assignment actor authority source v3 Domain

- 新增Account-owned纯Domain actor-authority source，独立于账户owner identity。合同封存source identity、opaque principal与非敏感authentication-context exact refs/hashes、User/RBAC source refs/hashes、stable actor ID、authenticated/active/staff/superuser/canonical role facts，以及principal/source/TTL三重有效期。cookie、session key、token、CSRF或password hash均不进入字段，context hash只能引用未来owner-issued sealed authentication evidence。
- 固定`attestation_only + inactive + execution_allowed=false + must_not_execute=true`。identity/content及principal/context/user/RBAC/facts/clock/chain/fixed/record seals均domain-separated；root claim绑定actor_id。同session successor固定principal/user/context/actor并精确绑定前序hash，且要求`previous.recorded_at < successor.source_recorded_at <= issued_at <= recorded_at`，阻断后来写入的回填事实。
- terminal revoked/deactivated记录不可再接successor；新session/context不能接旧链。Domain仅提供historical knowable与单记录`is_temporally_current_at`，明确不声称logical head；repository未来必须以final head判current，terminal/expired不得回退旧授权。
- source Domain与actor Application、Receipt/Evidence定向pure `65 passed`；Ruff、Black/isort、2 production files strict mypy及architecture 2854/0通过。同步收紧Application：approver只接受owner source已封存的exact canonical`admin`，不再现场归一化角色别名。
- 本批没有Application capture、strict codec、append-only ledger、Django User/RBAC/auth-context原始provider或request adapter。现mutable User/Profile/session不能现场拼hash充当source；在这些owner链路与zero-seed ledger闭合前，staff write composition和路由保持缺失，execution不开放。

### 2026-08-14：Account actor authority source v3 Application workflow

- 新增纯Application capture/exact/current合同。写命令只携source、principal及三项上游authority artifact的ID/version/expected content hash；authentication context、User authority与RBAC authority必须由单一原子bundle provider在同一PIT返回，禁止顺序拼接三次可撕裂的mutable读取，也不接收cookie、session key、token、CSRF或password hash。
- 新写在同一repository UOW内先查first winner；无winner时以server cutoff首末双读完整bundle，再取authoritative recorded clock并做第三次bundle重验与final-head复核。same-session successor精确绑定前head hash并调用Domain相邻validator；terminal head不可续接，新session必须新root。winner重放不再读取当前会话、User/RBAC或recorder，撤权/过期后仍可永久幂等返回历史winner。
- exact reader仅按recorded knowledge提供历史版本；current reader先scalar exact恢复，再同时要求source temporal window、owner bundle仍exact-current且事实未漂移、repository final head exact equality。terminal、expired、superseded或上游不可用均返回None，绝不回退旧授权。terminal source保留真实`is_authenticated`事实，授权阻断由`authority_state`完成，避免把RBAC/staff撤权伪造成会话登出。
- Domain+Application pure `40 passed`；Ruff、Black/isort、2 production files strict mypy及architecture 2855/0通过。本批仍只有Protocol/DTO与pure fakes：无strict codec、append-only ledger/migration、真实atomic authority bundle provider、Django request adapter、staff write composition或HTTP/TUI路由；mutable User/Profile/session仍不得现场hash冒充owner artifact，execution继续关闭。

### 2026-08-14：Account actor authority source v3 strict codec

- 新增独立strict codec，按Domain dataclass完整字段集编码并重建principal/auth-context、User/RBAC refs、authority facts、全部aware clocks、root/predecessor、fixed semantics、identity/content及十类domain-separated seals。decoder要求exact mapping/key集合、exact scalar类型、UTC-Z microseconds，并在恢复Domain后执行encode-equality，未知/缺失字段、bool伪int、非规范时钟及任一hash/seal篡改均fail closed。
- codec定向pure `28 passed`，Domain/Application/codec组合`68 passed`；Ruff、Black/isort及strict mypy通过。本批不含model/repository/migration，也不改变zero-seed、authority bundle provider缺失和write/execution关闭状态；codec只能验证已封存payload，不能把mutable session/User/Profile现场hash升级为owner truth。

### 2026-08-14：Account actor authority source v3 0051 schema与append guards

- 新增0051 schema-only迁移，依赖0050且严格只有两个`CreateModel`、无RunPython/RunSQL/seed。独立root-lock表以`source_id + root_claim_hash`形成candidate-independent锁锚；ledger以PROTECT FK绑定该锚和self OneToOne predecessor，完整持久化Domain字段/canonical payload、service recorder、recorder binding/ledger seals及persisted clock。
- 两表都使用private non-nestable UOW/exact insert claim，并阻断save/update/bulk/raw/delete绕写；DB约束固定inactive/attestation-only/nonexecution与automated recorder，校验authority state闭集、current必须authenticated+active、root/successor XOR、clock上下界和`persisted_at=recorded_at`。`source_id+version`、root/predecessor/content/seals保持唯一，chain index按source+recorded clock建立。
- isolated Django5.2 model component `3 passed`；Ruff、Black/isort、pycompile、3 production files增量mypy 0 regressions及architecture 2857/0通过。本批尚无repository/closed-world restore/append CAS/IntegrityError replay，也没有PostgreSQL空root与same-predecessor双连接竞争证明；因此0051仍是zero-seed schema/guard，不是可用authority账本或production授权。

### 2026-08-14：Account actor authority source v3 0051 repository

- 新增Django repository，精确实现Application atomic/clock/first-winner/exact PIT/final-head/append协议。首次append在private UOW内以exact claim创建candidate-independent source/root anchor，再`select_for_update`该anchor；append整体位于inner savepoint，因CAS/校验失败即使被调用方在外层UOW捕获，也不会提交孤儿anchor。same-source successor以final predecessor content hash做CAS，IntegrityError只接受完整Persisted record exact replay。
- 每次selector先恢复整张ledger和全部anchors，再应用recorded-at PIT。restore以strict codec重建Domain，逐列核canonical payload、service recorder、content-bound recorder seal、ledger seal与persisted clock；逐source验证single root、anchor root claim、PROTECT predecessor、相邻Domain successor、无fork/cycle/orphan/disconnect。`get_current_head`始终返回最终knowable head，即使terminal或expired，也不回退旧current。
- isolated Django5.2 model+repository component `7 passed`，覆盖zero-seed/root replay/PIT/exact、terminal successor/expiry no-fallback、private UOW/CAS及caller-caught rollback、无关selector前full-table tamper；Ruff、Black/isort、pycompile、focused strict mypy及architecture 2858/0通过。真实PostgreSQL空root/same-predecessor双连接race、真实owner auth/User/RBAC ledgers与atomic bundle provider仍未完成，因此0051继续zero-seed且staff/write/execution入口关闭。

### 2026-08-14：Account actor authority raw-source v3 Domain primitives

- 在Account Domain内新增仅供三种owner raw authority artifacts复用的frozen/slots primitives：exact source ID/version、`observed_at <= recorded_at < valid_until` aware clock、root/predecessor XOR chain，以及canonical UTC-Z、domain-separated hash和固定inactive/attestation-only/nonexecution header validator。业务语义未下沉`shared/`，也没有用单一kind+nullable矩阵混合auth-context/User/RBAC三种不同撤权规则。
- pure `10 passed`；Ruff、Black/isort、strict mypy及architecture 2859/0通过。该模块不是raw source artifact、ledger、provider或request adapter；下一步仍须分别定义auth-context、User authority与RBAC authority concrete Domains，之后才可建立各自zero-seed ledgers与atomic aggregate provider。mutable session/User/Profile现场hash继续禁止。

### 2026-08-14：Account auth-context/User/RBAC raw authority source v3 Domains

- 新增三个独立Account-owned concrete artifacts并复用raw-source primitives，不使用nullable discriminator。Authentication Context封存opaque source/session identity、principal/user/stable actor、真实authenticated/revoked事实与authenticated clock，字段集合显式排除cookie/session key/token/CSRF/password；User Authority封存active/staff/superuser与current/deactivated；RBAC Authority只接受现Account schema的7个canonical roles与current/revoked，不import或现场调用Application role normalization。
- 三种artifact均固定inactive/attestation-only/nonexecution，identity/root hash显式包含owner/artifact/schema并按各自domain分离；完整principal/user/RBAC/facts/clock/chain/fixed/record/content seals和canonical nested payload。相邻successor精确绑定前序content、固定各自root identity并推进version/observation/record clock；auth-context还冻结authenticated_at。revoked/deactivated为terminal，historical knowable永久而temporal-current明确不代表ledger head。
- primitives+三Domain pure `85 passed`；Ruff、Black/isort、3 production files strict mypy及architecture 2862/0通过。本批仍无strict codecs、append-only raw ledgers、Django immutable source writers、atomic bundle provider或request adapter；不能从mutable session/User/Profile即席构造这些Domain对象，也未启用staff composition、route或execution。

### 2026-08-14：Account auth-context/User/RBAC raw authority source v3 strict codecs

- 为三种concrete raw authority artifacts分别新增strict codec；每个codec完整编码/恢复nested identity、clock、chain及所有专属facts、fixed header、identity/content与domain seals。decoder要求top/nested exact mapping与key集合、exact scalar类型（bool/int不互认）、canonical UTC-Z microseconds，恢复后调用各自Domain重验并要求encode equality；RBAC role不做fallback/normalize。
- 未知/缺失/非字符串key、非mapping、非规范时钟、root/predecessor XOR、fixed semantics、role/state及任一hash/seal篡改均fail closed。codec测试合计`100 passed`，三Domain+codec组合`175 passed`；Ruff、Black/isort、3 production files strict mypy及architecture 2865/0通过。
- 本批仍无raw models/repositories/migrations或immutable Django writers。strict codec只验证已有owner payload，不能把live session/User/Profile读取转换为可审计的observed/recorded/valid evidence；atomic aggregate provider、request adapter、staff composition与execution继续关闭。

### 2026-08-14：Account actor authority raw-source v3 Application primitives

- 新增三种raw authority source共用的纯Application边界：统一Unavailable/Conflict/Corruption taxonomy、只含`source_id/source_version/expected_content_hash/as_of`的exact/current标量selector，以及固定`service/account_actor_authority_raw_recorder/automated`语义的frozen recorder。公共模块不引用任一具体Domain artifact，也不包含provider、capture command、repository或ORM。
- 定向pure `22 passed`；Ruff、Black/isort、strict mypy及AST Application边界检查通过。该小批只冻结后续三个typed read/repository合同的共同语言；没有采集mutable session/User/Profile、没有生成source version/clock/facts，也没有raw ledger、atomic bundle、request adapter或staff write入口，execution继续关闭。

### 2026-08-14：Account auth-context/User/RBAC raw authority v3 Application read contracts

- 为三个concrete raw artifacts分别新增纯Application Persisted wrapper、typed Repository Protocol与scalar GetExact/GetCurrent readers。Protocol冻结private atomic/server clock、identity first-winner、source logical final head、exact hash PIT、predecessor CAS append形状，但本批不提供capture command、provider或实现；Persisted wrapper将exact Domain source与固定自动service recorder一起重验。
- GetExact仅在repository返回的版本已由`recorded_at`可知且ID/version/hash完全匹配时永久返回；repository泄漏未来行、类型或selector替换均为Corruption。GetCurrent在exact基础上要求temporal current及最终Persisted head完全相等；source、同version hash或recorder替换为Corruption，revoked/deactivated、expired或superseded均None且不回退旧head。
- 三合同定向pure `29 passed`，primitives+三个Domains/codecs/Application组合`236 passed`；Ruff、Black/isort、3 production files strict mypy及architecture 2869/0通过。仍无raw Django models/repositories/migration、mutable source capture、version allocator或atomic bundle；append仅为Dormant Protocol surface，staff/request/execution均未开放。

### 2026-08-14：Account auth-context/User/RBAC raw authority v3 0052 schema与guards

- 新增0052 schema-only迁移并依赖0051；建立三套彼此独立的candidate-independent source/root anchor与concrete ledger，共六个`CreateModel`，随后仅追加同批FK、索引与约束操作，无RunPython/RunSQL/seed/backfill。没有使用kind+nullable discriminator，也没有FK到mutable Session/User/Profile；fresh schema六表均为zero-seed。
- 三种ledger分别完整投影strict Domain的identity/clock/chain、专属facts与seal，并共同封存fixed header、canonical payload、自动service recorder、content-bound recorder seal、ledger seal及persisted clock。anchor PROTECT、self predecessor OneToOne PROTECT；数据库约束固定artifact/state/clock/root-XOR、positive user、RBAC 7-role allowlist、source identity与root/predecessor uniqueness。私有非嵌套UOW/exact claim与save/save_base/raw/queryset/bulk/delete guards覆盖六个模型，字段集合显式排除session key/data、cookie、CSRF、password/hash与token。
- isolated Django5.2与0051模型组件合计`19 passed`；Django check、Ruff、Black/isort、official增量mypy 0 regressions及architecture 2870/0通过。`makemigrations --check`只报告既有Physical-v2 constraint state重投影，无0052 drift。尚无三个Django repositories/closed-world restore/CAS replay、真实PostgreSQL migrate/race、immutable lifecycle writers或atomic bundle，0052保持zero-seed且staff/request/execution关闭。

### 2026-08-14：Account auth-context/User/RBAC raw authority v3 0052 repositories

- 为三套0052 concrete ledgers分别新增Django repository并精确实现各自Application Protocol。每个repository以显式alias、private nonnested atomic和whole-append savepoint工作；root append在inner savepoint exact-create candidate-independent anchor后`select_for_update`，再锁定并恢复该artifact全部anchors/rows，避免空链双root与调用方捕获失败后遗留孤儿anchor。
- closed-world在任何winner/exact/head/append selector前以strict codec恢复canonical Domain，逐列核facts/fixed/seals、完整历史service recorder、content-bound recorder seal、ledger seal和persisted clock；图校验single root、anchor binding、PROTECT predecessor、Domain adjacent successor、无fork/cycle/orphan/disconnect及terminal无后继。PIT只以recorded-at可知性筛选，logical head即使revoked/deactivated/expired仍返回最终head，由Application current reader返回None，绝不回退旧授权。
- 三repo component合计`14 passed`；与0052 model组件合跑`30 passed`，覆盖root/replay/exact/PIT、successor与terminal no-fallback、无关行raw SQL tamper、private/nested UOW、wrong CAS和caller-caught rollback。Ruff、Black/isort、official增量mypy 0 regressions及architecture 2873/0通过。真实PostgreSQL空root/same-predecessor双连接race、0052实际生产migrate、Django lifecycle writers、source version allocator与atomic bundle provider仍未完成；三账继续zero-seed且staff/request/execution关闭。

### 2026-08-14：Account RBAC authority mutation v3 dormant fact-outbox合同

- 新增纯Application编排合同，并只注入一个`AccountRbacAuthorityMutationV3UnitOfWork`。该UOW未来必须在同alias、同一事务内统一拥有稳定mutation→source identity解析、Profile锁/CAS、0052 winner/head/append和server clock；用例先查first winner，历史exact replay不再读取当前Profile，首次写才核Profile与final head、执行CAS、构造Domain root/successor并在append后复核winner/head/Profile。
- command只接target user、server-issued mutation ID与七角色closed-set中的exact role；拒绝大小写、别名、首尾空白和fallback normalization。当前实现明确标记dormant，不存在concrete UOW、composition或生产调用点。
- final head即使TTL已过仍是唯一合法predecessor，可由owner追加fresh successor；只有revoked terminal阻断同epoch后继，current读取仍对expired head返回None且不回退。定向pure`13 passed`，Ruff、Black/isort、strict mypy及architecture 2874/0通过。该artifact目前只是authority fact-outbox编排合同，不是owner mutation provenance receipt：尚未持久化证明mutation ID→source ID/version映射，也未封存issuer、mutation kind或exact old/new Profile hashes；不得接Profile写入口、注册/setup/signal或staff route，0052继续zero-seed，atomic bundle与execution总闸仍关闭。

### 2026-08-14：Account RBAC mutation binding v3 Domain合同

- 新增纯Domain binding基座：Profile exact old/new refs（profile id/version/content hash）、独立authenticated active staff + canonical `admin` human operator authority ref、固定automated service recorder，以及`bootstrap|role_change|revoke|reactivate`四类状态机。epoch初始/重新激活链、binding ledger chain与raw authority-source chain分域封存；source identity/content/record三重hash、operator/issuer/clock/chain seals与PIT exact selector均闭合，固定inactive/attestation-only/nonexecution。
- pure`16 passed`、Ruff/Black/isort、strict mypy、official增量mypy 0 regressions及architecture 2875/0通过。仍仅是Domain合同：没有codec、0053模型/迁移、closed-world repository、mutation-id持久issuer、Profile anchor/version ledger或同alias concrete UOW；现存Profile不得用updated_at补历史，旧role写入口/注册/setup/signal与所有staff routes继续保持未接，execution仍关闭。

### 2026-08-14：Account RBAC mutation binding v3 strict codec

- 新增strict canonical codec，完整嵌套恢复epoch、old/new Profile refs、human operator authority、service issuer、binding/raw-source双链与全部transition/source/clock/chain/fixed/record seals；exact key集合、bool/int、UTC-Z microseconds、Domain重验与encode equality使未知键、替换、跨链篡改和非canonical时间 fail closed。
- codec unit`18 passed`，Ruff、Black/isort、strict mypy、official增量mypy 0 regressions及architecture 2876/0通过。codec只证明payload封存形状，不证明operator source或mutable Profile真实性；尚无0053 schema/repository/UOW/lifecycle writer，zero-seed与execution总闸保持不变。

### 2026-08-14：Account RBAC mutation binding v3 Application读合同

- 新增ID/version/hash/PIT selector、Persisted binding wrapper与typed repository Protocol；Exact reader只返回`recorded_at <= as_of`的同一mutation/source/hash，Current reader再要求`new_authority_state=current`、TTL窗口与最终head exact equality。revoked/expired/superseded不回退，future row、selector/hash/type替换统一Corruption。
- 定向pure`4 passed`、Ruff、Black/isort、strict mypy、official增量mypy 0 regressions及architecture 2877/0通过。仍是dormant read/persistence合同：无binding codec之外的Django repository、0053 schema、capture/issuer/profile UOW或生产入口，zero-seed与execution继续关闭。

### 2026-08-14：Account RBAC mutation binding v3 0053 schema-only基座

- 新增0053 schema-only迁移（依赖0052），建立独立RBAC source epoch anchor、exact Profile authority anchor/version ledger与mutation binding ledger；migration含四个`CreateModel`及必要FK/索引/约束操作，无RunPython/RunSQL/默认记录/存量回填。binding以PROTECT FK闭合epoch与0052 raw RBAC source，self OneToOne predecessor防分叉，并分别持久化binding-chain与raw-authority-chain refs。
- binding逐列封存mutation kind、old/new Profile identity/version/content refs、human staff+canonical admin operator facts/source refs、service issuer、时钟、fixed inactive/attestation-only/nonexecution、canonical payload、全部Domain seals与ledger seal；Profile version表为未来owner CAS提供稳定版本，严禁使用既有Profile `updated_at`冒充历史。
- isolated Django5.2 model/component `9 passed`；与0052 raw-source model组件合计`25 passed`，Django check、Ruff、Black/isort、official增量mypy 0 regressions、py_compile、architecture 2878/0与diff-check通过。真实PostgreSQL migrate/race、closed-world binding repository、mutation-id持久issuer/UOW、mutable Profile/User/operator lifecycle接线与生产入口仍未完成；0053保持zero-seed，旧role写入口、注册/setup/signal、staff route和execution总闸不变。

### 2026-08-14：Account RBAC mutation binding v3 dormant closed-world repository

- 新增同alias、private non-nestable UOW的0053 repository：winner/exact/head/append均先恢复全部epoch、Profile anchor/version、binding和0052 RBAC raw-source rows，再按`recorded_at`执行PIT selector。raw source canonical codec、fixed recorder、content-bound recorder/ledger seals、binding逐列投影、Profile exact refs与双链图均在selector前核验；坏行、缺FK、anchor/profile孤儿、fork/cycle/disconnect、source-chain substitution和未来隐藏篡改统一fail closed。
- append要求锁定既有epoch、inner savepoint、exact predecessor CAS与IntegrityError exact replay；`get_current_head`保留terminal/expired最终head，不回退旧current。定向repository component `4 passed`，与0053 model、Domain/codec组合`47 passed`；Ruff、Black/isort、py_compile、official增量mypy 0 regressions及architecture 2879/0通过。
- 本批仍是dormant persistence合同：0053空epoch/真实Profile version需未来同一owner UOW提供，未接mutable Profile/User/operator、mutation-id issuer、production role route或staff composition；未取得真实PostgreSQL空链/同predecessor竞争证据，zero-seed与execution总闸继续保持。

### 2026-08-14：Account RBAC mutation binding v3 dormant Application writer contract

- 新增ID/hash-only `AccountRbacAuthorityMutationBindingV3Command`、server-issued identity resolver与单一typed `AccountRbacAuthorityMutationBindingV3UnitOfWork`。写用例在同一注入UOW内先取server clock并解析稳定mutation/epoch identity，再查first winner；命中时只重验已持久binding并直接replay，不读取Profile、operator或live raw source。未命中时按final predecessor（过期但非revoked head仍可续接）读取完整old/new Profile refs、human staff+canonical-admin operator authority与0052 raw RBAC source exact/current，校验source role/subject/epoch闭合，构造完整Persisted binding并以predecessor CAS append，随后复核winner/head。
- 定向writer unit `7 passed`；与既有Domain/codec/read contract/0053 model+repository组合 `54 passed`；Ruff、Black/isort、py_compile、official增量mypy `0 regressions`、architecture `2879/0` 与diff-check通过。Application仅依赖Protocol/Domain，未导入ORM或Infrastructure。
- 本批明确仍为dormant orchestration contract：没有concrete Profile mutation receipt/version issuer、mutable User/Profile/operator lifecycle的同alias实现、0053跨epoch reactivation的PostgreSQL闭环或任何production route/composition；命令不得自行伪造source identity、facts或clock。生产写入口、staff approval、bundle/provider与execution总闸继续关闭，真实PostgreSQL空链/竞争仍待独立验收。

### 2026-08-15：Account authority component evidence runner correction

- 复核发现 RBAC mutation binding、RBAC/User raw authority 与 actor raw model 的 schema-editor component 原先没有显式持有 pytest-django 的数据库解锁边界，直接按仓库默认 settings 运行会出现 `Database access not allowed`，不能把历史计数当作可复现证据。
- 八组测试统一改为在 fixture 内注入 `django_db_blocker.unblock()`，不依赖 pytest-django 自动建表，保持自建 schema 的 zero-seed 语义；使用 `--ds=tests.settings_account_actor_authority_source_v3 --confcutdir=tests/component/account` 重跑，合计 `50 passed`，其中 mutation-binding repository `4 passed`；配套 dormant writer unit `20 passed`。
- 该批只修复 SQLite/no-migrations 组件证据边界，不新增 production writer、不回填 0052/0053、也不宣称 PostgreSQL 空链/同 predecessor race；真实 lifecycle mutation issuer、Profile version UOW、atomic bundle、owner/operator scope 与 execution 继续关闭。

### 2026-08-15：Evidence owner/tenant scope read contract

- 新增纯 Application `EvidenceScopeGrant`、trusted `EvidenceScopeProvider` 与
  `EvidenceScopeAuthorizer`，scope grant 精确封存 actor、tenant、account、目标
  artifact、状态、`recorded_at`/`valid_until` 和 content hash；scope provider 缺失、
  future/stale、revoked、artifact substitution 或 hash tamper 均 fail closed。
- `EvidenceReadFacade` 现在可通过显式注入的 authorizer，在三类 exact read 触碰
  repository 前执行 artifact-level scope gate；未注入时保持既有 staff-only compatibility
  path，未新增路由、ORM、User/Profile 查询或任何写/执行权限。scope contract unit 与
  既有 facade 回归 `12 passed`；新增强制注入 authorizer 的 `ScopedEvidenceReadFacade`，
  避免 owner-scoped composition 忘记安装 gate；增量 mypy/architecture/format/py_compile
  通过。
- 这只是 owner/tenant scope 的本地 Application 合同，不是生产 owner provider、租户
  真源、PostgreSQL current-head/并发证明或人工授权；当前 API 仍 staff-only，Evidence
  hard gate、审批、写入和 execution 总闸继续关闭。

### 2026-08-15：Evidence owner/tenant authority source contract

- 新增纯 Domain `EvidenceScopeSourceV1`，把未来可信 scope source 的最小不可变语义
  固定为 owner、tenant、account、actor 与 exact artifact refs；permission 固定为
  `read_only`，`must_not_execute=true`、`execution_allowed=false`，source content/hash
  不得包含 session/cookie/token/password 等秘密，也不读取 mutable User/Profile/session。
- source 以 candidate-independent root claim 开始，successor 必须绑定 exact predecessor、
  保持 scope identity 不漂移并推进 recorded clock；历史 PIT 只按 recorded knowledge 读取，
  temporal current 受 active/valid window 约束，revoked/expired 不回退旧版本。纯 scope
  Domain/Application/facade 回归 `30 passed`，增量 mypy、architecture、Black/isort、compile
  与 diff-check 通过。
- 这只是 source 语义合同；没有创建 owner/tenant ledger、真实 provider、PostgreSQL
  current-head/并发证明、人工授权或 production route。现有 Django User/session、Account
  owner mapping 与 inactive authority ledger 均不能冒充真源，Evidence hard gate、写入和
  execution 继续关闭。

### 2026-08-15：Evidence owner/tenant authority source strict codec

- 新增 strict `EvidenceScopeSourceV1` codec，完整重建 source 与 nested `ArtifactRef`；
  payload 使用 exact key set/type、canonical UTC `Z` microseconds 和 lowercase SHA-256，
  `identity_hash`/`content_hash`、root/successor、fixed read-only/non-execution semantics
  均由 Domain 重算并复验。未知键、缺键、bool/int 替换、非 canonical 时钟、nested ref、
  chain/hash/fixed tamper 和非 mapping payload 全部 fail closed。
- scope/source/facade codec 回归 `42 passed`；4 个生产文件增量 mypy 无回归，architecture
  audit `0 violations`，Black/isort、compile 和 diff-check 通过。
- 该批仍只是 canonical persistence contract，未创建 ledger/repository/provider，未读取
  mutable User/session/tenant rows，也未接 API、人工授权或 production route；Evidence hard
  gate、写入和 execution 继续关闭。

### 2026-08-15：Evidence owner/tenant authority source Application readers

- 新增 dormant pure Application `GetExactEvidenceScopeSourceV1` 与
  `GetCurrentEvidenceScopeSourceV1` readers。命令只接受 source ID/version、expected content
  hash 与 aware PIT；repository port 要求先完成全表 canonical restore，再返回 exact row 或
  final logical head。exact reader 重新校验 Domain、selector、content hash 与 recorded PIT，
  因而保留 recorded knowledge 之后的历史读取，即使 source validity window 已过期。
- current reader 先做 exact read，再要求 temporal current、final head、稳定 scope identity
  与完整对象/hash 相等；缺失、过期、revoked、已被 successor 替换的候选均返回 `None`，不
  回退旧 active predecessor；future row、类型替换、scope substitution 或 Domain/hash
  tamper 统一 fail closed。source Application/codec/Domain/facade 定向回归 `52 passed`，
  增量 mypy `0 regressions`、architecture audit `0 violations`、Black/isort、compile 与
  diff-check 通过。
- 这是只读 Application 合同，不是 concrete repository 或可信 source provider。当前没有
  owner/tenant immutable ledger、User/session/tenant ORM 取证、PostgreSQL current-head/并发
  证明、人工授权或 production route；Evidence hard gate、写入和 execution 总闸继续关闭。

### 2026-08-15：Evidence owner/tenant authority source schema-only ledger

- 新增零种子 `research_evidence_scope_source_v1` append-only ORM 基座与
  `apps/research/migrations/0028_evidence_scope_source_v1.py`。表逐列保存 Domain/codec 所需的
  scope identity、nested artifact ref、status、recorded/valid clocks、root/supersedes 与
  predecessor、fixed read-only/non-execution flags、canonical payload 及 identity/content
  hashes；数据库约束固定 clock、status、fixed header 与 root/successor XOR，predecessor 使用
  `PROTECT`，所有 save/update/bulk/raw/delete shortcut 继续由 Research evidence guard 拒绝。
- migration 只有一个 `CreateModel`，没有 `RunPython`、`RunSQL` 或默认/现场数据；隔离 SQLite
  schema component `4 passed`，source Application/codec/Domain/facade 与该基座合计 `56 passed`，
  `manage.py check`、`makemigrations --check`、增量 mypy `0 regressions`、architecture audit
  `0 violations`、Black/isort、compile 与 diff-check 通过。
- 这是持久化 schema/guard contract，不是可用的 source provider 或写入闭环。当前没有
  repository full-world restore/append CAS、可信 owner/tenant immutable lifecycle、
  User/session/tenant 取证、PostgreSQL current-head/并发、人工授权或 production route；
  Evidence hard gate、写入和 execution 总闸继续关闭。

### 2026-08-15：Evidence owner/tenant authority source repository

- 新增 `DjangoEvidenceScopeSourceV1Repository` 与 private
  `_DjangoEvidenceScopeSourceV1Store`。public exact/PIT/current-head 读取和 private root/successor
  append 都先恢复整张 ledger，再执行 selector；strict codec、逐列 header、scope identity、
  predecessor FK、单 root/无 fork/orphan/cycle/disconnect、successor Domain validator 和
  recorded PIT 均 fail closed。current-head 即使 terminal/expired 也返回最终 head，Application
  再返回 `None`，不会回退旧 active predecessor。
- private store 只在 repository-owned atomic 与 evidence insert claim 内写入；root/successor
  predecessor CAS、unique collision exact replay、不同内容 conflict、失败事务回滚均有 component
  证据。repository component `6 passed`，与 schema `10 passed`，source Application/codec/Domain/
  facade/plan registry 组合回归 `66 passed`；增量 mypy `0 regressions`、architecture audit
  `0 violations`、Black/isort、compile 与 diff-check 通过。
- 该批仍只是本地 repository/schema contract，不是生产 source provider。尚未取得 PostgreSQL
  空链并发/回滚证据，也没有可信 owner/tenant immutable lifecycle、User/session/tenant 取证、
  人工授权或 production composition；Evidence hard gate、写入和 execution 总闸继续关闭。

### 2026-08-15：Evidence owner/tenant authority source dormant provider adapter

- 新增 `EvidenceScopeSourceV1Provider`。它只接受服务端签发的 source ID/version/content hash
  selector，并通过既有 current Application reader 完整重验 exact source、artifact identity、
  recorded PIT、temporal validity 与最终 head，之后才投影为 `EvidenceScopeGrant`；缺 selector、
  source/artifact substitution、reader unavailable/corruption、revoked/expired source 均 fail
  closed。provider unit `15 passed`，source Domain/codec/Application/schema/repository/facade 组合
  回归 `79 passed`。
- 该 adapter 是 dormant Application contract，不读取 mutable Django User、session、tenant 或
  request，不生成 selector，不提供 writer、人工授权或 route，也不把 source content hash 冒充
  grant projection hash。可信 owner/tenant immutable lifecycle/provider composition、PostgreSQL
  空链并发、production composition、Evidence hard gate、写入和 execution 继续关闭。

### 2026-08-15：EVID-01 下一 slice exit audit

- 对 ScopeSourceV1 的 Domain、strict codec、Application reader、zero-seed ledger、closed-world
  repository 与 dormant provider，以及 Account actor-authority raw ledgers 做了闭环审计。
- 结论：当前仓库没有比 dormant provider 更强、且不依赖真实 immutable owner/tenant lifecycle
  selector issuer、同 alias atomic bundle 和 PostgreSQL 空链/current-head 竞争证据的安全下一小批。
  不新增只按 alias 组装的胶水，避免把零种子账本包装成 production authority。
- EVID-01 继续 active；production owner/tenant read、人工授权、Evidence hard gate、写入和
  execution 保持关闭。下一阶段必须先建立可信 owner/tenant source lifecycle/provider 与其
  deployment/PG 证据，再组装 production read path。

### 2026-08-15：EVID-01 authority provider exception boundary hardening

- 复核发现 owner-scoped scope authorizer 以及 dormant ScopeSourceV1 selector/reader adapter
  对未知数据库、RBAC 或 provider 异常没有统一分类；这会让内部错误穿透 scoped facade，不能
  满足 authority unavailable 时稳定 fail-closed 的边界。现已将未知 `Exception` 统一转换为
  脱敏的 `EvidenceScopeUnavailable`，已知 corruption/unavailable 仍保持既有分类，不捕获
  `BaseException`，也不把异常当作授权成功或 fallback。
- 新增 selector、reader、authorizer 的异常回归与消息脱敏断言；scope-source 单元集为
  `68 passed`，Black/isort、增量 mypy、architecture/audit delta 与 diff-check 通过。
- 这只是本地异常边界加固，不是 owner/tenant authority source：仍没有 immutable lifecycle、
  server-issued selector、同 alias atomic bundle、生产 composition、PostgreSQL race/rollback、
  人工授权或 production route；EVID-01、Evidence hard gate、写入和 execution 继续关闭。

### 2026-08-15：Macro sizing residual output moved into Evidence EVID-03

- 原 Macro sizing 外包任务书的实现资产已完成仓库范围对账，但其 `SizingContextOutput` 同时
  影响直接仓位建议，现登记进 `governance/evidence_output_surfaces.json`：
  `position_impact=direct`、`current_gate_state=not_evidence_integrated_hard_blocked`。当前
  required fields 仅冻结现有 output shape，不把 `calculated_at` 误认成 source observation。
- `EVID-03` 后续必须由可信 source/provider 补齐 source observation time、identity/content
  hash、config/version binding、owner scope、freshness 与 exact-current revalidation；在这些
  证据具备前，SizingContext 不得进入 Evidence-governed input、审批或 execution path。

### 2026-08-13：跨 App 决策读边界与模块循环收口

- Portfolio transition-plan API 不再直接 import SimulatedTrading Application；账户访问由 owner 在启动时注册到 app-neutral registry。registry 缺失时稳定返回 `503`，不会因解耦而绕过账户权限。
- Broker order-detail 不再直接 import Research Application。Research app-root 只注册纯 legacy approval Evidence projector；Broker 对返回字段集合、hash、clock、permission 与 deny markers 做闭合校验，未注册时发布稳定 blocker `broker_order_approval_evidence_provider_unavailable`。
- Account cold-start command 通过 Django app registry 解析 Strategy models，移除 Account→Strategy 静态依赖而不改变初始化步骤或数据。
- 模块依赖治理基线只向下收紧到 `206` edges：`0` bidirectional pairs、`0` cycle components；Account outbound `12`、Strategy inbound `3`，所有全局和 per-app 预算均无 exceeded/stale。

未完成与验证：

- legacy Broker Evidence registry/projector/order-detail 局部测试 `33 passed`；app-neutral Portfolio access registry纯测试已写。Black/isort、AST/py_compile、diff-check和module-cycle guard通过。
- 当前默认Python缺Django/Celery且pytest自动插件缺Playwright，Portfolio API与Account command的完整Django回归未在本环境执行；生产执行总闸和所有inactive合同均未改变。

### 2026-08-14：Evidence composition boundary 与 governance consistency 收口

- 将 Operator Spec approval 的 concrete Django 组装移入 Risk Center-owned `apps/risk_center/evidence_operator_spec_approval_composition.py`，将 lifecycle 的 concrete 组装移入 Research-owned `apps/research/evidence_operator_spec_lifecycle_composition.py`。`core/integration` 仅保留不含 infrastructure import 的兼容导出，Risk Center Interface 直接依赖自己的 composition root。
- 这修复了 governance consistency 唯一失败项 `core_integration_infrastructure_import_growth`（旧的 0→4 concrete imports），不抬高 baseline、不把跨 App ORM 组装下沉到 Application；架构边界与审计扫描均为 0 violations。
- 定向 Application/API 单元回归 `24 passed`；四组 Django component 共收集 `10` 个测试，但在当前环境执行超过 180 秒超时，未计为通过。Data Center catalog `validated=10 datasets`、legacy fact guard、current-data `49 surfaces` 与 Celery `87 registered task(s)` 均通过。
- 本地验证：`python scripts/check_governance_consistency.py`、`python scripts/verify_architecture.py --include-audit --format text` 均通过。生产人工审核、PostgreSQL 并发和真实数据仍未完成，Evidence/decision hard gate 与 execution 总闸保持不变。

### 2026-08-14：Evidence composition Django component contract 回归

- 修正 approval write-flow 测试对 raw subject timestamp tamper 的断言：subject ledger seal 失效必须先于 approval 时序检查，不能把篡改误报成 `predates` 业务时序错误；生产恢复顺序保持 fail closed，不改实现。
- Risk Center/Research 五组隔离 component（`--no-migrations`）合计 `22 passed`。这只证明 SQLite/no-migrations 下的软件恢复与篡改合同；真实迁移、PostgreSQL 并发、生产人工审批、真实数据与 Evidence hard gate 仍未完成，execution 总闸继续关闭。

### 2026-08-15：Account Physical v2 migration-state drift correction

- VPS candidate deploy exposed a repeatable Django warning that account models had changes
  not reflected in migrations. `python manage.py makemigrations --check --dry-run` reproduced
  one drift: `acct_phys_v2_fixed_ck` was structurally equivalent but serialized differently
  between `PhysicalAccountRowObservationV2Model` and migration `0042`.
- Added schema-only `account.0054_normalize_physical_v2_fixed_constraint` (remove/add the
  same named CHECK; no data operation, seed or backfill). `makemigrations --check --dry-run`
  now reports `No changes detected`; `manage.py check` passes. Isolated SQLite forward,
  reverse and re-forward of `0054` all passed.
- This removes the model-state warning for the next deployment, but does not claim that
  production PostgreSQL migration/rollback or Evidence owner authority is complete; the
  production hard gate and execution deny remain unchanged.

## 三、实施阶段

### M0：冻结与设计收口

- 新建独立计划文档、ADR 和 owner/接口矩阵。
- 从当前干净主线另开 `dev/` 分支；不触碰现有未提交的 Dashboard/Research 测试改动。
- 冻结新增旁路决策、计划更新和 Broker 裸执行入口。
- 盘点所有能影响仓位的输出、TUI action、SDK/MCP入口和旧 Transition Plan 写路径。

### M1：Evidence Contract 与账本

- 实现 Domain 合同、传播算法、append-only ORM 和只读 API。
- 为 Data Center、Regime、Policy、Pulse、Alpha、Signal、R1–R8、Strategy/Portfolio 建立 Application adapter。
- 实现 Operator Spec 和风险策略的数据库注册、审批、激活流程。
- 旧输出生成非持久化兼容 Envelope：`legacy_unverified + DISPLAY_ONLY`。
- 不改变现有结果表和 canonical hash。

### M2：Track Record 与 TUI

- 先以 R7 完成首个端到端 Track Record，再验证 R8 的“确定性算法+预测输入”传播。
- 依次接入 R1/R3/R6、R2/R4/R5 和现有生产决策模块。
- 更新 TUI schema、compiler、runtime 和 Workbench renderer。
- 所有决策 primary action 通过编译和运行时 Evidence Binding 检查后，才允许进入切换清单。

### M3：Policy Benchmark

- 建立账户基准定义、生命周期、每日估值和再平衡回执。
- 增加账户 TUI 配置与显式批准流程。
- 首次激活后从 live inception 开始影子净值，不回填历史。
- Audit 仅在共同日期、时钟、币种和 coverage 对齐后开放比较。

### M4：Attestation、Risk Gate 与 Broker

- 将 `decision_rhythm` 旧计划写路径改为 Portfolio Application facade，禁止原地修改 payload。
- 实现签署、主动风险计算、预算预约、证伪复核案件。
- 将 receipt/hash 纳入 Broker approval digest，在四个执行节点重验。
- 更新 Signal/Portfolio/Benchmark Celery outcome 契约以及 Task Monitor 告警投影。
- 完成旧 SDK 的只读兼容和执行阻断错误码。

### M5：生产硬切换

- 切换前冻结新审批、打开 Broker kill switch、暂停 Agent lease，并运行只读预检。
- 应用 schema-only migration，注册并激活数据库 Operator Spec 和保守风险策略；所有 artifact 初始化为 SHADOW。
- 无新 receipt 的 `WAITING_APPROVAL/READY/LEASED` 订单转为 `DECISION_REVIEW_REQUIRED` 并释放租约。
- 已提交、部分成交和已成交订单保留原状态；现有持仓标记 `legacy_unattributed/SHADOW`，允许安全减仓但不能基于旧信号加仓。
- Web、Worker、Agent 同版本部署并完成 smoke/reconciliation 后解除 kill switch。
- 正式环境没有 warning-only 或绕过开关；回滚只能重新打开 kill switch，不能回退到可绕过新门禁的旧执行路径。
- Append-only 账本永久保留，不随 UI 或调度回滚删除。

## 四、测试与验收

### 测试包

- Domain：分类正交、传播、hash/clock、permission 交集、Promotion 不继承、版本/horizon 隔离。
- Track Record：完整分母、`n=0`、`n_eff`、未来证据、基准与 CI、漂移和版本错配。
- Risk：主动权重、TE、换手、family 聚合、拆单、并发额度争抢和 safe harbor。
- Persistence：ORM/QuerySet/bulk/raw update/delete 绕过、并发 first-winner、幂等与 fork/tamper。
- Benchmark：入金出金收益中性、股息利息、拆股、成本、再平衡、节假日、缺价和 FX 阻断。
- E2E：Plan → 签署 → 授权 → Broker批准 → lease → submitting → fill → 额度结算。
- 失效场景：审批后 Promotion 过期、freshness 下降、基准换版、证伪触发，提交前全部阻断。
- TUI：所有 view type 永久显示 Strip，`n=0` 与 unavailable 区分，键盘/屏幕阅读器和三种 viewport 可用。
- Migration：zero-seed、zero-backfill、往返迁移、旧计划和订单状态转换。
- 性能：批量 Evidence resolve，无 TUI N+1；Broker 提交只读本地 receipt，不调用外部网络。

必须运行相关 Portfolio/Risk/Broker/Signal/Task Monitor 测试、架构 guard、增量 mypy、TUI compiler/JS/build，以及项目规定的 TUI、Terminal、SDK、SSL 最小回归包。新增任务同步登记 `celery_task_contracts.json`，current/latest 基准接口登记 `current_data_contracts.json`。

### 最终验收

- 任意决策输出都能还原分类、数据 lineage、版本、Promotion、Track Record 和有效权限。
- `n=0`、SHADOW、ADVISORY、缺基准或证据不可核验时，无法通过任何系统入口增加模型归因风险。
- R8 明确显示“确定性优化方法+预测/估计输入”，不会制造虚假精确感。
- 每笔新增主动风险都绑定人工签署、证伪条件、风险授权和政策基准。
- 证伪触发会阻断新增风险并生成复核案件，但不会自动平仓。
- 每个账户从明确 inception 开始持续获得扣成本、同现金流口径的政策基准对照。
- 旧记录可读、不可伪装为已验证；旧客户端无法绕过新执行闸门。

## 五、明确假设

- Evidence 基础设施完成不等于 R1–R8 ready；真实 Publication、PIT、OOS、Promotion 和 consumer 验收仍须独立完成。
- 所有金融阈值、Operator Spec 和基准定义均以数据库 active version 为真源；无 active 记录时 fail closed。
- 不新增 Classic Django 业务页面、不新增 raw MCP tool、不创建 Docker 文件。
- 不把 Evidence 业务规则放入 `shared/`；Research 定义合同，Data Center/Audit 提供证据，Risk Center/Portfolio执行门禁，TUI负责强制展示。
- 历史 replay 与 live OOS 严格隔离，任何旧数据都不自动获得新证据等级。

## 2026-08-15 EVID-02 PostgreSQL 并发 harness 边界

- 新增 `tests/settings_evidence_scope_source_v1_postgres.py` 与
  `tests/component/research/test_evidence_scope_source_v1_postgres_concurrency.py`，仅针对
  `EvidenceScopeSourceV1` ledger 提供显式 opt-in 的 PostgreSQL 证据 harness。
- harness 覆盖空链 root first-winner、同 predecessor successor 单赢家，以及异常回滚后无残留行；URL
  必须是本地/测试服务且数据库名同时含 `evidence` 与 `test`，非空库、SQLite、VPS/生产 host 均拒绝。
- 默认运行保持 `3 skipped`；本轮未取得 disposable PostgreSQL 实际运行证据（Docker daemon 当前未能响应），
  因此 `EVID-02` 仍为 planned，不能把 SQLite 或测试收集结果写成 PostgreSQL 并发通过。

2026-08-15 追加尝试使用本机 `127.0.0.1:5432` 的临时 PostgreSQL 服务创建受约束的
`evidence_scope_test_20260815` 数据库；连接在 3 秒超时窗口内失败，数据库未创建，harness
未运行。该结果只确认当前本机 PostgreSQL/Docker 工具链仍不可用，不改变 `EVID-02` 的
planned 状态，也不将任何 SQLite、VPS 或生产库结果计为并发证据。

随后本机隔离 PostgreSQL 容器恢复可用后，修正 harness 缺少
`pytest.mark.django_db(transaction=True)` 的测试隔离声明，并让两个 successor 候选保持
同一 artifact identity、仅以不同 validity 窗口形成合法内容竞争。使用专用数据库
`evidence_scope_test_20260815`（容器 `postgres:18.4`，数据库创建前为空，测试后已删除）运行：

```text
AGOM_EVIDENCE_SCOPE_PG_CONCURRENCY_EVIDENCE=1
AGOM_EVIDENCE_SCOPE_PG_TEST_DATABASE_URL=postgresql://<local-test-user>@127.0.0.1:5432/evidence_scope_test_20260815
python -m pytest tests/component/research/test_evidence_scope_source_v1_postgres_concurrency.py -q --create-db --confcutdir=tests/component/research -p no:cacheprovider
... 3 passed in 207.58s ...
```

这是真实本机 PostgreSQL 的空 root first-winner、同 predecessor 单 successor 和 rollback/no-orphan
软件证据；不接触 VPS/生产库，也不证明生产 alias、owner/tenant lifecycle、人工授权、
publisher/runtime 或 execution gate。`EVID-02` 因此仍为 planned，仅关闭该本地 harness 子项。

## 2026-08-15 EVID-01 scope grant integrity hardening

`EvidenceScopeAuthorizer` 现在在接受 provider 返回的 grant 后重新执行完整的
`EvidenceScopeGrant` invariant，再核对 content hash；provider 不能通过替换 permission、
identity 或 scope 字段并重算 hash 来绕过 `read_only`/scope 合同。scope ID、version、actor、
tenant、account token 也统一要求严格字符串、无空白且长度不超过 192。

新增 permission substitution（重算 hash）和非法 token 回归。EVID scope/source/facade 全套
回归 `74 passed`，增量 mypy 无 regressions，Black/isort/diff-check 通过。该 slice 仍只是
本地 fail-closed authority boundary；没有 immutable owner/tenant lifecycle、真实 provider、
PostgreSQL 并发、人工授权或 production route，`EVID-01` 与 Evidence hard gate、写入和
execution 继续关闭。

## 2026-08-15 EVID-01 Application selector boundary hardening

统一 `EvidenceScopeSourceV1` Application reader 与 dormant provider selector 的 identity/version
令牌边界：`source_id`、`source_version` 必须是无空白、非空且不超过 192 字符的 bounded canonical
token。这样入口校验与 Domain、codec、repository 及 ORM `max_length=192` 保持一致；超长 selector
在读取或投影 grant 前即 fail closed，不会依赖后续层级补救。

新增 Application command 与 provider selector 的超长令牌回归；scope source Application/provider
聚焦回归 `78 passed`，Black/isort、增量 mypy、治理一致性和 diff-check 通过。此项只是本地输入
边界加固，不创建 selector issuer、immutable owner/tenant lifecycle、production composition 或
route；`EVID-01`、Evidence hard gate、写入和 execution 继续关闭。

## 2026-08-15 AUD-01 authority snapshot token boundary hardening

`SystemAuditAuthoritySnapshot` 的 actor、tenant、owner 与 role 现在共享 bounded canonical token
边界：必须非空、无首尾/内部空白且不超过 192 字符；authority content hash 在序列化前也执行
同一校验。这样 scope identity 不能通过异常空白或超长值进入 provider-issued snapshot，再由
重算 hash 掩盖输入不规范。

新增空白/超长 token 回归并保持 authority/provider 未接线、publisher `publisher_not_wired` 和
query fail-closed 语义不变。该 slice 只收紧本地 composition contract；没有 authenticated
authority source、tenant/owner lifecycle、durable publisher、production route 或审计运行时接入，
`AUD-01` 与 AUD-02/03 依赖状态不变。

同一边界已同步到 `SystemAuditReaderContext` 的直接 query contract：actor 与 role selector
不能通过空白或超长值绕过 canonical context 构造。query unit `14 passed`，与 composition、
outbox dispatch/metrics runtime 聚合回归 `46 passed`；这仍只是 dormant read contract，不能替代
真实 authenticated/RBAC authority source。

## 2026-08-15：Evidence hard-gate next-slice exit audit

对当前最高优先级的 Evidence/Broker 执行链做了只读复核，结论是本地没有可以安全开启终态的
production slice：

- `apps/broker_execution/application/evidence_gate.py` 的
  `broker_order_evidence_integrated()` 仍固定为 `False`，create/approve/lease/submitting
  四个节点继续 fail closed；这是当前保护行为，不是待绕过的测试门槛。
- `governance/evidence_output_surfaces.json` 的 66 个 surface 中，15 个直接影响仓位的
  surface 仍为 `integrated=0`；`SizingContextOutput`、`AdvisorOrderIntent`、TransitionPlan
  与 OrderDraft 没有可证明的 owner-scoped canonical Evidence/consumer binding。
- Risk Center 的本地 policy/approval ledger 与 SQLite component 不能替代 production
  composition；没有真实 Risk policy source、Broker execution scope、Portfolio exact plan/
  approval、Research execution-eligible Envelope/TrackRecord provider，且相关 production
  composition 尚未注册。
- Account owner/tenant authority 仍是 dormant、zero-seed raw ledger。禁止从 mutable
  User/Profile/session/request、数据库 alias 或现场 hash 推导 authority；本机 PostgreSQL
  first-winner/rollback harness 只证明 disposable local PostgreSQL 软件行为，不计作 VPS/生产
  alias 证据。

在当前候选 `dev/next-development@45281620a8739ee666a1b20e6c6511c0b8101111` / release
`20260815230537` 上，远端只读 inventory 进一步确认 auth-context、User authority、RBAC
authority、actor bundle 与 Evidence scope source ledger 均为 `0` 行。这证明 schema 没有 seed/
backfill，不证明 authority 已存在；对应 scope-provider 与 actor-authority application 回归为
`29 passed`，仍是 dormant read contract。

因此本轮不新增一层只按 alias 拼装的胶水，也不接 Broker issuer、execution consumer 或生产路由。
下一真实依赖固定为：不可变 tenant/owner lifecycle、authenticated staff/tenant/owner provider、
Research/Portfolio/Risk/Broker 同源 exact bundle，以及合格 staging/production PostgreSQL
并发与回滚证据。完成这些前，EVID-01/EVID-03、AUD-01、写入和 execution 总闸保持关闭。

## 2026-08-16：EVID-01 当前候选 authority inventory 复核

在当前 production candidate `e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` /
release `20260816004134` 上，通过只读 PostgreSQL 查询复核了 0050–0053 migration 与
authority 账本行数。0050、0051、0052、0053 均已应用；auth-context、User/RBAC raw
authority、actor source、Evidence scope、subject/evidence/receipt 账本均为 `0` 行。
机器摘要见
[`evid-01-authority-inventory-2026-08-16.json`](../deployment/evid-01-authority-inventory-2026-08-16.json)。

这确认当前部署是 schema-ready/zero-seed，而不是已经存在可用的 owner/tenant authority。
不得从 mutable User/Profile/session/request、数据库 alias 或现场 hash 推导或回填 authority；
EVID-01、Evidence hard gate、写入和 execution 继续保持关闭。下一真实交付仍是 owner-issued
immutable lifecycle、authenticated scoped provider、同 alias exact bundle、人工授权和
production PostgreSQL 并发/回滚证据。

## 2026-08-16：EVID-01 scope grant owner binding hardening

`EvidenceScopeGrant` 现在显式保存 `owner_id`，并将其纳入 canonical content hash；
`EvidenceScopeSourceV1Provider` 从 immutable source 到 grant 的投影逐字段保留 owner，避免
scope grant 只绑定 actor/tenant/account 而丢失 owner 维度。scope/source 单元回归 `37 passed`，
与 Data Center structure/architecture guard 聚合 `46 passed`，增量 mypy regression 为 `0`。

这只是本地 owner identity/contract 加固，未创建 owner/tenant lifecycle、selector issuer 或
production composition，也未读取 mutable User/session/tenant；人工授权、PostgreSQL 并发与
Evidence hard gate、写入和 execution 继续关闭。

## 2026-08-16：Evidence hard-gate critical test contract alignment

CI 暴露的关键执行测试仍假设订单可以在 Evidence 未接入时审批、租赁或进入 Fake Agent
流程。现已将 `tests/critical/test_risk_and_order_safety.py` 与
`tests/critical/test_agent_and_recovery_safety.py` 对齐当前 fail-closed 合同：创建/审批/租赁
及 Fake Agent 入口稳定返回 Evidence 阻断，订单保持 `WAITING_APPROVAL`，不触发 broker、
snapshot、lease 或 fill 副作用。critical 回归 `13 passed`。

该 slice 只修正测试合同，没有放宽 `broker_order_evidence_integrated()`、没有创建生产
Evidence publisher/authority，也没有解除写入或 execution 总闸。全仓 mypy debt ceiling 和
module-cycle baseline 仍需独立治理，不能用提高基线或扩大 allowlist 冒充修复。

## 2026-08-16：EVID-01 scope grant nested artifact invariant hardening

`EvidenceScopeGrant` 与 `EvidenceScopeAuthorizer` 现在在 scoped boundary 重新执行嵌套
`ArtifactRef` 的完整 value-object invariant。这样 provider 即使原地篡改请求 artifact 并重算
grant content hash，也不能把非法 artifact identity 伪装成合法 owner-scoped grant；请求在进入
provider 前也会 fail closed。

新增 nested artifact mutation / provider hash-recompute 回归；scope/source/provider/facade focused
回归 `71 passed`，Black/isort、增量 mypy regression `0`、architecture/audit `0 violations`。
`ruff` 当前环境未安装，未将其记为通过。该 slice 仍只收紧本地 Evidence authority boundary，
不创建 immutable owner/tenant lifecycle、selector issuer、production composition 或 route；
EVID-01 仍 active，EVID-02/EVID-03、人工授权、PostgreSQL 生产证据、Evidence hard gate、写入和
execution 继续关闭。

## 2026-08-17：EVID-01 authority inventory candidate binding guard

当前候选 `443658d33159dd80a35b3001ae2c8505113e3fff` / release `20260816223921` 的
registry、cutover candidate、deployment preflight、VPS runtime verification 与只读
authority inventory 已一致。`tests/unit/test_evid_01_authority_inventory_evidence.py`
不再固定某一个历史文件，而是从当前 cutover candidate 唯一匹配 preflight、runtime 与
`evid-01-authority-inventory` artifact，并校验 preflight SHA、OCI revision、runtime image
及 `blocked_zero_seed_authority`/12 表全零状态；focused 回归 `1 passed`。

该 guard 只防止旧 release、旧 runtime 或旧 zero-seed inventory 串入当前候选，不创建或
回填 authority，不读取 User/Profile/session 现场状态，不接 production writer，也不改变
Evidence hard gate。immutable owner/tenant lifecycle、authenticated scoped provider、同
alias exact bundle、人工授权以及 PostgreSQL production race/rollback 证据仍缺，
`EVID-01` 保持 `active`，`EVID-02`/`EVID-03` 与写入/execution 继续关闭。

## 2026-08-19：EVID-02 offline PostgreSQL evidence collector/report contract

新增纯 Application `apps/research/application/evid_02_postgres_evidence.py`，以及
`scripts/record_evid_02_postgres_evidence.py`。collector 只接受固定
`tests/component/research/test_evidence_scope_source_v1_postgres_concurrency.py` 的机器结果，
严格校验本地/测试 PostgreSQL、disposable/empty-before、三项 root/successor/rollback
case 的逐项 facts、UTC 时间、完整 case 集和 secret 字段边界；报告由逐项结果推导，不能由
caller 自报 aggregate `passed`。报告明确标记 `offline_disposable_postgresql_software`、
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`，
并把 current-head read-only audit 与 human approval 缺口记录为 `not_collected`。

新增 `tests/unit/test_evid_02_postgres_evidence.py`，覆盖 deterministic canonical bytes/hash、
缺失/重复/未知 case、skip/inconsistent facts、SQLite/远程/production host、非 disposable
数据库、UTC/secret/unknown-field、不可伪造 human approval/head audit，以及 dry-run、
content-addressed append-only writer collision；focused 回归 `15 passed`。

该 slice 只完成 EVID-02 自动采集的离线报告合同，不连接 PostgreSQL、Risk Center approval
writer、VPS/production database 或真实审核人；不把 `EvidenceScopeSourceV1` harness 误称为
approval proof。`EVID-02` 仍为 `awaiting_production`，registry exit gate、EVID-01 authority
要求、Evidence hard gate、写入和 execution 继续保持 fail-closed。

## 2026-08-19：EVID-02 current-head/approval link audit contract

在离线采集报告之上新增纯 Application `apps/research/application/evid_02_head_audit.py`
与显式 dry-run/append-only CLI `scripts/record_evid_02_head_audit.py`。输入只接受外部捕获
的 `evid-02-head-audit-snapshot.v1`：严格校验 UTC-Z、PIT 截止、全链 root/predecessor/head、
分叉/孤儿/循环/未来行、approval→activation 的 exact operator/version/definition 绑定，
并拒绝未知键与秘密字段。报告固定为 `production_claim=false`、`production_ready=false`、
`runtime_enablement=not_authorized`、`human_approval_status=not_collected`；写入仅使用
内容寻址本地工件，默认不写且不触碰数据库或 approval writer。

新增 `tests/unit/test_evid_02_head_audit.py`，覆盖空账本、线性 head、缺失/漂移引用、分叉、
孤儿、断根、时钟回退、未来 PIT、未知/秘密字段、非 canonical 时间、稳定序列化与报告
内容哈希；EVID-02 离线报告与 head audit 合计 `29 passed`，增量 mypy、Ruff、Black、isort
通过，债务门禁需以命令最终输出为准。

该 slice 只完成“外部快照→fail-closed current-head 报告”的本地合同，不读取生产 PostgreSQL、
不接 Risk Center approval/activation writer、不生成真实并发/回滚或人工审批证据。`EVID-02`
仍为 `awaiting_production`，EVID-01 authority、生产双连接 first-winner/rollback、真实
approval owner/reviewer 与 Evidence hard gate 继续保持 fail-closed。

## 2026-08-19：EVID-01 当前 HEAD VPS authority inventory 只读验收

当前 `dev/next-development@0ad5df129fbc5d0d6c3030287a0a88c83b6ae871` 已按 code-only、保留
PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 流程发布为 release `20260819193755`，
镜像为 `sha256:571940d6198ebe4c2c6b1774d8c51b4893d708d9e7d5e057c3890525d045898c`。部署
verifier 对 Caddy domain/TLS、HTTPS health、容器、Django check、迁移/schema、TUI registry、
Qlib、Celery ping 与部署前 PostgreSQL backup 全部通过；报告为
`dist/remote-build-reports/remote-build-report-20260819193755.json`。

在同一 release/web 容器内以 PostgreSQL 只读查询复核 account 0050–0053 migration，并逐表
读取 EVID-01 约定的 12 张 authority/evidence ledger/root-lock 表；12 张表的 row count 均为
`0`。机器证据落盘于
[`docs/deployment/evid-01-authority-inventory-2026-08-19-1156.json`](../deployment/evid-01-authority-inventory-2026-08-19-1156.json)，
结果固定为 `blocked_zero_seed_authority`。

这一步只证明当前候选的运行身份、schema/migration 和 zero-seed 状态，不证明 authority
lifecycle、authenticated owner/tenant provider、同 alias bundle、人工授权、生产 writer 或
PostgreSQL race/rollback。严禁从 mutable User/Profile/session/request 现场 hash 或回填历史；
`EVID-01` 继续 `active`，Evidence hard gate、写入与 execution 继续 fail-closed。

## 2026-08-19：M5 candidate `20260819195103` / EVID-01 inventory 重绑验收

共享 candidate binding 已切换到 `dev/next-development@0ad5df129fbc5d0d6c3030287a0a88c83b6ae871`
、release `20260819195103`，并在 `governance/active_plan_registry.json` 的 M5 `next_gate`
中同步该 candidate。当前 VPS `current` 与 web/celery image 均为该 release；最新只读 verifier
确认 Caddy/TLS、HTTPS health、容器、Django check、迁移/schema、TUI registry、Qlib、Celery
ping、备份和 healthcheck 通过。

对同一 candidate 重新执行 PostgreSQL 只读盘点，account 0050–0053 均已应用，EVID-01 约定的
12 张 authority/evidence ledger/root-lock 表仍全部为 `0`。对应 runtime 与 inventory 工件为
[`vps-runtime-verification-2026-08-19-1210.json`](../deployment/vps-runtime-verification-2026-08-19-1210.json)
和 [`evid-01-authority-inventory-2026-08-19-1210.json`](../deployment/evid-01-authority-inventory-2026-08-19-1210.json)，
静态 candidate-binding 回归 `1 passed`。

这只是 candidate binding 与 zero-seed 只读验收；不代表 M5 角色化浏览器 UAT、写后 receipt/
refresh、14 日观察、restore/rollback 或 owner/reviewer 已完成，也不代表 EVID-01 的
authenticated owner/tenant lifecycle、同 alias bundle、人工授权、production writer 或
PostgreSQL race/rollback 已存在。`EVID-01`、M5、Evidence hard gate、写入和 execution 继续
fail-closed。

## 2026-08-19：EVID-01 offline authority-inventory report contract

新增纯 Application 合同
`apps/research/application/evid_01_authority_inventory.py` 与显式
`scripts/record_evid_01_authority_inventory.py`。输入仅是外部受控的
`evid-01-authority-inventory-snapshot.v1` JSON；解析器固定 production/PostgreSQL/public、
0050–0053 account migrations、12 张 authority/evidence/root-lock 表和 read-only 语义，
并对候选 commit/release、UTC-Z 微秒时间、非负严格整数、未知键及递归 secret 字段
fail-closed。报告由逐表 row count 确定性推导：全零为 `blocked_zero_seed_authority`，
任一非零为 `blocked_unverified_authority`；报告永远固定
`production_claim=false`、`production_ready=false`、`authority_ready=false`、
`runtime_enablement=not_authorized`。

命令默认只输出 canonical summary；仅显式 `--write --output-root` 才在本地内容寻址目录
追加 JSON 与 SHA-256 sidecar，重复写入 exact replay，不覆盖既有工件。新增
`tests/unit/test_evid_01_authority_inventory.py`，覆盖 zero/nonzero outcome、schema/type/
candidate/backend/time/secret tamper、无 ORM/网络边界、dry-run、append-only collision 与
重复写入；EVID-01 focused 回归为 `16 passed`，Ruff/Black/isort、增量 mypy、全量 debt
ceiling、governance consistency 均通过。

该 slice 只完成“外部快照→fail-closed 本地报告”合同，不连接 PostgreSQL/VPS，不读取或
回填 User/Profile/session，不创建 owner/tenant lifecycle、authenticated provider、人工
授权、production writer，也不提供 PostgreSQL 双连接 race/rollback 证据；因此不改变
registry 状态，`EVID-01` 继续 `active`，Evidence hard gate、写入与 execution 继续
保持 fail-closed。

## 2026-08-19：EVID-01 offline contract candidate deployment and observation

提交 `0c92cf6357ea2e33877319342745fb4eadde103f` 的四条必需 CI 已全部成功（Security、
Architecture、Consistency、Fast Feedback；Python 3.11/3.13 与完整 production mypy debt
ceiling 均通过）。随后按 code-only `-Upgrade`、保留 PostgreSQL/Redis 数据卷、启用 Celery
发布到 VPS，release `20260819210655`，镜像
`sha256:af5bb7953e42d7842151109edce1d6add7a9e12236c0a54e57273e6eaa493c2e`。部署 verifier
确认 Caddy/TLS、HTTPS health/ready `200`、web healthy、Celery worker/beat/ping、Django
check、迁移/schema、TUI registry、Qlib 与备份均通过；只读运行摘要见
[`vps-runtime-verification-2026-08-19-1334.json`](../deployment/vps-runtime-verification-2026-08-19-1334.json)。

在同一 release/web 容器中执行只读 PostgreSQL 查询，0050–0053 均已应用，EVID-01 约定
12 张 authority/evidence/root-lock 表全部为 `0` 行；原始快照见
[`evid-01-authority-inventory-snapshot-2026-08-19-1332.json`](../deployment/evid-01-authority-inventory-snapshot-2026-08-19-1332.json)，
旧版兼容验收工件见
[`evid-01-authority-inventory-2026-08-19-1332.json`](../deployment/evid-01-authority-inventory-2026-08-19-1332.json)，
新的 canonical report 内容寻址工件见
[`evid-01-authority-inventory/9d/9dc07b28dd278133a1f2dab078a0c2c3c06862fa9094a9e2e78c3143bcd5162d.json`](../deployment/evid-01-authority-inventory/9d/9dc07b28dd278133a1f2dab078a0c2c3c06862fa9094a9e2e78c3143bcd5162d.json)。

这次部署只验证该代码候选的运行身份、短时只读健康与 zero-seed；没有执行业务登录/写入、
authority backfill、destructive migration、restore/rollback 或人工审批。M5 的 registry/
cutover candidate 仍绑定此前的 TUI 候选，本非-TUI slice 不自动重绑观察窗口；ready 仍含既有
`etf_net_flow` degraded/stale 观察。authenticated owner/tenant lifecycle、同 alias bundle、
人工授权、production writer、角色化浏览器 UAT、14 日 telemetry、PostgreSQL race/rollback
和 Evidence hard gate 继续 fail-closed。

## 2026-08-20：当前候选 EVID-01/AUD-03 PostgreSQL 只读盘点

在当前 VPS release `20260820012016` 的 web 容器内，以只读 Django/PostgreSQL 查询复核了
account `0050`–`0054`、agent_runtime `0004` 与 audit `0012` migration；均已应用。EVID-01
约定的 authority/evidence/root-lock 表仍全部为 `0` 行，另观测到
`audit_system_outbox=0` 与 `audit_system_event=0`。本次没有创建、更新、删除、回填或触发
任何业务写入。

该证据只确认当前候选的 schema、zero-seed authority 状态和“当前没有 outbox backlog”；空
outbox 不能证明 durable publisher、dispatcher claim/delivery、authenticated owner/tenant
authority 或同 UOW 双写已接通。`EVID-01` 与 `AUD-01/AUD-03` 的生产 writer/authority、
PostgreSQL race/rollback、migration/restore/owner sign-off 仍保持 fail-closed。

## 2026-08-20：EVID-01 formal candidate VPS acceptance recheck

按当前 active registry 的正式候选
`f3881a04cf0b5d5bff5d2b7e5a6bf25d523667e2` / release `20260820043710` 直接运行
`scripts/deploy_vps_verify.py --expected-commit ...`，验证器明确拒绝候选绑定：远端当前实际
运行的是 `7cf7e984373af71b6f96b234cefb78b5f319d770` / release `20260820145119`，镜像
`sha256:6af515cee168cb4a406c158078f73eeab7e7931f331fbbff98b892f9ff701dca`。因此本轮没有
把当前运行版本的健康结果拼接到 `f388...`，也没有生成或写入伪造的
`vps-runtime-verification-*` / `evid-01-authority-inventory-*` 候选工件。

对远端当前实际版本（`7cf...`）另行完成只读复核：expected-commit verifier exit `0`；
Caddy/TLS、Django check、0050–0053 migration/schema、TUI registry、Qlib、备份、资源、
Celery worker/beat/ping 均通过；HTTPS `/api/health/`、`/api/ready/`、`/api/`、
认证后的 `/api/tui/`、`/api/policy/status/`、`/api/audit/health/`、
`/api/audit/metrics/` 均为 `200`。认证后的 `/api/terminal/runs/` 保持预期
`503 queued_runtime_not_wired`，`/api/regime/current/` 保持
`503 decision_runtime_blocked` 与 `must_not_use_for_decision=true`。同一远端 PostgreSQL
只读盘点（2026-08-20 08:42:33Z）确认 0050–0053 均已应用，EVID-01 约定的 12 张
authority/evidence/root-lock 表全部为 `0` 行。

这证明当前实际运行版本健康且 authority 仍 zero-seed，但不满足 formal `f388...` candidate
binding；`tests/unit/test_evid_01_authority_inventory_evidence.py` 仍诚实地失败（缺同
候选 runtime/inventory 工件）。在 release owner 明确重绑候选并重新取得同一 commit/release/
image/matrix 证据前，`EVID-01`、M5、AUD-01、写入与 execution 继续 fail-closed；本轮未做
业务写入、authority 回填、生产 restore/rollback、角色化 UAT、容量/chaos 或 owner/reviewer
签字。

## 2026-08-21：EVID-02 disposable PostgreSQL concurrency harness acceptance

在本机一次性 `postgres:16-alpine` 容器的空数据库
`evidence_scope_test_20260821` 中，使用隔离设置
`tests.settings_evidence_scope_source_v1_postgres`、显式测试开关和
`--confcutdir=tests/component/research` 运行固定并发套件：
`tests/component/research/test_evidence_scope_source_v1_postgres_concurrency.py`，结果为
`3 passed`（本次带 `--durations=0` 的 pytest 输出为 `15.48s`，进程墙钟
`2026-08-20T20:10:42.331802Z`–`2026-08-20T20:11:00.639474Z`）。空根 first-winner、同
predecessor successor first-winner 与 outer-transaction rollback 三项事实分别为
`(winner,conflict,rows)=(1,1,1)`、`(1,1,2)`、`(0,0,0)`；测试数据库已在取证后删除。

原始输入为
[`evid-02-postgres-concurrency-run-2026-08-21.json`](../deployment/evid-02-postgres-concurrency-run-2026-08-21.json)，
通过离线 recorder 生成的 canonical 内容寻址工件为
[`a27e193f53910cdb4395cc88d4d96fb04fcda71f2f191dbda7df2626299e6df8.json`](../deployment/evid-02-postgres/a2/a27e193f53910cdb4395cc88d4d96fb04fcda71f2f191dbda7df2626299e6df8.json)，
SHA-256 为 `a27e193f53910cdb4395cc88d4d96fb04fcda71f2f191dbda7df2626299e6df8`；
unit 合同与 head-audit 回归为 `29 passed`，dry-run 与 append-only 写入均成功。

该工件固定 `evidence_scope=offline_disposable_postgresql_software`、
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`；
它只证明本地 PostgreSQL 软件层的双连接 first-winner/rollback 合同，不读取既有 production
ledger，`head_audit` 与 `human_approval` 均保持 `not_collected`。因此 `EVID-02` 仍为
`awaiting_production`，真实 VPS PostgreSQL race/rollback、current-head snapshot、Risk
Center approval、owner/reviewer 签字和 Evidence hard gate 继续 fail-closed。

## 2026-08-21：EVID-02/STRAT-01 VPS 只读账本盘点

在当前 VPS 实际运行的 `dev/next-development` commit
`4c49dd8a247bf83984346984c1663842e670a2fe` / release `20260821024537` 的 web 容器内，
以 Django PostgreSQL connection 的只读 `SELECT COUNT(*)` 复核 EVID-02 approval/activation
相关表。`risk_center_evidence_operator_spec_subject`、
`risk_center_evidence_operator_spec_approval`、`research_evidence_operator_spec_approval`、
`research_activated_evidence_operator_spec`、`research_r6_activation_authorization`、
`research_evidence_operator_spec`、`research_evidence_track_record` 与
`research_evidence_envelope` 均为 `0` 行；同一运行态 `/api/health/` 与 `/api/ready/` 均为
`200`。空 rows 按既有 `evid-02-head-audit-snapshot.v1` 合同解析为 approval/activation
`empty`、无 current head，`human_approval_status=not_collected`。

同一只读盘点还检查了 STRAT-01 的 canonical ledger families：`research_r1_` 至
`research_r8_` 共 `65` 张表、`portfolio_r4_`/`portfolio_r5_`/`portfolio_r8_` 共 `7` 张表，
以及四张 `equity_forecast_baseline_*` 表，全部为零行；R1–R8 依赖的 Data Center actual/PIT、
macro-factor 与 market-structure calendar/series 表也全部为零。结构化盘点工件为
[`evid-02-strat-01-vps-readonly-inventory-2026-08-21.json`](../deployment/evid-02-strat-01-vps-readonly-inventory-2026-08-21.json)，
SHA-256 为 `09d628c3070068e621bc3550bd0d20a70669274c29977c3ddfbc5006fafbf0e5`。

这次验收只证明当前候选健康、schema 可读和 canonical owner/evidence 账本为空；没有创建、
更新、删除、回填、人工审批或 rollback，也没有把现有 Data Center facts 现场提升为 owner/
definition/policy 证据。因此 `EVID-02` 继续 `awaiting_production`，`STRAT-01` 继续等待
真实 owner/definition/policy/calendar/scope/qualification 登记；生产 first-winner、successor、
current-head、rollback、人工 reviewer 与 Evidence hard gate 仍保持 fail-closed。

## 2026-08-21：EVID-02/STRAT-01 current HEAD 只读盘点重绑

为避免把旧 release 的空账本结果误当成当前候选证据，在
`a428edaad5cf70e0c47a5649c5f867ae6aeabdd5` / `20260821060037` / image
`sha256:0b83684e05c77a0371e223f2b3250246307f17f3da7cc626608c29839cf01d7f` 上重新执行了
Django PostgreSQL `default` alias 的纯 `SELECT` 盘点。EVID-02 approval、activation 与
supporting tables 仍全部为 `0` 行，head audit 为 `empty/no-head`，人工审批为
`not_collected`；STRAT-01 的 Research R1–R8 `65` 张表、Portfolio R4/R5/R8 `7` 张表、
四张 Equity baseline 表及 Data Center actual/PIT/macro-factor/market-structure 依赖表也全部为
`0` 行。结构化工件为
[`evid-02-strat-01-vps-readonly-inventory-2026-08-21-head-a428edaad.json`](../deployment/evid-02-strat-01-vps-readonly-inventory-2026-08-21-head-a428edaad.json)，
SHA-256 为 `e93fdcef3591aece3d9d9412a9e58b288e9514a759e3a2fe048d2d85bf56f95b`。

本次没有创建、更新、删除、回填、审批或 rollback；结果只证明当前候选 schema 可读且真实 owner/
approval ledger 为空，不把 Data Center facts 现场提升为 owner evidence。`EVID-02` 继续
`awaiting_production`，`STRAT-01` 继续 `awaiting_production`，`EVID-03`、`STRAT-02/03` 与
Evidence hard gate 继续 fail-closed。

## 2026-08-23：EVID-02/STRAT-01 current candidate read-only inventory refresh

针对当前运行的 `4cef9040cccc2127c3f8128c8d858bc7958df2a4` / release
`20260822134658`，在同一 PostgreSQL alias 内重新执行只读盘点。Account owner-assignment
target tables `9` 张全部为 `0` 行；Research R1–R8 `65` 张表、Portfolio R4/R5/R8
`8` 张表也全部为 `0` 行；明确的 operator/approval/promotion policy tables 仍为空，
`human_approval_status=not_collected`。运行态 health/readiness 均为 `200`，audit health
为 `200/OK`。结构化工件为
[`tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json`](../deployment/tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json)。
SHA-256 为 `7f4e859915e7e0a8399ee75558a12e660b34ef04000f29988291f59d47eaaa55`。

本轮只读盘点没有创建、更新、删除、回填、审批或 rollback；现有 Data Center facts/publications
没有被现场提升为 owner evidence。故 `EVID-02` 与 `STRAT-01` 仍分别为
`awaiting_production`，`EVID-03`、`STRAT-02/03` 与 Evidence hard gate 继续 fail-closed；
真实 owner/definition/policy/calendar/scope、PIT/OOS、canonical receipts、Promotion 与
consumer UAT 仍未具备生产证据。

## 2026-08-23：EVID-01 Research Evidence composition fail-closed 收口

复核发现 Research Evidence API 的默认 composition 只注入 `EvidenceReadFacade`，
staff-only permission 并不等于 artifact 的 owner/tenant scope。现已将
`apps/research/evidence_composition.py` 改为始终构造 `ScopedEvidenceReadFacade`，并注入
一个明确返回 `None` 的 `_UnwiredEvidenceScopeProvider`。在可信、不可变的
authenticated owner/tenant authority provider 接入前，未知 scope 不会触碰 Evidence
repository；API 继续返回稳定的 unavailable/not-found 语义，不会把 staff 身份升级为
owner grant，也不会新增写入或执行能力。

新增 `tests/unit/research/test_evidence_composition.py`，用不接 Django ORM 的 sentinel
repository 验证默认 composition 的 exact selector 在 scope 缺失时 fail-closed，repository
调用次数保持为零；Evidence scope/read/API 相关 focused 回归合计 `58 passed`。生产文件的
增量 mypy regression、debt ceiling、Ruff、Black、isort 与 diff-check 均通过。

这只是本地 composition 安全边界，不能宣称 EVID-01 完成：authenticated user/tenant/owner
authority source、同 alias bundle、人工授权、production provider/rollback 与 PostgreSQL
race 仍缺；VPS 不做重部署，Evidence hard gate 与 decision/execution 总闸保持
fail-closed。CLI/SDK 仍是服务器 API 的传输客户端，AI/provider/tool execution 必须在
服务器端完成，不能要求用户安装本地模型、provider runtime 或凭据。

## 2026-08-23：EVID-01 同 alias scope-source authorized composition contract

在既有 fail-closed composition 之上新增显式
`make_authorized_evidence_read_facade(selector_provider, using)`。它把严格的
`DjangoEvidenceScopeSourceV1Repository`、`GetCurrentEvidenceScopeSourceV1`、
`EvidenceScopeSourceV1Provider` 与 `DjangoEvidenceRepository` 组装到同一个 database alias；
selector provider 只能由外部权威组合注入 server-issued source ID/version/content hash，
composition 本身不读取 request、session、User/Profile 或 tenant mutable rows，也不创建
authority facts。默认 `make_evidence_read_facade()` 仍使用未接线 provider，在 scope 缺失时
于 Evidence repository 之前稳定返回 unavailable。

新增 composition 回归覆盖：默认无 provider 时 repository 调用数为零；注入 selector 后
scope/evidence 使用同一 alias、artifact/hash/时钟精确保留并允许继续到 Evidence read；相关
scope/source/facade/API 回归 `72 passed`，Black/isort/Ruff、增量 mypy 与 diff-check 通过。

该 slice 只完成可注入的同 alias composition contract，不代表 authenticated owner/tenant
lifecycle、selector issuer、atomic multi-source bundle、人工授权、production provider、
PostgreSQL production race/rollback 或 Evidence hard gate 已完成；zero-seed authority 与
全局写入/execution deny 保持不变。CLI/SDK 仍是服务器 API 的薄传输客户端，AI/provider/tool
execution 只在服务器端运行，用户不安装本地 Agent 或模型。

## 2026-08-23：EVID-01 composition candidate CI verification

候选 commit `91b18e0c4fadbd31989b0afd75f1550ea32f3bae` 的 GitHub Actions
`CI Fast Feedback` run `32591510019` 已完成：Python 3.11/3.13 targeted suite、无数据库
TDD suite、增量 Ruff/Black/isort/mypy/debt ceiling、TUI/runtime guards 与静态检查均为
成功；同一候选的 Architecture Layer Guard、Security Scan、Consistency Check 也均成功。

这只是仓库候选的自动化证据，不是生产部署或 authority 证据。authenticated owner/tenant
lifecycle、server-issued selector issuer、atomic multi-source bundle、人工授权、VPS
production UAT、PostgreSQL production race/rollback 与 Evidence hard gate 仍未完成；默认
composition 和所有无 authority 路径继续 fail-closed。CLI/SDK 仍只向服务器传输请求，AI、
provider、tool execution 不落到用户本地。

## 2026-08-23：EVID-01 Research Evidence append 时钟边界加固

只读审计发现两个 append-only Research ledger 仍接受调用方提供的 `recorded_at`，但未用 repository-owned server clock 拒绝未来时间；这会让未来 PIT 行污染后续历史读取。现已在
`apps/research/infrastructure/evidence_scope_source_v1_repository.py` 与
`apps/research/infrastructure/evidence_repository.py` 的 private append store 中加入统一边界：
先校验 repository clock 为 timezone-aware，再要求 `recorded_at <= server_now()`；未来时间抛稳定
Conflict，naive/unavailable server clock 抛稳定 Unavailable，均在任何 ORM insert 前失败，不重写
调用方时间或 hash。公开 PIT cutoff 也复用同一 validated clock。

组件回归新增覆盖 scope-source root future timestamp、Evidence operator/track/envelope 三类
future timestamp、naive/unavailable clock 与零落库；定向 Research component 合计 `20 passed`。
Ruff、Black、isort、增量 strict mypy、full debt ceiling 与 diff-check 均通过。为避免测试依赖完整
项目迁移，Evidence component 使用独立 in-memory SQLite schema fixture；这不构成 PostgreSQL
并发或生产运行证据。

该 slice 只收口 ledger 写入时钟，不新增 owner/tenant/authenticated authority、不伪造 selector
issuer、不实现同 alias Repeatable Read bundle，也不连接 VPS 或生产 writer。EVID-01、Evidence hard
gate、decision/execution 总闸保持 fail-closed；production PostgreSQL race/rollback、authority
lifecycle、provider/UAT、人工 sign-off 仍未完成。CLI/SDK 仍是服务器 API 的薄传输客户端，AI、
provider、MCP/tool execution 均在服务器端，用户不需要安装本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 scope selector authority identity binding

`EvidenceScopeSourceV1Selector` 现在必须携带 server-issued 的
`owner_id/tenant_id/account_id/actor_id`，`EvidenceScopeSourceV1Provider` 在授予 scope 前会将
这组 authority identity 与 exact scope source 逐字段比较；任一替换均稳定返回
`scope source authority selector substitution`，不会进入 Evidence repository。该切片只收紧
后续 authenticated issuer 的 typed contract，不从 User/Profile/session、mutable tenant rows 或
数据库 alias 推导身份，也不创建或回填 authority ledger。

新增 selector authority-substitution 回归；已有 scope/provider/composition focused tests 继续
覆盖 exact source/hash/artifact/PIT 语义。EVID-01、Evidence hard gate、同 alias atomic bundle、
真实 owner/user/tenant lifecycle、production provider、PostgreSQL race/rollback、UAT 与人工签署
仍未完成，默认 composition 和所有无 authority 路径继续 fail-closed。

## 2026-08-23：EVID-01 PostgreSQL actor-authority bundle read contract

新增 dormant Infrastructure composition
`DjangoAccountActorAuthorityInputBundleProviderV3`。它只接受明确的 PostgreSQL
database alias，在同一个外层 `transaction.atomic(using=...)` 中先执行
`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`，再复用现有 authentication-context、
Account-user 与 RBAC 三个 immutable raw-source current reader，按 ID/version/content-hash
selector 投影成 `ExactCurrentActorAuthorityInputBundleV3`。缺表、空 ledger、非 current、
跨 ledger user/actor 不一致、alias/type/hash 替换均 fail-closed；嵌套 transaction、SQLite
和其他 backend 也不被当作 authority snapshot。

该切片没有读取 mutable User/Profile/session/request，没有现场 hash，没有接入 Evidence
composition、HTTP/CLI route 或 production writer，也没有改变 zero-seed authority 状态。
focused unit `7 passed`；Ruff、Black、isort、增量 mypy 与 architecture boundary 均通过。
它只证明本地 PostgreSQL snapshot composition contract，不证明 authenticated owner/tenant
lifecycle issuer、生产 source seed、VPS/PG race/rollback、UAT 或人工签署；EVID-01 与
Evidence hard gate 继续 active/fail-closed。CLI/SDK 仍只向服务器提交请求，AI/provider/
MCP/tool execution 在服务器端，用户不安装本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 owner/tenant authority composition gate audit

对下一步接线进行了只读审计。actor-authority bundle 只封存 authentication-context、Account
user 与 RBAC 三个 immutable raw source，不能投影出 Evidence scope 所需的
`owner_id`、`tenant_id`、`account_id`。仓库当前也没有可验证的 owner/tenant lifecycle issuer、
selector receipt 或 production write route；`PortfolioObserverGrantModel` 等 mutable grant
不能作为历史 authority source，不能被现场 hash 成 Evidence scope。

因此本阶段不新增 scope 映射胶水，也不把 bundle provider 接入 Evidence/HTTP/CLI/Agent route。
默认 composition 继续在 repository 前 fail-closed。下一可解除门禁的证据必须来自同一服务端
生命周期：immutable owner/tenant/scope source、同 alias PostgreSQL 写入与回滚/并发观察、
角色化 UAT 及 owner/reviewer 签署；zero-seed、fake provider、当前 User/Profile/session 或
本地测试不能替代。CLI/API 仍是 B/S 薄传输客户端，AI、provider、MCP 与 Agent 执行均在
服务器端，用户不安装本地模型或 provider 软件。

## 2026-08-23：EVID-01 dormant scope-source winner-first replay

补齐 dormant `IssueEvidenceScopeSourceV1` 的幂等重放顺序：同一事务内先按
`source_id/source_version` 读取并严格恢复 immutable winner；winner 存在时只校验固定身份、状态、
记录时钟与 canonical seals，直接返回历史 winner，不再读取当前 owner/tenant observation 或要求
它仍是 logical head/current。只有没有 winner 的首次签发才读取 owner/tenant observation 两次，检查
漂移后进入 predecessor/CAS append。

新增纯 Application 回归 `4 passed`，覆盖已过期 winner 的历史重放、winner-first 零 observation 读取、
首次签发双读和 observation 漂移回滚。该模块仍是 dormant contract：没有接入 HTTP、CLI、Agent、
Evidence composition、mutable User/Profile/session 或生产 writer，也没有创建 owner/tenant authority
source。EVID-01、Evidence hard gate、production authority/UAT/PG race/rollback 与人工签署继续
fail-closed。CLI/API 仍只向服务器传输请求，AI/provider/MCP/tool execution 在服务器端，用户不安装
本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 scope observation content-hash selector

继续收紧 dormant scope-source issuance command：`IssueEvidenceScopeSourceV1Command` 现在必须携带
server-issued `expected_observation_content_hash`，provider exact-current 读取同时接收并返回该 selector，
Application 在任何 scope Domain 构造、predecessor 检查或 append 前逐项核对 observation ID/version/hash。
同 ID/version 的 authority facts 替换、伪造 content hash、未来/无效 observation 均稳定
fail-closed，不会写入 scope ledger。

生命周期回归更新为 `55 passed`（含 hash substitution、winner-first 与 existing scope read/provider
contract）；增量 Ruff/Black/isort/mypy 与 full debt ceiling 保持通过。该切片仍未创建 owner/tenant
lifecycle issuer，不读取 mutable User/Profile/session，不接 Evidence/HTTP/CLI/Agent 或 production writer；
EVID-01 继续 active/fail-closed。CLI/API 仍只把请求传到服务器，AI/provider/MCP/tool execution 在服务器端，
用户不安装本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 Research scope ledger disposable PostgreSQL concurrency evidence

为补足 Research `EvidenceScopeSourceV1` repository 的数据库竞争证据，在现成的本地
`agomtradepro-tar02-pg` disposable PostgreSQL 16 测试容器中创建了专用空库
`evidence_scope_test_disposable`，并以显式
`AGOM_EVIDENCE_SCOPE_PG_CONCURRENCY_EVIDENCE=1` 与测试数据库 URL 运行
`tests/component/research/test_evidence_scope_source_v1_postgres_concurrency.py`。测试结果为
`3 passed in 66.82s`：空表两个不同 root 只允许一个提交、同一 predecessor 的两个 successor
只允许一个提交、外层异常回滚后 ledger 不留孤儿行。测试库随后已删除，未触碰其他本地数据库。

这只是隔离 PostgreSQL 的 repository/事务合同证据，不能替代 VPS/生产 PostgreSQL、真实
owner/tenant immutable lifecycle、server-issued selector、production writer、生产回滚/RTO、
角色化 UAT 或人工签署；没有部署、回填、审批或生产写入。EVID-01 与 Evidence hard gate
继续 active/fail-closed。CLI/API 仍是 B/S 薄传输客户端，AI、provider、MCP/tool execution
继续在服务器端运行，用户不安装本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 authorized Evidence composition same-alias guard

收紧 `make_authorized_evidence_read_facade()` 的 dormant composition 边界：注入的 selector provider、
`DjangoEvidenceScopeSourceV1Repository` 与 `DjangoEvidenceRepository` 现在都必须暴露
`unit_of_work_key`，且与显式 `using` 精确对应 `django:{using}`。using 非规范、selector provider
缺失/替换或跨 alias 时，在创建任一 repository、读取任何 Evidence 之前 fail-closed；这避免把
两个不同数据库事务的 selector 与 scope/evidence ledger 误称为同一原子组合。

新增 selector alias mismatch 回归；composition/provider/scope/repository focused `77 passed`，
增量 mypy、Ruff、Black、isort、governance、architecture 与 deterministic inventory 检查通过。
该 slice 仍只证明 dormant wiring contract，不创建 authenticated owner/tenant authority、selector
issuer、User/Profile/session 读取或 production writer，不接 HTTP/CLI/Agent，不替代 PostgreSQL
production race/rollback、VPS/UAT 或人工签署。EVID-01 与 Evidence hard gate 继续 active/fail-closed；
CLI/API 仍只把请求发送到服务器，AI、provider、MCP/tool execution 在服务器端，用户不安装本地
Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 scope-source lifecycle unit liveness guard

将同一 unit-of-work 约束从 constructor-time 扩展到 lifecycle 执行期间：Application 记录 provider
与 repository 的 canonical `unit_of_work_key`，并在 execute 入口、进入 repository-owned `atomic()`
后、server cutoff、winner/head/observation 每次关键读取之间、source append 前后逐次重验。运行期间
出现 alias/unit 替换、空白或非规范 key、provider/repository 重新绑定，都会以稳定 unavailable 失败；
append 后发生漂移也必须让外层事务回滚，不能留下孤儿 scope row。

新增构造边界、execute 前漂移、读取间漂移和 append 期间漂移/回滚回归；Research
lifecycle/application/provider/composition/repository focused `76 passed`，增量 mypy、Ruff、Black、
isort、governance 与 architecture 检查保持通过。该 slice 仍只证明 dormant transaction-identity
contract，不创建 owner/tenant authority，不读取 User/Profile/session，不接 HTTP/CLI/Agent 或生产
writer，不替代 PostgreSQL production race/rollback。EVID-01 与 Evidence hard gate 继续
active/fail-closed；CLI/API 仍只把请求传到服务器，AI、provider、MCP/tool execution 在服务器端，
用户不安装本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 scope-source repository winner read port

补齐 dormant scope-source lifecycle 与 Django repository 之间的 typed seam：
`DjangoEvidenceScopeSourceV1Repository.get_winner()` 现在先执行完整 ledger restore/chain 校验，再按
`source_id/source_version` 和 `recorded_at <= as_of` 返回 immutable 首赢家；它不检查 validity TTL，
也不把 successor/final head 当成 winner，不会在历史重试时回退到其他 active 行。重复 identity、未来
row、损坏或断链仍在 selector 前 fail-closed。

新增 isolated component 覆盖 root+successor、过期首赢家历史重放和 head 不回退，repository focused
回归 `10 passed`。该修复只完善 dormant read/append contract，未接 owner/tenant lifecycle issuer、
mutable User/Profile/session、Evidence/HTTP/CLI/Agent route 或 production writer；EVID-01 继续
active/fail-closed，CLI/API 仍只向服务器传输请求，AI/provider/MCP/tool execution 在服务器端。

## 2026-08-23：EVID-01 scope-source lifecycle same-unit guard

在 dormant scope-source lifecycle 构造阶段增加同一服务端 unit-of-work 约束：观察 provider 与
append repository 都必须暴露非空 `unit_of_work_key`，且必须精确相等；缺失、类型替换或 alias
不一致都会在任何观察读取、head 查询或 append 前失败关闭。Django store 使用其 database alias
作为该 key，纯 Application fake 也必须显式声明测试 unit，避免把两个独立事务误称为原子
owner/tenant observation。

新增 alias mismatch 回归；scope lifecycle/application/provider/repository focused 回归 `71 passed`，
Ruff、Black、isort、增量 mypy 与 diff-check 通过。该 guard 只证明 dormant composition 的事务边界
合同，不创建 owner/tenant authority，不读取 User/Profile/session，不接 HTTP/CLI/Agent 或生产 writer，
不替代 PostgreSQL production race/rollback。EVID-01 与 Evidence hard gate 继续 active/fail-closed；
CLI/API 仍只向服务器传输请求，AI、provider、MCP/tool execution 全部在服务器端，用户不安装本地
Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 scope-source lifecycle Django append seam

将私有 Django scope-source store 对齐 dormant Application lifecycle 的 typed append 端口：支持
`expected_predecessor_hash` 与 `recorded_at`，在同一 repository-owned UOW 内解析并校验完整 ledger
中的 predecessor，要求记录时钟与 canonical source 一致且不晚于 server clock；旧的显式
`append_root/append_successor` 测试/组合入口继续保留为兼容 shim。store 同时提供 lifecycle 所需的
validated `now()`，因此 `IssueEvidenceScopeSourceV1` 可以在隔离 Django store 上真实走 root、successor、
CAS 与 winner-first replay，而不是落到 fake repository。

隔离 component 回归 `12 passed`；Research lifecycle/application/provider/composition 与 repository
组合回归 `70 passed`；Ruff、Black、isort、增量 mypy、full debt ceiling、governance consistency、
architecture delta 与 diff-check 均通过。该 slice 仍是 dormant/local SQLite contract：没有 owner/tenant
authority source、production selector issuer、HTTP/CLI/Agent route、mutable User/Profile/session 读取、
生产 writer、VPS 部署、PostgreSQL production race/rollback 或人工签署；EVID-01 与 Evidence hard gate
继续 active/fail-closed。CLI/API 仍只向服务器传输请求，AI、provider、MCP/tool execution 在服务器端，
用户不安装本地 Agent、模型或 provider 软件。

## 2026-08-23：EVID-01 expired final predecessor successor policy

修正 dormant scope-source lifecycle 的 predecessor policy：最终 head 只需在当前 PIT 已知、
且状态仍为 `active`，即可作为新 successor 的 CAS predecessor；它是否已超过自身
`valid_until` 不再阻断新的 owner observation 写入。`revoked` 仍是 terminal，future head 仍
fail-closed，current read 仍由 final-head 与 temporal TTL 单独决定，不会回退到旧 active row。

新增 active-but-expired final-head successor 回归；lifecycle focused tests `7 passed`，Ruff、Black、
isort、增量 mypy regression 通过。该修正只澄清历史链续接与 current-read 的分离，不创建或回填
owner/tenant authority，不接 User/Profile/session、HTTP/CLI/Agent 或生产 writer；EVID-01 继续
active/fail-closed，CLI/API 仍只向服务器传输请求，AI、provider、MCP/tool execution 在服务器端，
用户不安装本地 Agent、模型或 provider 软件。
