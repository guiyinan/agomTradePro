# 策略研究能力 R1—R8 完成度审计（2026-08-05）

> 状态：**路线图未完成；无 P0，仍有可在真实数据到位前开发的 P1**
> 审计基线：`dev/refactor-scenario-governance-quick-wins` / `6958b33c`
> 权威目标：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)

## 1. 审计结论

上一批完成了 readiness、research-only 合同和 13 项限定交叉复核整改，但不能据此推断完整路线图已经实现。本次由三组 Luna Max 分别审计 R1—R3、R4—R6、R7—R8，并按备忘中的目标、启动条件、最低验收和全局研究纪律逐项核对。

- 未发现当前代码可越过 research-only/readiness 直接影响生产决策或执行的 P0。
- 真实数据、Publication、PIT 样本、历史 outcome、外部对账和 PromotionDecision 仍是外部阻断。
- 同时确认多项纯软件能力仍可在无真实数据时开发，因此不得再使用“R1—R8 无数据基础全部完成”的口径。
- 本批优先完成 R5 组合风险预算/压力测试，并修复 R4 到期边界及报告 seal；其余项目进入下列实施队列。

## 2. 逐能力剩余开发项

| 能力 | 已有可靠基础 | 仍可无数据开发的主要 P1 | 必须等待的真实证据 |
|---|---|---|---|
| R1 | Sector typed AST/DAG、三情景、PIT fact、Equity 误差台账与持久 bridge、cash-flow/六阶段/template-run seal、owner-approval-enforced baseline spec、完整配对 trial、Research exact Promotion/retirement/rollback | 当前 R1 无数据软件切片经 Luna Max 复核已无 P0/P1；Valuation 消费须等待真实证据并另建阶段 | QW-7 反馈、连续行业 KPI、财务/估值 Publication、真实 owner approval、trial 与 approved decision |
| R2 | actor/series 双时间、proxy/measure semantics、PIT membership、描述性证据、版本化 expected-period calendar、series×period 完整 coverage、整期全缺门禁 | 运行时 taxonomy/calendar Publication 接线与研究晋级闭环 | 获批 taxonomy、授权、两个市场周期、Production Publication、Audit 解释力 |
| R3 | 独立 App、exact PIT fact/manifest、historical-mean/FMP、nested temporal-CV runner、canonical artifact bytes、dated current/forward ledger、append-only retirement lifecycle | regime 分段、trial/Promotion exact artifact binding、监控与生产读取投影 | 宏观 vintage、代理资产/连续期货、真实 cost/benchmark、OOS trial、Promotion |
| R4 | beta/CI/R²/残差、PSD、风险贡献、typed rolling/regime、三基准同窗 OOS、Portfolio result ledger/query、covariance diagnostics、Research stable scope/policy/trial/decision、五表 append-only ledger、lifecycle/active provider 与 concrete composition | 下游 active consumer 接线须等待真实 Promotion 并另行验收 | R3 晋级版本、真实 exposure/covariance/constraint snapshot、Regime PIT assignment、owner authorization 和历史样本 |
| R5 | 单券定价、久期/凸性、carry/roll-down、曲线/信用利差、PIT 历史分位、评级迁移、流动性溢价、signed curve portfolio、容量/流动性/shortability 与 ID-only composite 软件合同 | append-only result ledger、concrete providers/跨 owner atomic UoW、Research Promotion/retire/rollback | 两条曲线、信用估值、Bond Master/CashFlow/Calendar Publication、PIT 历史/评级 cohort、容量/借券与外部对账 |
| R6 | 简单基准不足 report、高级 artifact evidence gate、七指标同窗 qualification、政策反应系数/诊断 | qualification persistence、监控/退役/Promotion 闭环 | 真实 shortfall、PIT 输入、预注册 family、OOS 证据 |
| R7 | 概率分栏、Brier/分箱、PIT 类比、typed 逐期路径证据、append-only reminder ledger/internal outbox、due/ack/escalate/expiry | calibration/path 结果持久化、retirement/Promotion lifecycle 与审计分页 | 完整预测—复核—兑现历史、获批 sample policy、PIT 路径样本 |
| R8 | canonical snapshot、execution feedback、13 类 typed 输入、current baseline、可投资 universe、四市场约束、path drawdown、四候选比较、append-only result/Promotion/retirement/rollback lifecycle | 本轮无数据软件清单经 Luna Max 复核已无 P0/P1；进入 transition plan/生产消费前仍须基于真实证据另建阶段 | broker reconciliation、R3/R4/R5 晋级、真实 Portfolio snapshot、成本/容量/市场约束校准 |

## 3. 本批完成项

### 3.1 R4 证据封存整改

- `valid_until` 到期边界由 `>` 收紧为 `>=`，到期时刻立即 stale。
- `MacroRiskCandidateReport` 保存 input hash，并对资格状态、factor/residual/total variance、turnover、完整 contribution vector、blocker code/detail、研究边界和时间重新计算 canonical SHA-256。
- 篡改 eligibility 或 contribution 后，report 构造立即拒绝。

### 3.2 R5 组合风险预算与压力测试

新增纯 Domain/Application 纵切：

- Portfolio-owned snapshot owner/hash/as-of 绑定；
- 估值/流动性证据归 `data_center`，久期/凸性和信用敏感度归 `fixed_income`；
- 完整 PIT manifest、Publication identity、币种、as-of、freshness 和 exact-expiry 门禁；
- 可复算 budget policy hash，bundle 精确绑定 policy hash；
- DV01、CS01、convexity、可变现比例、流动性成本及逐持仓恒等式；
- 显式 parallel/key-rate/steepener/flattening/credit widening shock；
- 一阶利率、凸性、信用和总压力 P&L 贡献恒等式；
- 所有预算和证据问题发布稳定 blocker；
- 完整 input/output SHA-256，固定 `research_only / must_not_use_for_decision / must_not_execute`。

本纵切不新增 ORM、迁移、URL、任务或生产写入，也不解除 R5 readiness。

### 3.3 R1 Sector→Equity 持久证据桥接

- Bridge 只接受 `run_key/run_version` 与 Equity-owned typed sensitivity evidence，从 Sector append-only evidence 读取、校验 hash 并 typed restore；调用方不能提交自称可信的 run result。
- Equity v2 预测封存任意治理 `metric_code` 的完整 PIT identity、template/run identity、cash flow、三情景六阶段结果及 sensitivity source artifact hash。
- `0012` 精确区分 0010/0011 legacy hash recipe，保留原 content hash、估值和 promotion 字段；旧行不补造 template/run、cash flow 或 stage，unverified legacy 只读且不可消费。
- v2 当前强制 research-only。旧的 decision-id-only checker 不能解锁估值消费；Promotion artifact exact binding 仍是后续独立 P1。
- Equity/Sector concrete base manager、并发首次写、run identity 幂等/冲突、事务全回滚及季度 actual evaluation 均已有直接组件证据。

### 3.4 R2 预期期间与完整 coverage

- Data Center 新增无 seed、append-only 的版本化 `MarketStructurePeriodCalendar`，request 精确绑定 code/version，日历 payload 与 hash 一并进入研究证据。
- Application 按 request series × calendar periods 生成完整 coverage，不再由已有 observation 反推期间；某整期所有 series 都缺可靠数据时发布稳定 blocker 并 fail closed。
- 日历 identity/frequency/as-of/active/expiry、coverage 缺格或重复、raw hash tamper、并发注册和 `_base_manager` 旁路均被拒绝。
- `0061` 只建 schema，不回填日历、不创建业务 seed，并保持旧 evidence payload/hash 字节不变。

### 3.5 R7 人工复核 reminder ledger/internal outbox

- 修复 review intent 的确定性缺陷：schedule 固定锚定 invalidation time，identity 同时封存 forecast observation、scenario revision/set、policy version/content hash；重复研究评估不再产生同 ID 异 payload。
- Research 新增 immutable reminder header 与 hash-chained lifecycle event，状态由 `scheduled / due / escalated / acknowledged / expired` 事件推导；exact due/escalation/expiry 边界和 terminal transition 均 fail closed。
- Conditional/transition evidence 显式携带 period index，并从 typed `ScenarioPathStudyEvidence` 派生完整 horizon binding；调用方不能提交任意 claimed hash，也不能跨 path、scenario set 或 period 替换。
- Application 只提供 internal pull queue、deterministic reconcile 与 owner-authorized human ACK；Domain/DB 固定 `must_not_execute / must_not_use_for_decision / no auto approval / no external dispatch`，未新增 Celery、邮件、短信、webhook 或执行链。
- `research.0002` 只新建空 ledger/outbox 表，不 seed、不回填旧 reminder，并保持 0001 既有研究记录不变；default/base/related manager mutation、并发 winner replay、同 key 异 evidence、事务回滚和 raw tamper 均有组件证据。

### 3.6 R3 可复算 runner、dated outputs 与 retirement lifecycle

- PIT design rows 逐项封存 target/proxy fact version、content hash、effective/available time，并核对 typed manifest selected versions；晚修订、未来不可知值和跨 manifest 替换均拒绝。
- Nested temporal-CV plan 精确绑定 governed split windows、purge/embargo、label availability 和 inner/outer row identity；outer OOS 全局唯一且不进入 selection。每个 outer fold 独立选择 alpha/资产，只有显式 final fold 绑定最终 result。
- Historical-mean 与 fixed-universe FMP 基准按 fold 重算；historical mean 与外部 final fit 使用同一 train+validation 窗口，避免人为弱化基准。
- External envelope 封存 per-fold inner scores、selected alpha、coefficients/weights、final-fit lineage、OOS prediction 和 canonical artifact bytes；bytes/media/length/producer 可从 DB 回读并重新解析、SHA 校验。
- Dated output 精确区分 current horizon 0 与 forward horizon > 0，保存 as-of/target period/produced/valid-until/value/unit；到期时刻立即 stale，latest 不等于 current。
- Run artifact、outputs 与 lifecycle event 使用三张 append-only 表；retirement 通过 owner-attested hash chain 派生，不修改 0001 source result。`macro_factor.0002` 为 schema-only、零 seed，完整保留 legacy payload/hash/status/timestamp。

### 3.7 R8 governed optimization input、结果与生命周期

- 13 类数值 payload 分别绑定 canonical owner、payload hash、PIT/knowledge time、有效期和 source artifact；R3/R4/R5 Promotion 必须由 exact provider 在运行时重读，调用方不能提交自称已批准的对象。
- Portfolio current baseline 使用版本化 conservation tolerance；可投资 universe 的 `can_buy / can_sell / retain_if_held` 被合成硬边界，held-only/no-buy 资产不能增仓。
- A 股、基金、债券和商品规则均为带 `available_at` 的 typed constraint。weight-only 求解无法证明手数、T+1、结算、应计利息或保证金约束时，候选稳定返回 `constraint_not_yet_enforced`，不会产出可执行权重。
- Path drawdown 只接受 knowledge cutoff 之前的完整逐期资产/现金路径；current、等权、资产风险平价和 local-search 四候选必须完整、守恒、可重算，selected candidate 必须是真实合格 argmin。
- 完整 problem/result/lifecycle 证据图统一使用 canonical Decimal 与 UTC 时间；scale 或等价时区表示不改变 hash。
- `portfolio.0006` 只创建 append-only input/result/lifecycle 台账，不 seed、不回填。Promotion 事件必须从 Research provider 精确回读，retirement/rollback 必须从 Portfolio owner authorization provider 精确回读；Repository 只持久化，不承担授权。
- 本纵切未注册 API/TUI/Celery/订单或 transition plan 写入口，所有输出固定 `research_only / must_not_use_for_decision / must_not_execute`。

### 3.8 R1 精确预测基线、trial 与晋级生命周期

- Equity 定义强制 owner approval 的 baseline spec 合同，精确绑定 subject、industry、scenario、purpose、horizon、calendar 和 metric set；预测与 baseline 在每个 period×metric 上完整配对，actual 使用独立 PIT manifest，不允许以评估时可见事实改写预测起点。
- Baseline artifact、trial result、forecast/template-run/sensitivity seal 与 owner receipt 均使用 canonical hash；trial 预注册样本、误差指标、失效条件和比较口径，缺行、重复行、单位不一致、未来知识或 owner 不一致均 fail closed。
- Research 使用 R1 专用 typed Promotion policy/decision，不复用通用 Sharpe/FDR/DSR 语义；approved/rejected 都保存完整审计结果，生命周期按 canonical scope 隔离并支持 promoted、retired、rolled_back。
- Research Infrastructure 只依赖 Equity Application query port，在决策、查询 active promotion 与回滚时重读 canonical Equity ledger；decision id、自报 hash、伪造 receipt、非尾回滚、过期 policy/trial 和跨 scope 替换均不能放行。
- Equity 四张、Research 五张 append-only ledger 均通过 schema-only、零 seed 迁移建立；未注册 Valuation consumer、API/TUI/Celery 或生产读取面。

### 3.9 R4 rolling exposure、Regime 稳定性与同窗三基准

- 新增 R4-owned narrow evidence：Portfolio covariance/OOS return projection、Macro Factor exposure projection、Regime PIT assignment 和 Research exact R3 Promotion attestation；不反向复用 R8 optimizer/path DTO。
- 每个 typed walk-forward fold 强制 training/validation/OOS、purge/embargo、selection/evaluation cutoff；selection 必须晚于 validation、早于 OOS，协方差不得在 estimation window 结束前被观察，所有 formation evidence 必须在 selection 时已知且未到期。
- 每窗必须恰好包含等权、资产风险平价、宏观因子风险平价三种候选，并共享 snapshot、exposure/factor covariance、asset covariance、cost/constraint、current weights、universe 和 OOS return path；任一缺失或错配使整个 study fail closed。
- 等权、资产风险贡献、宏观风险贡献、逐期 frozen-weight return、gross return、variance、drawdown、turnover/cost、rolling exposure 与 Regime summary 均由服务重算；artifact factory 再逐值绑定 source projection、window metrics 和 aggregate summary，调用方不能预填 eligible。
- ID-only Application 在运行时通过 authoritative provider 精确重读 active/unexpired/unretired R3 attestation；缺 provider、错 artifact/decision/purpose 或到期均返回稳定 blocker。
- 本批不新增 ORM/migration、R4 Promotion lifecycle、current/组合预览/API/TUI/Celery/执行链；covariance condition number、rank 和 missing-coverage policy 仍列入后续 canonical persistence 切片。

### 3.10 R4 append-only result ledger 与 exact owner query

- Portfolio Application 新增 immutable Draft/Record：显式封存 study/artifact/R3/split、完整 window/evidence/source/candidate/output subhash、evaluated/recorded/valid-until、producer code、dependency lock 和 record hash；record factory 必须重新运行 R4 service 与 output integrity。
- 持久化命令只提交 identity/provenance，不提交 study、artifact、attestation 或 recorded-at；Application 通过 exact study provider 与 authoritative R3 provider 重读后才构造 Draft，Repository 使用 server clock 生成稳定 Record。
- Portfolio `0007` 只建立 input receipt/result 两张空表，FK `PROTECT`；default/base/related manager、instance/queryset update/delete、所有 bulk create、direct save、错误 UoW/clock、raw payload/column tamper 和 child failure 均 fail closed。
- 同 identity 并发写入返回首个 exact winner；不同 evidence 冲突。codec 只接受 canonical UTC datetime，typed restore 后逐项重建 study、attestation、artifact、subhash 和 record hash。
- Application exact query 只接受 `record_id + expected_record_hash + as_of`，要求 `recorded_at <= as_of < valid_until` 并返回 opaque owner row/UoW identity；不提供 latest/current/list，也不 import Research implementation。
- 协方差 evidence 新增 condition number、rank、expected/missing observation denominator 与 missing-value policy；rolling policy 版本化 maximum condition number 与 minimum coverage ratio，ill-conditioned、rank deficient 或 coverage 不足返回稳定 blocker。
- 本批仍未实现 Research-owned R4 policy/trial/decision 与 Promotion/retirement/rollback lifecycle，未接组合预览、R8 active input、API/TUI/Celery 或执行链。

### 3.11 R4 Research Promotion/lifecycle Phase A

- Stable scope 只包含 Research/r4 authority、下游 purpose、exact stable study-family id、固定 macro-factor-risk-parity target 及稳定 universe/factor/split/cost semantic IDs；study/R3/record/split/subhash/code/dependency 的 exact version/hash 只进入 registration、trial 和 decision seal，不会为每个新证据错误创建新 stream。
- Policy 必须 owner-recorded、active 且在最早 window selection 前预注册；三方法 family、minimum folds/regime coverage、相对两基准的 net return/drawdown/volatility/cost 门槛和 validity 全部显式版本化，无默认阈值。
- Decision command 只包含 policy、Portfolio record 和输出 decision identity；同一 atomic/UoW 内 exact 重读 policy、Portfolio owner record 与 current R3，并 claim Research owner receipt。Trial seal 覆盖全部 record/subhash/window/method/regime/exposure/R3/code/dependency；outcome、gates 与 validity 均由服务端派生。
- Lifecycle 使用 scope-local hash-chain stack：PROMOTED push，RETIRED 清空当前 top，ROLLED_BACK 只能 pop 到 `stack[-2]`；A→B→C 只能 C→B 再 B→A，skip/cross-scope/rejected/future target 均拒绝。
- PROMOTE/ROLLBACK/active 在当前 as-of 动态重读 policy、Portfolio record 与 R3；RETIRE 为避免上游失效后无法撤权，可按 decision-time 历史 PIT 重建 canonical bundle 后清栈。Active provider 重放完整 prefix，任一 exact evidence、receipt、bundle、chain 或 UoW 不一致均返回 None。
- Phase A 不新增 ORM/migration/concrete provider/composition；Research policy、decision receipt/bundle、lifecycle authorization/event 五张 append-only 表与下游 active consumption 留给 Phase B。

### 3.12 R4 Research Promotion/lifecycle Phase B

- 新增五张 Research-owned append-only 表与 schema-only `0004`；无 Portfolio FK、migration dependency、`RunPython`、`RunSQL` 或 seed，旧 `0001/0002/0003` SHA 与完整 R1 sentinel 行升级前后保持不变。
- Policy registration draft 不接受 caller `recorded_at/content_hash`，由 Repository 注入 server clock 重建 canonical Policy；五表只允许 private UoW + exact insert claim 写入，default/base/related manager、instance/queryset mutation 和全部 bulk conflict 模式均拒绝。
- Decision 与 lifecycle 在同一事务内先 claim receipt 再 append child；子表失败回滚 receipt。first-miss race 仅在 identity 与完整 bundle 均一致时重放 winner，异证据、stream sequence/previous fork 与 raw header/payload/FK tamper 均 fail closed。
- Strict typed codec 逐类型恢复并重验 dataclass/domain hash；repository 重建 trial/decision/lifecycle prefix，active 每次动态重读 policy、Portfolio Application exact record 与 current R3。RETIRE 仍按 decision-time historical PIT 清理过期 top。
- Composition 只注入 Portfolio Application port 和 current-R3 provider；未注册 API/TUI/Celery，也未开放 consumer/current/preview/execution。Phase B 软件合同不能替代真实 owner authorization、R3 Promotion、canonical inputs 或 OOS trial。

### 3.13 R5 relative-value Phase A

- 历史利差分位使用 owner-attested expected calendar denominator、release/PIT cutoff、latest-available revision、target-period 隔离、mid-rank tie 与完整 coverage/count/hash 重算；未来 revision、重复任意 revision、缺 target 或 coverage 不足稳定 blocked。
- 评级迁移显式封存 taxonomy/version、formation-time origin、horizon/grace、DEFAULT absorbing、WITHDRAWN/CENSORED/UNRESOLVED 五桶、完整 cohort denominator 与终态 Publication；逐行/顶层 count、rate、coverage 和 selection policy 全量重算。
- 流动性把 premium driver 与 financing/transaction/impact/liquidation cost 分离，区分 INCLUDES/EXCLUDES spread identity、one-way/round-trip、holding horizon、owner gross-included-cost manifest，并现场推导 quote age；partial evidence 在 blocked 状态可 canonical 封存，available 必须完整全集。
- Curve portfolio 使用 positive notional + LONG/SHORT 单一符号，版本化 topology 与合法 curve-role/kind pair，逐腿重算 KRD/DV01/CS01/convexity/carry/roll-down/cost/capacity/liquidity/borrow 及 cash conservation；每腿 raw liquidity evidence 在同 cutoff/同 policy 现场重算，不能信 caller derived result。
- Composite 将多 subject liquidity raw/result seals 与 curve 消费集合精确对齐；四 child 的 evaluated_at/policy hash/状态/阻断均进入 seal。Application 只收 input/policy ID/version/cutoff，并重读 Publication、BondMaster、CashFlow、Calendar 及 nested PIT/cohort/analytics/funding exact seals。
- Owner 方向固定为 Data Center raw facts、fixed_income analytics/candidate/input set、Portfolio funding、Research policy；全链固定 research-only/must-not-execute/must-not-use-for-decision。Phase A 不新增 ORM/migration/concrete providers/UoW/Promotion 或消费接线。

### 3.14 R5 relative-value Phase B1 persistence

- fixed_income 新增 input receipt/result 两张 append-only 表与 schema-only `0003`；无 `RunPython`、`RunSQL` 或 seed，旧 `0001/0002` bytes 与历史 sentinel 行保持不变。
- Receipt 封存完整 input/policy graph、owner、ID-only command hash、evaluation cutoff、server-owned `recorded_at` 与原始 evidence clock graph；历史证据只按 evaluation-time PIT 语义复算，不因记录时或今天已过期而误拒绝。
- 公开 Repository 仅提供 exact query；写能力位于 composition closure，只接受 ID/version/cutoff command，在共享 UoW 中进入 Data Center、Portfolio、Research Application atomic port 后重新执行 authoritative Phase A。任一 owner 缺失、事务键不一致、command/draft 错配或伪造 Draft 均零写入。
- Receipt/result 同事务 append，child 失败回滚 parent；first-miss race 只接受完整一致 winner。strict codec 与 query 重验 schema、UTC/Decimal/tuple 类型、payload、header、content hash、FK、owner 与 knowledge time；raw tamper 稳定报 corruption。
- Default/base/related manager、instance save/save_base/delete、bulk/create/update/get-or-create missing/update-or-create 等常规 ORM mutation 均拒绝；raw SQL、underscored QuerySet 和显式 unbound base dispatch 属防线外，任何由此产生的篡改必须在 exact restore 被发现。
- 本阶段不创建 Research PromotionDecision、retirement/rollback、active provider、consumer/current/API/TUI/Celery 或 execution 接线；B1 软件证据不替代真实 Publication、券级 PIT 历史、容量/借券或外部对账。

### 3.15 R6 qualification evidence

- 新增 Research Domain/Application qualification contract；命令只含 content-addressed study ID 与 assessment time，study provider 返回同 ID 不同 payload 时在读取其他依赖前稳定阻断。
- Study 在 OOS 前预注册 trial family、split、embargo、policy-reaction specification 和 exact policy hash；同窗比较固定 transition accuracy、log loss、calibration error、duration MAE、decision loss、complexity 与 label stability 七项指标、单位、方向和版本化最小改善阈值。
- S2 attestation 不接受裸 `ACCEPTED`；公共工厂必须读取 candidate、baseline shortfall、完整/verified PIT manifest、独立 artifact attestation 和 threshold payload，并重放原 S2 gate。PIT、artifact、threshold canonical hash 与时钟全部进入 qualification seal。
- Decision loss、complexity 与 label stability candidate 值由独立 content-sealed exact bundle 提供，Application 按 ID/version 重读；study 重封三值、provider substitution、future/stale、label drift 或 retired candidate 均 fail closed。
- 政策反应函数按 target/lag/预期符号/置信区间/p-value/最小幅度验证，并检查样本量、adjusted R²、残差自相关、异方差、参数稳定性和条件数；阈值全部来自 exact policy，无代码默认。
- 成功结果仅为 `EVIDENCE_COMPLETE` 且 `may_request_promotion_review=true`；没有 PromotionDecision、持久化、current/Regime/决策/执行接线，固定 research-only/must-not-use-for-decision/must-not-replace-regime。

### 3.16 R5 Promotion Phase A

- Research scope、registration/policy、trial、decision、decision authorization 与 lifecycle event 使用 content-addressed identity；预注册必须早于 selection/OOS，caller 不能提交 derived decision、hash 或完整 lifecycle stream。
- Trial 将每个 fixed_income B1 exact result 与唯一 Portfolio canonical owner record 配对；Portfolio outcome seal 封存 owner row、FI result/owner seal、OOS clocks、return/cost/drawdown/liquidity/capacity/credit-loss 和三重安全标志。随机 hash、同 FI/Portfolio record 重解释或 trial provider 单方“好指标”均阻断。
- Decision Application 在 shared UoW 中逐项重读 Research policy/trial/authorization、fixed_income exact result 和 Portfolio outcome；authorization 精确绑定 `decided_at`、`decision_recorded_at` 与派生 `decision_valid_until`，不得跨 as-of 复用或延长有效期。
- Lifecycle Application 命令只含 scope/action/evidence identity；完整 prefix、authorization、winner 与 append 均在 shared UoW 中处理。PROMOTE/RETIRE/ROLLBACK 复用完整 Domain replay，rollback 只能回到 `stack[-2]`，stream fork、跨 scope、缺前缀或异 winner fail closed。
- Active provider 每次按 PIT 重放 stream，并动态重读 policy、trial、FI、Portfolio 与 decision authorization；失效 decision 可按 decision-time 历史 PIT 由 RETIRE 清理，任一 current owner evidence 缺失/替换/过期则不发布 active。
- Phase A 仅有 Domain/Application 与测试，无 ORM/migration/concrete repository/provider、API/TUI/Celery、R8/current/执行接线；fixtures 不构成真实 OOS、owner authorization 或 approved PromotionDecision。

## 4. 后续实施顺序

1. R5 Promotion Phase B append-only persistence/concrete providers；R6 qualification persistence/monitoring/Promotion lifecycle。
2. R3 regime 分段、trial/Promotion exact binding 与监控读取投影。
3. R7 calibration/path 结果持久化与 retirement/Promotion lifecycle。

R1 与 R8 本轮无数据软件清单已关闭。R1 只有取得真实 QW-7、Publication、连续 KPI、真实 trial 与 approved decision 后，才另建 Valuation 消费阶段；R8 只有取得真实 R3/R4/R5 Promotion、Portfolio snapshot、broker reconciliation 和约束校准后，才另建 transition plan/生产消费阶段。两者都不在 fixture 上提前接线。

每项按独立 commit 组推进；真实证据未齐时保持 blocked，不使用 fixture、模型文件或迁移存在作为 ready 证明。

## 5. 验证边界

当前新增纵切最低回归：

```powershell
pytest tests/unit/portfolio/test_macro_factor_risk.py -q
pytest tests/unit/fixed_income/test_portfolio_risk.py tests/unit/fixed_income/test_portfolio_risk_use_case.py -q
python scripts/check_mypy_regression.py apps/portfolio/domain/macro_factor_risk.py apps/fixed_income/domain/portfolio_risk.py apps/fixed_income/application/portfolio_risk.py
python scripts/verify_architecture.py
```

本批此前验证 fixed-income 与 R4 macro-risk 共 `49 passed`。本次 R1/R2 续批由实现与只读复核 Luna Max 交叉验收：R1 unit `15 passed`、component `10 passed`、migration `3 passed`；R2 unit `18 passed`、component `6 passed`、migration `2 passed`。主代理另行联合复跑 unit `27 passed`、component `13 passed`。14 个变更生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Django system check、三 App migration drift、架构扫描（2150 files / 0 violations）、业务配置硬编码门禁和 43 个 current-data surface 均通过。

R7 reminder 续批经 Luna Max 实现与只读复核关闭全部 P0/P1；主代理独立复跑 unit `18 passed`、component `11 passed`、migration `2 passed`。8 个变更生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Research migration drift、Django system check、架构扫描（2155 files / 0 violations）、44 个 current-data surface、业务配置、governance consistency 和 Celery task contract 均通过。

R3 runner 续批经 Luna Max 实现与多轮泄漏/持久化复核关闭全部 P0/P1；主代理独立复跑 unit `32 passed`、component `11 passed`，实现 agent migration `1 passed`。16 个生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Macro Factor migration drift、Django system check、架构扫描（2168 files / 0 violations）、45 个 current-data surface、业务配置和 governance consistency 均通过。

R8 governed optimization 续批经 Luna Max 实现、两轮独立只读复核和定点整改后无 P0/P1；主代理独立复跑 unit `21 passed`、component `11 passed`、migration `2 passed`。19 个生产文件增量 mypy 为 0 regression；Ruff、Black、isort、Portfolio migration drift、Django system check、架构扫描（2182 files / 0 violations）、45 个 current-data surface、业务配置、governance consistency 和 Celery contracts 均通过。测试只证明 software contract，不替代真实 Promotion、snapshot、broker reconciliation 或约束校准。

R1 精确基线与晋级续批经 Luna Max 实现、独立只读复核和定点整改后无 P0/P1：Domain/Application `80 passed`；Equity unit/component `99 passed`、migration `2 passed`；Research unit/component/migration `48 / 24 / 3 passed`。相关生产文件增量 mypy 为 0 regression，Ruff、Black、isort、Equity/Research migration drift、Django system check、架构边界、业务配置与 governance consistency 均通过。测试只证明 baseline/trial/Promotion/lifecycle 软件合同，不替代真实 Publication、经营事实、样本外结果或 Valuation 授权。

R4 rolling 续批经 Luna Max 实现、独立只读复核和两轮定点整改后无 P0/P1；主代理复跑新增合同/服务/Application 与既有 R4 candidate 回归共 `29 passed`，实现代理另复跑相关 R8 回归 `15 passed`。5 个生产文件增量 mypy 为 0 regression；Ruff、Black、isort、架构扫描、业务配置和 governance consistency 均通过。测试只证明 rolling/regime/同窗比较的软件合同，不替代真实 R3 Promotion、canonical covariance/returns、Regime PIT 历史或 R4 Promotion lifecycle。

R4 persistence/query 续批经 Luna Max 实现和多轮独立只读复核后关闭 canonical UTC、ID-only 权威重读、server-clock/UoW、coverage denominator 和 artifact provenance 问题，最终无 P0/P1；主代理独立聚合复跑 unit/component/migration `43 passed`。11 个生产文件增量 mypy 0 regression，Ruff、Black、isort、Portfolio migration drift、架构、治理、业务配置和模块循环均通过。测试只证明 Portfolio owner ledger/query 软件合同，不替代真实输入、Research R4 Promotion/lifecycle 或下游激活。

R4 Promotion Phase A 经 Luna Max 实现、持续旁审和最终独立复核后关闭 stable scope、Portfolio UoW/atomic TOCTOU、receipt recorded-at binding、RETIRE 失效死锁、连续 rollback 与 mypy 回退，最终无 P0/P1；主代理复跑 `29 passed`。10 个生产文件增量 mypy 0 regression，Ruff、Black、架构、业务配置与模块循环均通过。该证据只证明 Domain/Application 软件合同；Phase B 五表、concrete provider、真实 trial 与 active downstream 尚未形成。

R4 Promotion Phase B 经 Luna Max 实现和持续只读复核后关闭 caller policy backdate、五表 direct/bulk/related-manager 绕过、receipt→child 回滚、first-miss raced winner、stream fork 与 raw tamper 问题，最终 P0/P1 均为 0。Phase A + codec `38 passed`，Phase B component `13 passed`，migration `4 passed`；7 个生产文件增量 mypy 0 regression，Black/Ruff、2236-file 架构、业务配置、模块循环和 migration drift 均通过。真实数据、owner authorization 与下游 active consumption 仍未形成。

R5 relative-value Phase A 经 Luna Max 实现、持续旁审和多轮定点整改后关闭 historical-current freshness 混淆、评级 survivor bias、流动性 hash 自引用/重复扣费、curve StopIteration、owner 反向依赖与 caller-derived liquidity 问题，最终 P0/P1 均为 0。主代理独立复跑 `32 passed`；7 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界/增量审计、业务配置与模块循环均通过。真实数据、持久化、跨 owner UoW 和 Promotion 尚未形成。

R5 relative-value Phase B1 经 Luna Max 实现、持续旁审与 exploit 定点整改后关闭 caller capability 自提权、command/draft 非语义绑定、历史/current freshness 混淆、strict-query content-hash 短路、`save_base` 与 related-manager 绕过、race/rollback/tamper 假覆盖，最终 P0/P1 均为 0。Codec `15 passed`、component `23 passed`、migration `2 passed`；7 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界/增量审计、业务配置、模块循环和 migration drift 均通过。真实数据、Research Promotion/lifecycle 与下游消费仍未形成。

R6 qualification evidence 经 Luna Max 实现、两轮独立攻击复核与定点整改后关闭同 ID study 重封替换、公开 zero-hash/私有 mint 绕过、裸 S2 `ACCEPTED` 包装和 derived metric 自证，最终 P0/P1 均为 0。R6 相关回归 `57 passed`；2 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界/增量审计、业务配置与模块循环均通过。真实 shortfall、PIT/OOS 数据、持久化、monitoring 与 Promotion lifecycle 仍未形成。

R5 Promotion Phase A 经 Luna Max 实现、持续旁审与三轮定点整改后关闭 Portfolio outcome/caller metric 自证、lifecycle 本地重放、authorization 跨 as-of 复用和 mypy 宽类型展开问题，最终 P0/P1 均为 0。完整 suite `26 passed`；9 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界、业务配置与模块循环均通过。Phase B append-only persistence/concrete providers、真实 OOS outcome/authorization/trial 与下游 active consumption 仍未形成。

R5 Promotion Phase B2a 已完成 Portfolio-owned relative-value outcome ledger：`portfolio.0008` schema-only、strict codec、server-clock/UoW ID-only writer、fixed_income Application exact owner reread 与 exact PIT query。Observation identity 唯一约束、owner seal/reference/header/payload 复核、append-only ORM guards、竞态/回滚均有证据；unit/component/migration `12/9/3 passed`，增量 mypy 0 regression。Research B2b persistence、真实 OOS outcome、owner authorization、Publication/容量/外部对账和下游消费仍未形成。

R7 approved sample policy 已完成 Research 两表 append-only approval/policy ledger、`research.0005` schema-only migration、strict UUID/typed codec、server-clock registration、Risk Center Application owner port/concrete adapter、shared UoW 与 exact PIT replay；scope/policy coherence、clock/header/payload/reference tamper、ORM shortcut、race/rollback 均 fail closed。R7 unit/component/migration `8/12/4 passed`，增量 mypy 0 regression。当前没有真实 Risk Center approved audit、forecast/outcome history 或 calibration sample，production composition 在 owner source 缺失时固定 unavailable 且不写入两表；calibration/path result persistence 与 Promotion/lifecycle 仍未形成。

R5 Promotion B2b 已完成 Research `0006` 五张 append-only ledger：artifact、decision authorization/bundle、lifecycle authorization/event 均由 shared-UoW/server-clock/ID-only closure 写入，fixed_income 与 Portfolio owner graph exact reread；PIT future cutoff、raw selector hiding、stream fork、append-only、race/rollback 均 fail closed。修复后 component `4 passed`、codec+migration `6 passed`；真实 approved trial、OOS outcome、owner authorization、Publication 与外部对账仍缺。

R7 result persistence 已完成 Research `0007` evidence graph、input receipt/result 两层 append-only ledger；calibration、历史类比、路径 assessment 只从 exact owner evidence 现场重算，结果固定 research-only。Unit/component/migration `4/7/3 passed`；真实 owner evidence、forecast/outcome history、Risk Center approved source 与 Promotion/lifecycle 仍缺。

完成路线图仍需为上表每项取得代码、迁移/台账、研究证据、运行时行为和 Promotion/回滚的直接证明；“测试全绿”只证明已覆盖合同，不替代真实数据和样本外结果。
