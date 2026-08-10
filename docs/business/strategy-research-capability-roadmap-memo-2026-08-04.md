# 策略研究能力后续开发备忘（2026-08-04）

> 状态：长期能力备忘，不是当前实施承诺
> 复核触发：情景治理 Quick Wins 完成、相关数据达到 Publication/PIT 门禁、或投资主任务发生变化时
> 适用版本：0.8.0 之后
> 来源边界：本备忘依据用户对四份策略会材料的摘要和当前仓库能力盘点编写，未读取原始 PDF。
> 关联实施计划：[情景治理与策略研究 Quick Wins 整改计划](../plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md)
> 2026-08-05 启动门复核：R1—R8 均为 `blocked`；已交付统一 fail-closed readiness 合约和分阶段计划，但未启动任何模型、数据回填或用户任务。
> 2026-08-05 开发续批：已实现 R1/R2 治理定义与 PIT 数据入口、R7 情景预测账本绑定、R8 research-only 输入合约及运行时 owner 取证；这些基础纵切不替代真实数据、样本外验证或 PromotionDecision，能力总门禁保持不变。
> 2026-08-05 无数据先行批次：已实现 R1 三情景经营预测与误差台账、R5 research-only 固收研究内核、R6 简单基准不足取证器，以及 R8 canonical portfolio snapshot/执行反馈台账；真实 Publication、外部对账、样本历史和晋级版本仍缺失，因此 R1—R8 总门禁不变。
> 2026-08-05 研究基础收口批次：进一步实现 R1 行业模板安全计算、R2 市场结构证据、R3 独立宏观因子研究 App、R4 宏观风险候选验证、R6 外部高级状态证据门禁、R7 校准/类比/路径研究和 R8 受约束确定性研究优化。所有结果保持 research-only；fixture、模型文件或迁移存在均不作为生产 ready 证据。
> 2026-08-05 Luna Max 交叉复核整改：三组独立只读复核未发现 P0，并提出的 13 项 P1 已全部关闭；整改覆盖 PIT 事实身份、双时间查询、coverage、固收输入封存、简单基准绑定、情景样本/路径身份、Portfolio snapshot owner 证据及优化风险贡献重算。该整改提升证据不可篡改性，不改变 R1—R8 的 `blocked` 结论。
> 2026-08-05 完整路线图审计：上述 13 项仅代表上一轮限定清单关闭，不代表 R1—R8 完成。新一轮按目标/最低验收逐项审计未发现 P0，但确认仍有多项无数据可开发 P1；本批新增 R5 组合风险预算/压力测试并加固 R4 report seal，完整队列见[完成度审计](../plans/strategy-research-capability-completion-audit-2026-08-05.md)。
> 2026-08-05 R1/R2 无数据续批：R1 已完成 Sector→Equity 持久证据桥接、通用 driver PIT 绑定、cash-flow/六阶段/template-run seal 及 legacy dual-read；R2 已完成版本化 expected-period calendar、series×period 完整 coverage 和整期全缺 fail-closed。该批当时尚未完成 R1 baseline/Promotion exact binding，已由 2026-08-06 续批关闭软件 P1；R2 真实 taxonomy/calendar/两个市场周期证据仍未完成，能力门禁保持 `blocked`。
> 2026-08-05 R7 reminder 续批：已完成 Research-owned append-only reminder ledger/internal outbox，修复 invalidation reminder 确定性时间锚，精确绑定 forecast/revision/policy 与逐期 conditional/transition evidence，并实现 due/ack/escalate/expiry。该流程只允许内部人工 pull/ACK，禁止外部发送、自动审批和执行；真实 outcome 历史、获批 sample policy、结果持久化与晋级仍未完成，R7 保持 `blocked`。
> 2026-08-05 R3 runner 续批：已完成 exact-PIT historical-mean/FMP、nested temporal-CV runner、可回读 canonical artifact bytes、dated current/forward ledger 与 append-only retirement lifecycle。每 fold 独立 selection，outer OOS 不参与选择，late revision/available-at/split/purge/embargo 均 fail closed。真实宏观 vintage、代理价格、benchmark/cost、regime/OOS trial 与 Research exact Promotion binding 尚未形成，R3 仍保持 `blocked`。
> 2026-08-09 R3 concrete fitting 续批：已在 Infrastructure 落地 sklearn 标准化/Lasso 与 OLS refit，严格复用既有 PIT design、nested temporal-CV 和 artifact/ledger 语义；预登记 alpha、逐 inner-fold 选择、outer-OOS 隔离、标准化参数、intercept、系数/权重、显著性/BIC/调整 R²及 benchmark/cost identity 全量封存，来源明确为 `infrastructure_concrete_fit`。Production composition 缺 canonical manifest/dataset/config/repository 时稳定 blocked 且零写；真实数据、owner policy、Regime/OOS trial、Promotion/current/decision/execution 仍缺，R3 保持 `blocked`。
> 2026-08-06 R8 治理续批：已完成 13 类 typed 数值输入、当前配置基准、可投资 universe、A 股/基金/债券/商品约束、逐期 path drawdown、四候选可复算比较，以及 append-only result/Promotion/retirement/rollback lifecycle。输入组装和生命周期均从 canonical provider 精确回读，完整证据图使用 Decimal/UTC canonical hash；无法在 weight 层证明数量约束时稳定阻断。真实 R3/R4/R5 Promotion、Portfolio snapshot、broker reconciliation、成本/容量和市场规则校准仍未形成，因此该能力仅为 research-only 软件切片，R8 保持 `blocked`。
> 2026-08-09 R8 readiness/composition 收口：`portfolio_canonical_snapshot` 已从机制 attestation 移除，class/repository 存在不再把真实 snapshot 条件标为 `verified`；四候选 fail-closed policy 改由 Portfolio owner attested。Production composition 现可构造，但 canonical input-set、Research exact Promotion 和 Portfolio lifecycle authorization source 在未接线时显式 unavailable，且在 repository 写入前阻断。`portfolio.0006` 只有 result/lifecycle 台账，独立 input receipt/provider 仍为后续 P1；真实数据门不变，R8 保持 `blocked`。
> 2026-08-09 R2 trial/monitoring 续批：已完成 selection 前预注册、taxonomy/calendar Publication 精确投影、两个完整市场周期 PIT manifest、Audit 因果时钟、Holm-v1 现场重算及解释力监控纯 Domain/Application 合同。Coverage、stability 与 `delta_r2` 均从 canonical denominator/raw facts 派生，缺期间、替换、未来/过期、选择泄漏和旧期间时钟洗白均 fail closed；输出固定 descriptive/research-only，禁止 predictive signal/current/decision/execution。真实 Publication、两个市场周期 outcome 与 owner provider 仍缺，R2 保持 `blocked`。
> 2026-08-09 R6 monitoring Phase B：Research `0011` 新增 observation/assessment 两张 schema-only append-only ledger，保留 owner observation clock 并另设 server-clock ledger clock；ID-only UoW 在同事务重读 qualification、policy、完整 period calendar 与 raw facts后现场复算，strict codec、PIT query、cursor、row-header seal、first-winner/fork/rollback 与常规 ORM/Collector 防绕过均已覆盖。该能力不自动 RETIRE、不激活模型、不替换 Regime、不发布 current/decision/execution；真实 monitoring facts、owner authorization 与 approved Promotion 仍缺，R6 保持 `blocked`。
> 2026-08-09 R8 input receipt Phase B：Portfolio `0009` 新增独立 canonical input receipt，完整封存 13 类 typed payload、owner graph、universe/snapshot/PIT 与 R3/R4/R5 Promotion；新 result v2 精确封存 receipt ID/hash/schema，旧 null-receipt result 仅允许显式 legacy research read。ID-only registration、nested-savepoint first-winner、计算后 receipt/Promotion 二次重读和 runtime writer 隐藏均已收口；production 因真实 owner providers 未接入继续显式 blocked，无 seed/backfill，R8 仍保持 `blocked`。
> 2026-08-09 R3 inference chronology 收口：runner 不再把带历史 label 的 outer-OOS 行包装成当前/未来输出；新增 manifest-bound、无 target label/value 的独立 inference row、authoritative calendar member/full content seal 与版本化 input-freshness policy。Final fit 只对该 inference proxy row 预测，knowledge cutoff 精确等于 manifest as-of，request/artifact 同时封存 inference identity、period、calendar 和 freshness；缺 inference、未来/过期时钟、owner 替换、runner 引用漂移或 external artifact 篡改均在写 ledger 前阻断。真实宏观 vintage、代理资产、target calendar owner、OOS trial 与 Promotion 仍缺，R3 保持 `blocked`。
> 2026-08-09 R6 activation Phase A：新增独立 Research Domain/Application activation contract，在 exact qualification、健康且新鲜的 monitoring、approved Promotion 与 owner authorization 全部动态重读后，才允许记录 internal ACTIVATE/RETIRE/ROLLBACK；rollback 只能回到 `stack[-2]`。Authorization 精确绑定前一 event hash，幂等 winner 必须完整重放 canonical stream，所有结果固定 research-only 且禁止 Regime/current/decision/execution。尚无 activation ORM/codec/UoW persistence、canonical owner adapter 或 consumer，真实证据门不变，R6 保持 `blocked`。
> 2026-08-09 R8 receipt DB integrity 收口：Portfolio `0010` 仅允许 legacy `v1 + NULL receipt` 或 canonical `v2 + receipt`，并精确限制 receipt contract v1；未知/空白版本升级或写入均原子失败。`0009` 逆迁在检查前阻断 PostgreSQL/SQLite 并发写，存在 v2/receipt evidence 时拒绝删 FK/receipt 表并保全数据。该 schema-only 纵深不 backfill、不生成 owner evidence；真实 provider、snapshot、reconciliation 与 R3/R4/R5 Promotion 仍缺，R8 保持 `blocked`。
> 2026-08-09 R3 runner contract integrity 收口：`MacroFactorRunnerSpec` 新增全字段 canonical seal，execution request 精确封存完整 target/candidate、split、benchmark、cost、reproducibility、freshness 与 validity 语义；manifest factory 在聚合前现场重验 calendar member/slice。所有版本、期间、样本数、seed、age、iteration 与 artifact length 采用 exact built-in `int`，float/bool/int-subclass、同 code 语义替换和 runner 引用漂移均 fail closed。Temporal-CV contracts 与 runner spec 已拆成独立纯 Domain 模块，Macro Factor unit `133 passed`；真实 owner manifest、PIT 数据、trial 与 Promotion 仍缺，R3 保持 `blocked`。
> 2026-08-09 R6 activation Phase B：Research `0012` 新增 authorization、event、stream commit anchor 与 audit snapshot 四张 schema-only append-only ledger。Event stream 强制双时钟单调、scope identity/hash 双唯一序列、authorization↔event↔commit 三方完整性、server-ledger knowledge cutoff、projection seal、signed immutable audit snapshot；strict codec、row/FK/header replay、private ORM/Collector guard、race/rollback、单侧或成对尾删、alias/tamper 均 fail closed。Production mutation/audit façade保持 inert，公开对象图不保留 store/token；真实 owner adapters 与 consumer 仍未接入，R6 保持 `blocked`。
> 2026-08-09 R8 production registration façade：Portfolio runtime 新增无状态 ID-only registration façade；在真实 canonical input-set、13-owner graph、universe、snapshot 与 Research Promotion provider 尚未接入时，合法或畸形命令均在任何写能力可达前稳定 unavailable。Facade 不持有 writer、UoW、provider、clock 或 closure，receipt/result/lifecycle 保持零写；R8 总门禁不变。
> 2026-08-09 R3 authoritative runner-spec 收口：runner command 不再接收调用方构造的完整 spec，只携 spec/manifest/freshness identity；Application 必须从 Research-owned provider 精确重读完整 spec，现场重验 canonical seal 与 selection 前 `registered_at`。同 identity 语义替换、缺失、畸形、未来或迟注册均在 runner/ledger 前稳定阻断。现有通用 Research Registry 不能无损重建完整 spec，因此 production composition 保持 fail-closed，不伪造 adapter；R3 总门禁不变。
> 2026-08-09 R4 post-promotion monitoring Phase A：新增纯 Domain/Application 的版本化 monitoring policy、连续完整 period calendar、11 类 owner raw facts 与 assessment。完整期间出现连续 breach、label/data drift 或陈旧/替换证据时输出人工 `RETIREMENT_REVIEW_REQUIRED`；所有阈值和方向均封存，freshness 绑定 canonical period end，Application 只接收 identity/as-of 并在 shared UoW 内精确重读 active decision、Portfolio result、R3 attestation 与 owner facts。该切片不自动 RETIRE、不持久化、不发布 current/decision/execution；真实 owner facts 与 Promotion 仍缺，R4 保持 `blocked`。
> 2026-08-09 R8 lifecycle 事务治理收口：lifecycle command 改为严格 ID-only，result、canonical stream、Research Promotion 与 Portfolio authorization 必须在同一 UoW 内双次精确重读；event 时钟由 repository trusted server clock 产生，selector 替换、owner retire-between、UoW 漂移、fork/race 与异常均在写入前归一化阻断。Repository 不再公开 append 能力，existing winner 必须锁 result 并完整重放 stream；production runtime 对象图不保留 repository/store/token。真实 owner provider 与 optimization monitoring 仍缺，R8 保持 `blocked`。
> 2026-08-10 R4 monitoring Phase B：Research `0013` 新增 observation、assessment 与 immutable audit snapshot 三张 schema-only ledger，zero seed。Identity/as-of-only writer 在同一数据库 UoW 内重读 Phase A 六个 owner provider并现场复算，owner/server 双时钟、payload/header/FK 与 PIT cutoff 均封存；exact query、first-winner/fork/rollback、常规 ORM/Collector guard 和确定性签名 cursor 均 fail closed。Production runtime 不暴露 store/token，真实 owner providers 未接入时 register/audit 保持 unavailable；不自动 RETIRE、不发布 current/decision/execution，R4 仍为 `blocked`。
> 2026-08-10 R8 post-promotion monitoring Phase A：新增版本化 policy、完整连续 calendar、11 类 Portfolio/Broker owner metric payload 与 assessment，精确绑定 active result、receipt、R8 lifecycle Promotion 及 R3/R4/R5 Promotion。Application command 只携 policy identity/as-of，按 policy target 在 shared UoW 内双次重读 owner graph；连续 breach 或历史 label/data drift 只产生人工 `RETIREMENT_REVIEW_REQUIRED`，历史普通 breach 恢复后可回到 healthy。Source payload 替换、未来/过期/缺期间、receipt 时钟和 UoW 漂移均阻断；固定禁止 current/decision/execution 与自动 retirement。无 persistence/composition/真实反馈，R8 保持 `blocked`。
> 2026-08-10 R5 post-promotion monitoring Phase A：新增独立 Portfolio raw projection、canonical owner role/knowledge clocks、完整连续 calendar、7 项现场派生指标与四态 assessment。Coverage、超额净收益、回撤增量、总成本、流动性 breach、容量利用与信用损失只能由封存的分子/分母重算；policy 精确绑定 active decision、FI result、benchmark、cost/liquidity/label/schema owner graph。Application command 只携 policy identity/as-of，并在 shared UoW 内双次重读；连续 breach/历史 drift 仅生成人工 review，禁止 current/decision/execution 与自动 retirement。无 persistence/composition/真实数据，R5 保持 `blocked`。
> 2026-08-10 R8 monitoring Phase B：Portfolio `0011` 新增 assessment-scoped observation、assessment 与 immutable audit snapshot 三张 schema-only ledger，zero seed。Writer 在同 DB UoW 内锁定并重读 result/receipt/lifecycle 与 Phase A owner graph，existing winner 在取得新 server clock 前按完整 Domain evidence重放，支持跨时钟幂等；相同 raw facts可被不同 policy assessment合法复用。Production builder固定 Django server clock，exact PIT、signed cursor、fork/rollback、ORM/Collector guard与正反迁移均有回归。真实 owner providers仍 unavailable，不自动 RETIRE或接入 execution，R8 保持 `blocked`。
> 2026-08-06 R1 精确基线与晋级续批：已完成强制 owner approval 的 baseline spec 合同、forecast/baseline/actual manifest 精确封存、完整 period×metric 配对评估、预注册 trial，以及 Research-owned exact PromotionDecision、retirement/rollback 生命周期。Research 在运行时通过 Equity Application port 重读完整 artifact/template-run/sensitivity/trial seal，调用方不能用 decision id 或自报 hash 解锁；五张新表均为 append-only、schema-only、零 seed。真实 owner approval、QW-7 反馈、连续经营事实、财务/估值 Publication 和真实 trial 仍未形成，且未接 Valuation 消费，因此 R1 保持 `blocked`。
> 2026-08-06 R4 rolling 研究续批：已完成 typed walk-forward/embargo、formation-time Regime PIT assignment、rolling beta/CI/R²/残差/稳定性汇总，以及等权、资产风险平价、宏观因子风险平价三方法同窗 OOS 比较。Application 只接受 study identity，并通过 authoritative provider 重读 exact R3 Promotion attestation；协方差、OOS path、source projection、派生 summary 和完整 artifact 均逐值复算、全字段 seal，缺证据或时间穿越稳定 blocked。该批未新增 ORM、Promotion lifecycle、current/组合预览或执行接线；真实 R3 晋级、资产/因子输入和历史样本仍缺失，因此 R4 保持 `blocked`。
> 2026-08-06 R4 持久证据续批：已完成 Portfolio-owned append-only input receipt/result ledger、schema-only `0007` migration、canonical typed codec、factory replay、server-clock/UoW 写入保护与 exact PIT Application query。协方差 evidence 进一步封存 condition number、rank、expected/missing observation denominator 和 missing-value policy，并由版本化 condition/coverage 阈值稳定阻断；所有 bulk/direct mutation、caller self-attestation、非 canonical UTC payload、并发冲突和 raw tamper 均 fail closed。Research Promotion/retirement/rollback lifecycle 仍未实现，R4 继续保持 `blocked`。
> 2026-08-06 R4 Promotion Phase A：已完成 Research-owned stable semantic scope、selection 前预注册 policy、Portfolio/current-R3 exact trial seal、派生 gates/outcome/validity、ID-only decision/lifecycle Application、scope-local Promotion/retirement/rollback stack 与 active provider。Rollback 只能逐层回到 `stack[-2]`；active 每次 PIT 重放并动态重读 policy、Portfolio record 与 current R3，RETIRE 可按 decision-time 历史 PIT 清理已失效栈顶。该批仅为 Domain/Application 软件合同，五张 append-only Research 表、migration、concrete provider/composition 与下游 active 接线仍未实现，R4 保持 `blocked`。
> 2026-08-06 R4 Promotion Phase B：已完成 Research policy、decision receipt/bundle、lifecycle authorization receipt/event 五张 append-only 表、schema-only `0004`、strict typed codec、server-clock registration draft、private UoW/insert claim、concrete repository/providers/composition，以及 exact PIT active replay。Portfolio 只经 Application exact query 注入；并发 first-miss 只重放完整一致 winner，fork、异证据、raw tamper、direct/bulk/related-manager 绕过和 receipt→child 失败均 fail closed。该批仍不接 consumer/current/execution；真实 R3 晋级、canonical inputs、owner authorization 与真实 trial 未形成，因此 R4 保持 `blocked`。
> 2026-08-06 R5 relative-value Phase A：已完成 PIT 历史利差分位、评级迁移五桶矩阵、流动性溢价/成本分解、signed curve/key-rate/steepener/flattening/butterfly/credit-spread 组合、逐腿容量/流动性/shortability/cash/risk 门禁及四组件 composite。Application 命令只收 ID/version/cutoff，逐项重读 Publication、BondMaster、CashFlow、Calendar 和 nested owner exact seals；Data Center 只拥有 raw facts，fixed_income 拥有 analytics/candidate/input set，Portfolio 拥有 funding，Research 拥有 policy。该批无 ORM/migration/concrete provider/UoW/Promotion/consumer/执行；真实 Publication、PIT 样本、容量/借券与外部对账仍缺失，R5 保持 `blocked`。
> 2026-08-07 R5 relative-value Phase B1：已完成 fixed_income-owned input receipt/result 两表 append-only audit ledger、schema-only `0003`、strict typed codec、server-clock `recorded_at`、完整历史 evidence clock graph seal、跨 Data Center/Portfolio/Research Application UoW 与 exact PIT query。公开 Repository 仅可读，写入闭包只接受 ID-only command 并在同一事务内权威重读 Phase A owner graph；caller Draft、自选 capability、command/draft 错配、direct/bulk/related mutation、race fork、回滚失败和 raw header/payload/FK 篡改均 fail closed。该批仍无 Research Promotion/retirement/rollback、consumer/current/执行接线；真实 Publication、PIT 样本、容量/借券与外部对账仍缺失，R5 保持 `blocked`。
> 2026-08-07 R6 qualification evidence：已完成预注册 family/split/embargo、同窗 transition/log-loss/calibration/duration/decision-loss/complexity/label-stability 七指标比较、政策反应系数与回归诊断，以及 ID-only authoritative qualification。Study 使用完整 body hash 派生稳定 ID；S2 attestation 强制重放 PIT manifest、外部 artifact attestation 与 acceptance threshold gate，三项额外派生指标由独立 exact bundle 重读；通过只表示 `EVIDENCE_COMPLETE`、可送人工晋级复核，不能生成 PromotionDecision、替换 Regime 或进入决策。真实 simple-baseline shortfall、PIT/OOS 样本、稳定标签和政策目标仍缺失，R6 保持 `blocked`。
> 2026-08-07 R2 Publication/Promotion 续批：Data Center 已完成 taxonomy actor/series 与 period-calendar 的 Canonical Publication/member 精确门禁和 attestation；Research `0009` 建立 policy、decision、PROMOTE/RETIRE/ROLLBACK 三本 append-only ledger，ID-only/shared-UoW/PIT active replay 动态重读 owner policy、Publication evidence 与 authorization。R2 unit `24 passed`、Data Center component `6 passed`、Research component `2 passed`、migration `2 passed`；无 seed、无 current/consumer/execution 接线。真实 taxonomy/calendar Publication、两个市场周期和 owner policy/authorization 仍缺，R2 保持 `blocked`。
> 2026-08-07 R6 qualification persistence/lifecycle 续批：Research `0008` 建立 assessment、lifecycle authorization、lifecycle event 三本 schema-only append-only ledger；ID-only exact PIT 注册/读取/审计分页与 PROMOTE/RETIRE 生命周期在 shared-UoW 内动态重读 assessment、owner authorization，退休终态且不替换 Regime、不产生决策或执行。新增 persistence/lifecycle unit/component-style 回归 `14 passed`；真实 shortfall、PIT/OOS、stable label、owner authorization、monitoring 和 approved Promotion 仍缺，R6 保持 `blocked`。
> 2026-08-07 R3 governed read 续批：新增 exact regime assignment、OOS segment、pre-registered trial family、Promotion authorization 与 monitoring raw-fact 重放；读取只接受 artifact/output identity 与 PIT cutoff，分段指标和监控按 canonical evidence 现场复算，缺项、篡改、到期、退役或失效规则均 fail closed。Governed-read `10 passed`，连同 runner/ledger regression `36 passed`；无 ORM/migration/API/TUI/Celery/current/执行接线。真实宏观 vintage、代理资产、Regime assignment、OOS trial、owner authorization 与 approved Promotion 仍缺，R3 保持 `blocked`。
> 2026-08-07 R5 Promotion Phase A：已完成 Research-owned content-addressed scope/policy/trial/decision/lifecycle contract。Trial 同时绑定 fixed_income B1 exact result 与独立 Portfolio outcome owner seal，逐观察重读 OOS return/cost/drawdown/liquidity/capacity/credit-loss；decision authorization 精确绑定 decision/record/validity clocks。Lifecycle Application 只收 ID，按完整 stream 执行 PROMOTE/RETIRE/ROLLBACK（rollback 只能 `stack[-2]`），active 每次 PIT 动态重读 policy、trial、FI、Portfolio 和 authorization，任一缺失/替换/过期即 fail closed。该批无 ORM/migration/concrete repository，仍不接 R8/current/执行；真实 Publication、OOS outcome、owner authorization 与 approved trial 未形成，R5 保持 `blocked`。
> 2026-08-07 R5 Promotion Phase B2a：已完成 Portfolio-owned relative-value outcome append-only ledger、schema-only `portfolio.0008`、strict codec、server-clock/UoW writer 与 exact PIT owner query。Portfolio 不新增跨 App ORM FK；写入只收 ID/version/cutoff，并在同一事务内经 fixed_income Application exact query 重读 result、owner seal 与 observation；重复 observation、direct/bulk/related mutation、race/rollback/raw header-payload tamper 均 fail closed。该批仍不接 R8/current/execution；真实 OOS outcome、Publication、容量/借券、owner authorization 与外部对账缺失，R5 保持 `blocked`。
> 2026-08-07 R7 approved sample policy：已完成 Research-owned approval receipt + scope-bound policy 两表 append-only ledger、schema-only `research.0005`、strict canonical codec、server-clock registration、owner Application port/concrete adapter、shared UoW 与 exact PIT active replay。UUID/clock/header/payload/reference tamper、scope-policy 语义矛盾、direct/bulk/save_base/delete、same-identity/race/rollback 均 fail closed；production composition 在 Risk Center owner source 尚未接入时固定返回 unavailable，测试 fake 只在私有 test factory 中可注入。Unit/component/migration `8/12/4 passed`；真实 forecast/outcome history、Risk Center approved audit、calibration evidence 与 Promotion 仍缺，R7 保持 `blocked`。
> 2026-08-07 R5 Promotion Phase B2b：已完成 Research-owned policy/trial artifact、decision authorization/bundle、lifecycle authorization/event 五张 append-only ledger 与 schema-only `research.0006`。Artifact registration、decision/lifecycle receipt→child 均为 shared-UoW、server-clock、ID-only closure；fixed_income 与 Portfolio owner graph 逐项 exact reread，PIT future cutoff、raw selector hiding、stream fork、race/rollback 与 append-only bypass 均 fail closed。修复后 B2b component `4 passed`，codec+migration `6 passed`；真实 approved trial、OOS outcome、owner authorization、Publication 与外部对账仍缺，R5 保持 `blocked`。
> 2026-08-07 R7 calibration/analogy/path result persistence：已完成 Research-owned 完整 evidence graph、input receipt/result 两层 append-only ledger 与 schema-only `research.0007`。ID-only writer 在 shared UoW 内重读 approved sample policy、Forecast observation、历史类比与路径证据，现场重算 calibration/analogy/path assessment；result 固定 research-only、禁止训练/概率发布/决策/执行，exact PIT/future cutoff、strict typed codec、header/payload/transition tamper、append-only、race/rollback 均 fail closed。Unit/component/migration `4/7/3 passed`；真实 owner evidence、forecast/outcome history、Risk Center approved source 与 Promotion 仍缺，R7 保持 `blocked`。

> 2026-08-07 R7 result retirement/Promotion lifecycle：已在 `research.0007` exact result 上完成 Research-owner authorization、lifecycle event 与 audit snapshot 三本 append-only ledger、schema-only `research.0010` 与独立 production composition。Apply 只接受 result/action/authorization identity，并在同一数据库 UoW 重读 exact owner authorization 和 PIT result；Promotion 仅表示内部研究记录晋级，退休为终态，始终禁止概率发布、决策和执行。Audit 首屏锁定完整 PIT 结果集合后物化不可变 snapshot manifest，manifest 封存 `result_persisted_at`，后续仅使用签名 snapshot/offset；header/payload/FK substitution、ORM private shortcut、Collector 删除、race/rollback、cursor 篡改/跨快照均 fail closed。新增 unit/component/migration `11/8/2 passed`，另有 `1 skipped` 的 PostgreSQL 双连接并发测试；既有 result + lifecycle 七文件回归 `35 passed, 1 skipped`。真实 owner authorization、forecast/outcome 历史和合格研究证据仍缺，R7 保持 `blocked`。

本轮执行索引：

- [R1/R2 启动门整改计划](../plans/strategy-research-r1-r2-readiness-plan-2026-08-05.md)
- [R3/R4 启动门禁及分阶段实施计划](../plans/macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md)
- [R5—R8 启动门禁与分阶段实施计划](../plans/strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md)
- [R6 简单基准不足与状态模型分阶段计划](../plans/r6-simple-baseline-shortfall-and-state-model-staged-delivery-2026-08-05.md)
- [R1—R8 执行状态与复核入口](../plans/strategy-research-capability-roadmap-execution-2026-08-05.md)
- [R1—R8 完成度审计与剩余开发队列](../plans/strategy-research-capability-completion-audit-2026-08-05.md)

`blocked` 表示备忘定义的前置证据尚未齐备，不表示通过创建空模型、默认参数或演示页面即可解除。每项能力只有在 canonical owner 提供带时间、可追溯引用且完整的 verified evidence 后，才允许另建独立实施计划和分支。

## 1. 备忘目的

当前实施计划优先处理硬编码情景、版本治理、AI MCP 受控修改，以及少量能复用现有能力的 Quick Wins。本备忘单独保存开发成本更高、数据依赖更重或需要严格研究验证的能力，避免：

- 在同一批次同时扩张情景、量化、固收、公司研究和部署边界；
- 因已有“因子”“风险平价”“债券”等名称而误判能力已经完成；
- 为了快速展示而把主观映射、代理数据或默认阈值重新硬编码；
- 让探索性模型绕过 PIT、研究晋级、数据新鲜度和人工确认。

本备忘不是无限期 backlog。每项能力都给出启动条件、建议 owner 和最低验收标准，条件满足后应拆成独立 plan、分支和回归包。

## 2. 当前系统定位

AgomTradePro 当前主轴是：

```text
宏观/Regime/Policy/Pulse
        ↓
通用标的评分与 Qlib Alpha
        ↓
规则化资产配置与风险闸门
        ↓
人工确认、模拟执行、回测与归因
```

当前相对强项：

- 数据来源、freshness、failover 和 decision block；
- Regime/Policy/Pulse 状态与规则化配置；
- 通用财务、估值、因子和 Qlib Alpha；
- 信号证伪、PIT 回测、研究晋级；
- Beta/Risk Gate、执行审批和 Audit 归因。

当前研究深度缺口：

- 公司经营变量到盈利预测的因果链；
- 多类投资者资金流和市场结构解释；
- 正式的高频宏观因子复制、筛选与检验；
- 宏观因子风险贡献与组合优化；
- 久期、曲线、信用和流动性相对价值；
- 前瞻情景概率校准与历史类比验证。

## 3. 能力路线总览

| 编号 | 长期能力 | 主要参考方法 | 价值 | 成本/风险 | 建议顺序 |
|---|---|---|---|---|---|
| R1 | 行业经营驱动与盈利预测平台 | 大消费 | 高 | 高数据维护、中模型风险 | 第一梯队 |
| R2 | 市场结构与投资者资金流全景 | 权益市场 | 高 | 数据授权和口径风险 | 第一梯队 |
| R3 | 高频宏观因子复制与 nowcast | 高频宏观因子 | 很高 | 高统计、数据和研究风险 | 第二梯队 |
| R4 | 宏观敞口回归与宏观因子风险平价 | 高频宏观因子 | 很高 | 高模型和组合风险 | R3 之后 |
| R5 | 固定收益相对价值与久期引擎 | 宏观固收 | 高 | 高数据和资产建模成本 | 第二梯队 |
| R6 | 高级状态模型与政策反应函数 | 高频宏观/宏观固收 | 中—高 | 易过拟合、解释成本高 | 第三梯队 |
| R7 | 情景概率校准、历史类比与路径模拟 | 权益市场/宏观固收 | 高 | 依赖长期情景运行证据 | Quick Wins 后 |
| R8 | 多资产优化与真实执行约束统一 | 四类方法的组合层 | 很高 | 高耦合、需真实交易证据 | R4/R5 后 |

建议顺序不是按模型“高级程度”排序，而是按数据可用性、决策收益和可验证性排序。

## 4. R1：行业经营驱动与盈利预测平台

### 4.1 目标

从通用财务评分升级为可解释的经营模型：

```text
经营驱动 → 收入 → 成本/毛利率 → 费用 → 利润 → 现金流 → 估值
```

覆盖模板候选：

- 餐饮：门店数量、同店销售、客单价、翻台率；
- 零售/零食：门店数、单店收入、份额、毛利率、净利率；
- 啤酒：销量、吨价、产品结构；
- 教育：培训人数、学费、续费率；
- 服装：品牌、渠道、门店、单店收入、毛利率；
- 后续行业使用独立模板，不把所有公司塞进同一公式。

### 4.2 为什么后置

- 自动化需要公司公告、行业高频、价格、门店、渠道和成本数据；
- 不同行业的数据频率和业务定义差异很大；
- 盈利预测必须区分事实、研究员假设和模型推断；
- 错误的自动预测比缺少预测更危险。

### 4.3 建议边界

- `equity` 拥有公司经营模型和预测结果；
- `sector` 拥有行业模板与行业比较语义；
- `data_center` 拥有原始/标准化经营事实和来源证据；
- `valuation` 消费已批准预测，不自行生成经营假设；
- `research` 管理模型验证和晋级。

### 4.4 启动条件

1. Quick Win 经营驱动工作表已有真实使用反馈。
2. 至少一个行业具备连续、可审计的经营数据源。
3. 财务和估值事实通过 Publication/PIT 门禁。
4. 明确预测 horizon、误差指标和基准预测。

### 4.5 最低验收

- 能还原 base/bull/bear 的每个假设；
- 能按季度记录预测与实际偏差；
- 输出收入、利润、利润率和估值敏感性；
- 不能用未来公告或最新修订数据回填历史预测；
- 自动预测必须经过 research PromotionDecision 才能进入正式估值。

## 5. R2：市场结构与投资者资金流全景

### 5.1 目标

从现有成交额、融资余额、ETF 流和主力/散户流，扩展到：

- 产业资本；
- 外资；
- 居民资金；
- 融资盘；
- 险资；
- 公募/ETF；
- 回购、增减持和解禁；
- AI/非 AI、新旧经济、内外需等可版本化资产组。

### 5.2 为什么后置

- 数据口径、可得性和授权差异大；
- 资金流代理容易被误读为真实投资者行为；
- 资产组成员随时间变化，必须支持 PIT membership；
- 需要把“资金量”“持仓变化”“交易净流入”严格区分。

### 5.3 建议边界

- `data_center`：资金流事实、主体分类、资产组 membership 和 Publication；
- `sector`/`asset_analysis`：结构比较；
- `pulse`：只消费已发布的聚合状态，不保存第二份资金流真源；
- `audit`：检验资金流信号的实际解释力。

### 5.4 启动条件与验收

- 每类资金流有清晰定义、单位、频率、来源和修订方式；
- 至少覆盖两个市场周期并具有 PIT membership；
- 代理指标必须显式标记 proxy；
- 能区分总量变化、加速度、历史分位和跨主体差异；
- 无可靠数据时不输出“增量/存量/减量博弈”的确定结论。

## 6. R3：高频宏观因子复制与 Nowcast

### 6.1 目标

建立真正的宏观因子研究链，而不是复用股票横截面 FactorEngine：

1. 定义增长、通胀、利率、信用、流动性和汇率目标变量；
2. 建立可交易代理资产与高频数据 universe；
3. 构建 Factor Mimicking Portfolio；
4. 使用 Lasso + 交叉验证筛选变量；
5. 报告显著性、调整后 R²、BIC、稳定性和经济含义；
6. 形成“当前状态”和“未来若干月预期”两组日频因子；
7. 进行样本外、滚动和不同市场阶段验证。

### 6.2 为什么后置

- 需要稳定的历史 vintage、期货连续合约和宏观发布日期；
- Lasso 选择不等于经济有效，需要研究纪律和人工复核；
- 代理资产和目标变量之间存在结构变化；
- 无 PIT 数据会产生严重后视偏差。

### 6.3 建议模块

该能力具有独立业务实体、研究规则和数据结果，实施前应评估新增 `macro_factor` App，而不是继续扩大股票横截面的 `factor`。若不新增 App，也必须通过明确 Protocol 隔离两种因子语义。

### 6.4 启动条件

1. Data Center 的目标宏观序列、发布日期、修订和代理资产价格具备 PIT manifest。
2. Research Experiment Registry、multiple-test family 和 PromotionDecision 可用。
3. 明确训练、验证、样本外、walk-forward 和 embargo。
4. 有稳定 benchmark 和交易成本假设。

### 6.5 最低验收

- 每个因子保存目标定义、候选资产、入选资产、权重和版本；
- 报告样本内外 R²、IC、稳定性、换手和成本；
- Lasso 超参数通过嵌套或严格交叉验证选择；
- 结果能被相同 PIT manifest、代码版本和参数复算；
- 失效时有明确退役机制，不把旧模型继续发布为 current。

## 7. R4：宏观敞口回归与宏观因子风险平价

### 7.1 目标

- 估计资产、行业和组合对宏观因子的暴露；
- 报告 beta、置信区间、R²、残差和稳定性；
- 将资产风险分解为增长、通胀、利率、信用、流动性等宏观来源；
- 优化各宏观风险来源的贡献，而不是简单做资产等权或波动率倒数。

### 7.2 与当前能力的区别

当前 Rotation 的 `risk_parity` 是资产历史波动率倒数加权。未来实现不得沿用同名输出冒充宏观因子风险平价，应提供独立 `methodology`、`factor_covariance_version` 和风险贡献明细。

### 7.3 前置条件

- R3 宏观因子通过样本外验证；
- Portfolio 有规范的资产暴露和协方差输入；
- 交易成本、权重上下限、换手和流动性约束可用；
- 至少存在一个资产风险平价和等权基准。

### 7.4 最低验收

- 风险贡献之和与组合风险一致；
- 协方差矩阵异常时 fail closed 或进入明确降级；
- 报告滚动暴露和 regime 稳定性；
- 回测比较等权、资产风险平价、宏观因子风险平价；
- 不使用未来修订宏观数据。

## 8. R5：固定收益相对价值与久期引擎

### 8.1 目标

把“债券”从资产大类标签升级为可计算的策略能力：

- 国债/政策性金融债曲线；
- 久期、修正久期和凸性；
- carry 与 roll-down；
- 2Y—10Y、10Y—OMO、2Y—DR001 等利差；
- 信用利差、等级迁移和流动性溢价；
- 曲线陡峭/扁平交易；
- 期限、信用和流动性风险预算；
- 组合级利率与信用压力测试。

### 8.2 为什么后置

- 当前系统主要持有债券基金/ETF 和大类权重，不具备完整券级现金流；
- 收益率曲线、政策利率、信用估值和流动性数据需统一口径；
- 债券交易的计息、结算和流动性约束不同于股票；
- 简单文字“缩短久期”不足以支撑真实调整。

### 8.3 建议模块与边界

若进入券级研究，应新增独立 `fixed_income` App：

- Domain：Bond、CashFlow、Curve、Spread、Duration、RelativeValueSignal；
- Application：曲线构建、久期预算、相对价值和压力测试；
- Infrastructure：债券主数据、估值、成交和曲线适配；
- Interface：研究和组合预览。

Data Center 仍是事实真源，Strategy/Portfolio 只消费目标暴露和订单草案。

### 8.4 启动条件与验收

- 至少两条可靠曲线和一套信用估值数据通过 Publication；
- 债券主数据、现金流和交易日历完整；
- 久期/凸性与第三方或手工样本对账；
- 相对价值信号有历史分位、成本和流动性约束；
- 第一阶段只输出研究建议，真实执行另立计划。

## 9. R6：高级状态模型与政策反应函数

候选研究：

- Markov 状态切换；
- Hidden Markov Model；
- 政策反应函数；
- 动态贝叶斯状态概率；
- Regime 转移矩阵和持续期模型。

启动前必须证明简单 PMI/CPI/Pulse 规则的明确不足，并建立简单基准。模型状态需要经济解释、稳定标签和样本外转移准确率；不得为了“高级”替换可解释规则。

## 10. R7：情景概率校准、历史类比与路径模拟

在 Quick Wins 积累足够情景运行记录后，进一步建设：

- 主观概率与模型概率分开保存；
- Brier Score、校准曲线和分箱命中率；
- 历史相似阶段检索；
- 路径依赖和多期冲击；
- 情景之间的转移与条件概率；
- 情景假设被证伪后的自动复核提醒。

启动条件：至少积累一段完整预测—复核—兑现记录，且 Forecast Ledger 能按情景版本评分。没有真实结果记录前，不应训练所谓“情景概率模型”。

## 11. R8：多资产优化与真实执行约束统一

长期目标是把以下输入纳入同一组合构建问题：

- 预期收益或赔率；
- 宏观与资产风险暴露；
- 情景损失；
- 最大回撤和风险预算；
- 交易成本、换手、流动性和持仓上下限；
- A 股、基金、债券和商品的交易约束；
- 人工限制和账户资金需求。

该能力必须依赖 Portfolio canonical snapshot、Risk Center、R3/R4/R5 的可靠输入和真实执行反馈。不得先造一个无真实约束的优化器，再让执行层修补不可交易结果。

## 12. 全局研究纪律

所有长期能力共同遵守：

1. 数据、规则、模型解释、个人约束和人工判断分层。
2. 外部事实只通过 Data Center；current 决策只消费 Published 数据。
3. 回测和模型晋级必须引用 PIT manifest。
4. 探索结果与生产结果分开，缺少证据时标记 exploratory。
5. 不在 Domain 中硬编码指标目录、资产名单、阈值和情景。
6. 不把相关性包装成因果关系。
7. 不把规则分数包装成概率。
8. AI 可以提出假设、生成反方观点和创建草稿，不能绕过权限、确认和晋级门禁。
9. 每个模型必须有 benchmark、失效条件、监控、退役和回滚路径。
10. 新业务主任务默认进入 TUI，不扩张 Classic 页面。

## 13. 禁止的捷径

- 用当前成分股回填历史资产组；
- 用请求时间包装旧观测为“实时”；
- 用常量缺省值补齐缺失因子；
- 将波动率倒数称为宏观因子风险平价；
- 仅报告最佳参数而隐藏试验 family；
- 让 LLM 直接生成无法复算的盈利预测；
- 通过 Prompt 规定权限、确认或风险边界；
- 在 Application 或 Interface 直接读取其他 App ORM；
- 为快速接入新增一批 raw MCP tools；
- 数据不足时通过硬编码资产映射继续给出肯定结论。

## 14. 启动决策模板

任何一项从备忘进入实施计划前，必须回答：

| 问题 | 必需证据 |
|---|---|
| 当前用户主任务是什么？ | 一句话 primary task 和 outcome |
| 现有简单能力哪里不足？ | 真实案例、误差或决策缺口 |
| 数据是否可用？ | 来源、频率、PIT、Publication、覆盖率 |
| 最简单基准是什么？ | 规则/等权/历史均值等 |
| 如何避免后视偏差？ | as-of、manifest、样本切分 |
| 如何验证收益？ | 样本外指标、成本和风险 |
| 谁能激活？ | owner、RBAC、确认、PromotionDecision |
| 如何回滚？ | 配置、模型、读取和数据回滚点 |
| 哪些能力明确不做？ | 独立非目标清单 |

条件不完整时保持在备忘状态，不以“先做页面”代替业务与数据准备。

## 15. 复核节奏

- 情景治理 M1-M3 完成后：复核 R7 数据积累设计。
- Quick Wins M5A 完成后：根据真实使用决定 R1 或 R2 谁先启动。
- Data Center D0-D9 Publication/PIT 生产验收后：复核 R3、R5 数据前置。
- Macro Factor R3 样本外通过后：才允许启动 R4。
- 固收研究完成且有真实持仓需求后：再规划债券执行能力。
- 每次版本收口时更新本备忘状态，不复制动态模型数、数据行数或测试数。

## 16. 关联文档

- [情景治理与策略研究 Quick Wins 整改计划](../plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md)
- [人机协同决策分层设计](human-judgment-decision-layering.md)
- [集中风控中心](risk-center.md)
- [研究可信度与决策可复算体系整改计划](../plans/research-integrity-and-decision-reproducibility-2026-07-21.md)
- [Data Center 唯一真源架构重构计划](../plans/data-center-canonical-architecture-refactor-2026-08-02.md)
- [估值定价引擎](valuation-pricing-engine.md)
- [MCP 技术与开发标准](../mcp/mcp-technical-and-development-standard.md)
