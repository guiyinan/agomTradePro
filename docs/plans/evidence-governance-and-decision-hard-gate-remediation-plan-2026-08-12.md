# AgomTradePro 证据治理与决策硬闸改造计划

> 执行状态（2026-08-13）：**M0 进行中，M1 Domain、append-only persistence、staff-only exact read API、Operator Spec lifecycle、Risk Center approval provider、Research↔Risk read composition、人工 subject/审批写入面代码与首个 Data Center legacy adapter 已完成**。当前工作分支为 `dev/plan-closure-by-priority`；归档与排期基线提交为 `919a9cea7`。本状态只证明下列已列出的仓库交付，不代表用户/租户 owner-scoped API、写入面的完整项目 runtime/component 证明、其余 App 输出 adapter、TUI、Portfolio、Broker 或生产硬切换已经完成。

## 0. 分阶段实施记录

### 2026-08-12：M0 基线与 M1 Domain / persistence 首批

已完成：

- 在独立 `dev/plan-closure-by-priority` 分支开始实施，并把完成计划归档、活跃计划优先级和索引修正作为独立基线提交。
- 新增 [`ADR-0007`](../architecture/adr-0007-evidence-envelope-and-decision-gates.md)，明确 Research、Data Center/Signal、Risk Center、Portfolio、Broker Execution 与 TUI 的 owner/接口矩阵，以及决策写入口冻结原则。
- 新增 `governance/decision_write_surfaces.json` 与机器门禁，冻结 54 个 Decision Rhythm、Portfolio、Broker Execution、Simulated Trading、Strategy HTTP 写入口、15 个 SDK 写方法、25 个发布态 TUI 决策流 action、23 个发布态 mutation/AI/admin action，以及 32 个可能影响决策或仓位的 MCP 写能力；发布图 SHA 漂移、新增旁路或陈旧登记均阻断。
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
- 未验证：完整项目 DRF/API/component、DRF 项目级 mypy、PostgreSQL 并发。module dependency budget 仍报告当前分支总边 `208 > 207`（Research outbound 与 Risk Center inbound 各 +1），未形成实际 cycle，需在后续 composition 边界治理中收口。

仍未完成：

- M0 尚需扩展全量 R1–R8、动态 dict/TypedDict/interface/query payload、Broker query API、raw/governed MCP 输出语义与旧 Transition Plan 写路径分类；owner/接口矩阵、HTTP/SDK/TUI/MCP 写入口及 41 个高风险输出首批冻结已完成。
- M1 的用户/租户 scope 模型与 owner-scoped 授权、人工审批写入面的完整项目 runtime/component 证明、并发 first-winner PostgreSQL 验证和其余 App Application adapter仍未完成；staff-only exact read API、Operator Spec lifecycle、Risk Center approval provider、Research↔Risk read composition、人工 subject/审批写入面代码与 Data Center quote legacy adapter 首批已完成。
- M2–M5 全部交付及真实生产切换证据。

本阶段验证：

- `python scripts/check_decision_write_surface_freeze.py`：通过，HTTP `54`、SDK `15`、TUI decision `25`、TUI mutation `23`、MCP position-write `32`。
- `python scripts/check_evidence_output_surfaces.py`：通过，outputs `41`、direct-position `11`、marker-discovered `32`；纯 Python `5 passed`，standalone strict mypy `0 errors`。
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
