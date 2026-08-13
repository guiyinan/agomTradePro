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
