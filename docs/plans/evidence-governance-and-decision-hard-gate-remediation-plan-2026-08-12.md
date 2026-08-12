# AgomTradePro 证据治理与决策硬闸改造计划

> 执行状态（2026-08-13）：**M0 进行中，外部写面、Transition Plan 内部 writer、65 个显式高风险输出及 18 个动态 query/GET/presenter 面已冻结；M1 Domain、append-only persistence、staff-only exact read API、Operator Spec lifecycle、Risk Center approval provider、Research↔Risk read composition、人工 subject/审批写入面代码与首批 legacy adapters 已完成**。当前工作分支为 `dev/plan-closure-by-priority`；归档与排期基线提交为 `919a9cea7`。本状态只证明下列已列出的仓库交付，不代表用户/租户 owner-scoped API、写入面的完整项目 runtime/component 证明、其余 App 输出 adapter、TUI、Portfolio、Broker 或生产硬切换已经完成。

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
