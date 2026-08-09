# 策略研究 R5—R8 启动门禁与分阶段实施计划（2026-08-05）

> 状态：R5—R8 无数据先行研究纵切均已实现；真实 Publication、样本历史、外部对账和晋级版本仍缺失，能力门禁保持 `blocked`
> 来源：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)
> 实施边界：本阶段只交付启动门禁、证据清单和后续最小纵切，不训练模型、不生成概率、不构造债券事实、不运行优化器、不触发真实交易
> 数据边界：以下数据库证据来自 2026-08-05 对本地 `db.sqlite3` 的只读审计，不代表生产环境状态；生产启动仍须重新取证

## 1. 本阶段结论

R5—R8 都具有部分基础代码，但没有一项同时满足备忘中的数据、研究和生产证据条件。因此本阶段不把任何能力标记为已启动：

| 能力 | 已具备的基础件 | 当前关键缺口 | 决策 |
|---|---|---|---|
| R5 固定收益相对价值与久期 | 宏观指标目录中有部分国债、信用收益率和资金利率代码；Data Center 已有 Publication 门禁；QW-5 可显式阻断 | 无两条已发布可靠曲线、无券级主数据/现金流/交易日历、无信用估值 Publication、无久期/凸性对账 | `blocked` |
| R6 高级状态模型 | Regime V2、PMI/CPI、Pulse 和简单转折规则可作为基准 | 未证明简单基准不足；无 PIT 训练证据、稳定标签协议、样本外转移准确率或政策反应函数基准 | `blocked` |
| R7 情景概率校准 | 情景版本、Signal Forecast Ledger、revision/set UUID 绑定、主观/模型概率分栏和显式 realization row score 已实现 | 无完整预测—复核—兑现样本，也没有经批准的 calibration sample policy | `blocked` |
| R8 多资产优化 | Portfolio 有目标组合、过渡计划、部分交易约束和 research-only 优化输入合约；Broker Execution 有成交/对账模型；Risk Center 有情景损失 | 无 Portfolio-owned canonical snapshot 持久真源；R3/R4/R5 未晋级；无真实执行反馈样本；尚未实现或运行优化器 | `blocked` |

`blocked` 是 fail-closed 业务状态，不等于代码缺陷，也不能通过页面、默认数据或 LLM 推断解除。

## 2. 审计证据边界

### 2.1 只读数据库证据

本地数据库审计显示：

- `data_center_canonical_publication` 当前没有可用于本次启动判断的 Publication；
- PIT fact/version manifest、Forecast Ledger entry/outcome、Research approved PromotionDecision 均没有可消费记录；
- Risk Center 新情景迁移尚未应用到该本地数据库，因此没有情景运行历史可评分；
- Portfolio transition plan、order intent、Broker account/position snapshot 和 fill 没有真实执行样本。

这些结果只能证明“当前本地环境不能作为启动证据”。未来即使出现非空记录，也仍须逐条验证 Publication、PIT、coverage、freshness、版本绑定、样本跨度和 PromotionDecision，不能以非空代替可用。

复核命令必须使用只读连接：

```powershell
@'
.headers on
.mode column
SELECT 'pit_fact_versions' AS metric, COUNT(*) AS value FROM data_center_pit_fact_version
UNION ALL SELECT 'pit_manifests', COUNT(*) FROM data_center_pit_dataset_manifest
UNION ALL SELECT 'canonical_publications', COUNT(*) FROM data_center_canonical_publication
UNION ALL SELECT 'forecast_entries', COUNT(*) FROM signal_forecast_ledger_entry
UNION ALL SELECT 'forecast_outcomes', COUNT(*) FROM signal_forecast_outcome
UNION ALL SELECT 'approved_promotions', COUNT(*) FROM research_promotion_decision WHERE decision='approved'
UNION ALL SELECT 'portfolio_transition_plans', COUNT(*) FROM decision_portfolio_transition_plan
UNION ALL SELECT 'order_intents', COUNT(*) FROM order_intent
UNION ALL SELECT 'broker_account_snapshots', COUNT(*) FROM broker_execution_account_snapshot
UNION ALL SELECT 'broker_position_snapshots', COUNT(*) FROM broker_execution_position_snapshot
UNION ALL SELECT 'broker_fills', COUNT(*) FROM broker_execution_fill;
'@ | sqlite3 'file:db.sqlite3?mode=ro'
```

### 2.2 源码证据

- Data Center 指标目录有 `CN_BOND_10Y`、`CN_BOND_2Y`、`CN_CORP_YIELD_AAA`、`CN_CORP_YIELD_AA` 和 `CN_DR007` 等代码，但目录项或历史 raw/canonical fact 不自动等于 Published 曲线。
- 本地 `asset_type=bond` 的资产是 ETF 兼容记录，不能冒充券级 Bond Master。
- `ScenarioRunEvidence` 已绑定 scenario revision、可选 scenario set revision、portfolio snapshot、数据证据和结果 hash，但尚未记录预测概率及期后兑现结果。
- `ForecastLedgerEntry` 已用稳定 UUID value reference 绑定 scenario revision/可选 set revision，并把 directional probability、subjective probability 与经 Research Promotion 批准的 model probability 分开；Risk Center checker 会验证 approved/active revision 及精确 set membership。
- Portfolio Domain 的 `PortfolioSnapshot` 是计算值对象；Portfolio Infrastructure 目前持久化的是 transition plan、order intent 和 planning policy，不是 canonical snapshot 真源。
- Portfolio 过渡计划已覆盖买入单位、费用、滑点、涨跌停、T+1 和成交量参与率等约束；这只证明约束算法存在，不证明参数经真实成交校准。

## 3. 统一 readiness 输入

以下 key 与 `research-capability-readiness.v1` 的 `ReadinessRequirement.value` 完全一致。只有 `verified` 能解除对应条件；`missing`、`unverified`、`stale` 或缺失证据一律使 capability decision 为 `blocked`、`can_start=false`。表中最后一列是 evidence 的 `blocking_reason` detail；机器 `reason_code` 由 `<capability>.<requirement>.<state>` 统一生成。

### 3.1 R5 固定收益相对价值与久期

| requirement key | 当前状态 | 证据 | `blocking_reason` detail |
|---|---|---|---|
| `publication_gate_available` | `verified` | Data Center canonical Publication/freshness 端口已存在 | — |
| `two_reliable_curves_published` | `missing` | 只有指标目录和未发布事实，未见两条独立曲线的 Published 成员、coverage 和 freshness 证据 | `r5_curves_not_published` |
| `credit_valuation_published` | `missing` | AAA/AA 仅有目录/适配能力，未见信用估值 Publication | `r5_credit_valuation_not_published` |
| `bond_master_complete` | `missing` | 当前 bond asset 兼容记录为 ETF，不含券级票息、到期日、计息规则等 | `r5_bond_master_incomplete` |
| `cash_flow_schedule_complete` | `missing` | 无券级 coupon/principal schedule 真源 | `r5_cash_flows_unavailable` |
| `fixed_income_trading_calendar` | `missing` | 无固收计息、付息、结算日历证据 | `r5_trading_calendar_unavailable` |
| `duration_convexity_reconciled` | `missing` | 无第三方或手工金样本对账 | `r5_duration_reconciliation_missing` |
| `fixed_income_research_only_scope` | `verified` | 备忘明确第一阶段只输出研究建议，不生成真实订单 | — |

R5 不得用单点宏观收益率拼接伪曲线，不得用 ETF 久期标签代替券级现金流，不得填充默认票息、到期日、信用等级或流动性。

### 3.2 R6 高级状态模型与政策反应函数

| requirement key | 当前状态 | 证据 | `blocking_reason` detail |
|---|---|---|---|
| `simple_regime_baseline` | `verified` | Regime V2 的 PMI/CPI 水平规则、现有 Regime/Pulse 转折提示可作为简单基准 | — |
| `simple_baseline_shortfall_proven` | `missing` | 未提供真实误判案例、误差分解或决策损失证据 | `r6_simple_baseline_shortfall_unproven` |
| `state_model_pit_inputs` | `missing` | 本地无 PIT fact/manifest 可复算训练集 | `r6_pit_training_evidence_missing` |
| `stable_state_label_protocol` | `missing` | 无跨窗口 label alignment、经济命名和 label-switching 处理协议 | `r6_stable_label_protocol_missing` |
| `oos_transition_benchmark` | `missing` | 无样本外转移准确率、持续期和简单规则对照 | `r6_oos_transition_benchmark_missing` |
| `policy_reaction_target_contract` | `missing` | 无政策目标变量、发布日期、修订和 benchmark 定义 | `r6_policy_reaction_contract_missing` |

现有 Regime 分布或转折分数只能按其当前规则语义使用，不能重新标成经过校准的 Markov/HMM 状态概率。

### 3.3 R7 情景概率校准、历史类比与路径模拟

| requirement key | 当前状态 | 证据 | `blocking_reason` detail |
|---|---|---|---|
| `governed_scenario_versions` | `verified` | 源码已定义不可变 scenario revision/set 和 run evidence；数据库应用状态需在目标环境另验 | — |
| `append_only_forecast_ledger` | `verified` | Signal Forecast Ledger、evaluation、outcome 和 Brier 字段已存在 | — |
| `scenario_version_ledger_binding` | `verified` | R7-C0 已新增 scenario revision UUID、可选 set revision UUID、Risk Center membership checker、复合索引与 DB 完整性约束；目标环境仍须应用迁移 | — |
| `subjective_model_probability_separation` | `verified` | subjective/model probability、各自 source version 与 model PromotionDecision 已独立持久化；未批准模型概率 fail closed | — |
| `complete_scenario_outcome_history` | `missing` | 本地无可评分 forecast outcome；ScenarioRunEvidence 也不是兑现结果 | `r7_complete_outcome_history_missing` |
| `calibration_sample_policy` | `missing` | 无最低样本量、分箱、horizon、删失和 class-balance 规则 | `r7_calibration_sample_policy_missing` |
| `historical_analogy_pit_manifest` | `missing` | 无历史类比 universe、特征版本和 PIT manifest | `r7_historical_analogy_manifest_missing` |

在上述条件解除前，禁止训练“情景概率模型”、输出校准曲线或把情景主观权重改写为模型概率。允许继续积累不可变的情景 revision/run evidence，但必须保留 `probability_source` 语义并记录期后复核。

### 3.4 R8 多资产优化与真实执行约束统一

| requirement key | 当前状态 | 证据 | `blocking_reason` detail |
|---|---|---|---|
| `portfolio_planning_constraints` | `verified` | Portfolio Domain 已覆盖 A 股、基金、债券和商品 typed rule，并在 weight-only 层无法证明数量/结算/保证金约束时稳定阻断 | — |
| `risk_center_scenario_input` | `verified` | Risk Center 已有情景影响及运行证据契约 | — |
| `portfolio_canonical_snapshot` | `unverified` | Portfolio 仅有 canonical snapshot class/repository 机制；机制存在不能替代目标环境中可由 owner 精确回读的真实 Portfolio-owned snapshot，因此 governance manifest 不再为该数据条件签署 `verified` | `r8_portfolio_canonical_snapshot_unverified` |
| `r3_promoted_factor_version` | `missing` | 无 approved R3 PromotionDecision | `r8_r3_not_promoted` |
| `r4_promoted_macro_risk_version` | `missing` | R4 依赖 R3，当前无可晋级的宏观风险暴露/协方差 | `r8_r4_not_promoted` |
| `r5_promoted_fixed_income_version` | `missing` | R5 数据门未通过 | `r8_r5_not_promoted` |
| `execution_feedback_reconciled` | `missing` | 本地无 broker snapshot/fill/reconciliation 样本可估计滑点、拒单和约束偏差 | `r8_execution_feedback_missing` |
| `optimizer_input_contract` | `verified` | Portfolio Domain/Application 已实现 13 类 typed payload、canonical owner、PIT/有效期、current/universe/path hash 和 R3/R4/R5 exact Promotion provider 校验；缺项、过期、冲突均 fail closed | — |
| `optimizer_baseline_fail_closed_policy` | `verified` | canonical owner 为 Portfolio；current、等权、资产风险平价、local-search 四候选必须完整可复算，不可行、矩阵异常、无法证明的市场数量约束和比较不完整均稳定 blocked。该机制 attestation 不证明任何真实 snapshot、Promotion 或执行反馈存在 | — |

R8 不得先实现一个只接受收益/协方差的展示型优化器，再让 Portfolio 或 Broker Execution 修补不可交易结果。

## 4. 分阶段实施

### M0：启动门禁（本阶段）

交付：

- Research Domain/Application 的统一 typed readiness definition、evidence、report 和 fail-closed evaluator；
- 本文的 R5—R8 requirement key、源码/数据库证据和 `blocking_reason` detail；
- 单元测试覆盖 missing、unverified、stale、future-dated、duplicate、blocked 和全 verified 证据；
- 无 API、TUI、MCP 写能力和模型运行入口。

退出标准：四项能力在证据不全时稳定返回 `blocked`，且报告所有阻断项，不采用“部分满足即 ready”。

### R5-F0：固收 Data Foundation

Owner：`data_center`，独立 plan/分支。

交付：

1. 债券主数据、现金流、交易/付息/结算日历的 canonical schema；
2. 至少两条曲线和信用估值数据集的 DatasetContract、provider binding、PublicationPolicy；
3. source observation、as-of、revision、unit 和 coverage 证据；
4. 同日对齐、缺口和 stale 时 fail closed；
5. 生产 shadow 与回滚证据。

退出标准：R5 数据类 requirement 全部 `verified`。目录项、raw fact 或人工 CSV 不单独构成退出证据。

### R5-F1：固收研究最小纵切

仅在 R5-F0 完成后新增 `fixed_income` App：

- Domain 只实现 Bond/CashFlow/Curve/Duration/Convexity 及纯计算；
- 先对少量金样本做应计利息、价格、久期、修正久期和凸性对账；
- Application 输出只读研究预览和 blocked evidence；
- 不实现订单生成、自动调仓、carry/roll-down 优化或信用组合优化；
- 新用户主任务只进入 TUI，不新增 Classic 页面。

2026-08-05 开发先行状态：在不解除 R5-F0 数据门禁的前提下，已完成 `fixed_income` App 的最小完整四层研究纵切。Domain 接受显式 Bond Master、settlement-specific CashFlow、交易日历、国债曲线、政策性金融债曲线、信用估值、融资/交易/流动性成本 Publication 引用，所有摘要为 64 位 SHA-256、所有 Decimal 必须 finite，Publication 到期边界按 stale 处理；实现 clean/dirty price、YTM、Macaulay/modified duration、convexity、carry、roll-down、期限/跨曲线利差纯计算。Application 缺任一版本输入、过期证据或金样本对账失败即返回 blocked，成功预览也固定 `research_only=true`、`must_not_execute=true`、`must_not_use_for_decision=true`。Infrastructure 仅提供 Data Center Publication/freshness adapter 与不可变 research result repository/migration；Interface 只有内部 presenter，未注册 URL/TUI。该代码允许先做可复算开发与积累证据，但不把本地金样本写成正式事实，不满足“两条可靠曲线 + 信用估值已发布”等 R5-F0 退出条件，因此 R5 capability 和 `r5_promoted_fixed_income_version` 仍保持 `blocked`。

2026-08-05 完成度审计后补充了组合级 R5 纵切：`fixed_income.domain.portfolio_risk` 与 Application use case 绑定 Portfolio-owned snapshot、可复算 budget policy、PIT manifest 和四类 canonical owner evidence，计算 DV01、CS01、convexity、可变现比例和流动性成本，支持显式 parallel/key-rate/steepener/flattening/credit widening stress，并封存逐持仓与总压力 P&L 恒等式。缺输入、错 owner/hash/as-of/currency、PIT 不完整、future/stale 或任一预算 breach 均稳定 blocked；输出仍固定 research-only。尚未实现历史分位、等级迁移、流动性溢价、曲线组合和结果晋级/持久化，也没有真实 Publication，因此 R5 总门禁不变。

2026-08-06 R5 relative-value Phase A 已完成此前四项软件缺口：owner-attested expected calendar/revision PIT 历史分位；formation-time taxonomy/cohort 五桶评级迁移；premium driver 与 once-only cost 分解；signed multi-leg curve/key-rate/steepener/flattening/butterfly/credit-spread portfolio、容量、流动性与 shortability 门禁。Composite 对多 subject raw liquidity 在同 cutoff/同 policy 现场重算，并逐项权威重读 Publication、BondMaster、CashFlow、Calendar、cohort、analytics 与 funding seal；owner 方向为 Data Center raw facts、fixed_income analytics/candidate/input set、Portfolio funding、Research policy。主代理复跑 `32 passed`，Luna Max 最终复核 P0/P1 为 0。该批不新增 ORM/migration/concrete provider/跨 owner UoW/Promotion/API/TUI/Celery/current/Portfolio-R8 consumer/order/execution；真实 Publication、PIT 样本、券级事实、容量/借券和外部对账仍缺，R5 总门禁不变。

2026-08-07 R5 relative-value Phase B1 已完成 fixed_income-owned append-only persistence 与 exact query：input receipt/result 两表、schema-only `0003`、strict typed codec、server-owned `recorded_at`、完整历史 evidence clock graph seal、Data Center/Portfolio/Research Application shared UoW，以及只接受 ID/version/cutoff 的 closure-bound writer。公开 Repository 不含写入口；伪造 Draft/capability、command/draft 或 owner graph 错配、事务键不一致、direct/bulk/related mutation、race fork、receipt→result 回滚失败和 raw header/payload/FK tamper 均 fail closed。Codec/component/migration 为 `15 / 23 / 2 passed`，Luna Max 最终复核 P0/P1 为 0。该批不新增 Research Promotion/retirement/rollback、active provider、API/TUI/Celery/current/Portfolio-R8 consumer/order/execution；真实 Publication、PIT 样本、券级事实、容量/借券和外部对账仍缺，R5 总门禁不变。

2026-08-07 R5 Promotion Phase A 已完成 Research-owned scope/policy/trial/decision/lifecycle 软件合同。Trial 精确配对 fixed_income B1 result 与唯一 Portfolio owner outcome，封存 OOS clocks、return/cost/drawdown/liquidity/capacity/credit-loss；Decision 与 Lifecycle Application 只接受 ID，在 shared UoW 动态重读全 owner graph。Authorization 绑定 decision/record/validity clocks；PROMOTE/RETIRE/ROLLBACK 完整重放且 rollback 只能 `stack[-2]`；active 每次 PIT 重读 policy/trial/FI/Portfolio/auth，任一替换/失效即不发布。完整 suite `26 passed`，Luna Max 最终复核 P0/P1 为 0。该批无 ORM/migration/concrete providers，不接 R8/current/execution；真实 Publication、OOS outcome、owner authorization、approved trial 和外部对账仍缺，R5 总门禁不变。

2026-08-07 R5 Promotion Phase B2a 完成 Portfolio-owned outcome persistence：`portfolio.0008` 为 schema-only、零 seed；ID-only writer 在 shared UoW 内经 fixed_income Application exact query 重读结果/owner seal/observation，Portfolio 仅保存研究 outcome，不创建跨 App ORM FK。严格 codec、server clock、PIT query、observation 唯一约束和 append-only/竞态/回滚/raw tamper 保护均已验证（unit/component/migration `12/9/3 passed`）。Research B2b 仍在实施，真实 OOS outcome、Publication、容量/借券与外部对账仍缺，R5 保持 `blocked`。

2026-08-07 R7 approved sample policy 完成 Research 两表 append-only ledger 与 `research.0005` migration。Scope/policy 全字段 canonical seal、UUID/clock/PIT/header/payload/reference tamper、server-clock/UoW、direct/bulk/save_base/delete、race/rollback 均 fail closed；production composition 在 Risk Center owner Application source 未接入前固定 unavailable，私有 test factory 才能注入 fake（unit/component/migration `8/12/4 passed`）。真实 approved audit、forecast/outcome history、calibration/path 结果与 Promotion/lifecycle 仍缺，R7 继续 `blocked`。
2026-08-07 R5 Promotion Phase B2b 完成 Research 五张 append-only ledger 与 `research.0006` migration。Artifact、decision receipt/bundle、lifecycle receipt/event 均由 shared-UoW/server-clock/ID-only closure 写入，fixed_income 与 Portfolio owner graph exact reread；future PIT、raw selector hiding、stream fork、append-only、race/rollback 均 fail closed。修复后 component `4 passed`、codec+migration `6 passed`；真实 approved trial、OOS outcome、owner authorization、Publication 与外部对账仍缺，R5 继续 `blocked`。
2026-08-07 R7 result persistence 完成 Research evidence graph、input receipt/result 两层 ledger 与 `research.0007` migration。Calibration、历史类比、路径 assessment 只从 shared-UoW exact owner evidence 现场重算；结果固定 research-only，禁止训练、发布概率、决策和执行。Unit/component/migration `4/7/3 passed`；真实 owner evidence、forecast/outcome history、Risk Center approved source 与 Promotion/lifecycle 仍缺，R7 继续 `blocked`。

2026-08-07 R2 Publication/Promotion 续批完成 Data Center taxonomy/calendar Canonical Publication/member gate 与 Research `0009` policy/decision/PROMOTE-RETIRE-ROLLBACK ledger。R2 unit `24 passed`、Data Center component `6 passed`、Research component `2 passed`、migration `2 passed`；无 seed/current/consumer/execution 接线，真实 Publication、两个市场周期和 owner authorization 仍缺，R2 继续 `blocked`。
2026-08-07 R6 qualification persistence/lifecycle 续批完成 schema-only `research.0008` assessment/authorization/event ledger、ID-only exact PIT/audit pagination 与终态 PROMOTE/RETIRE。新增 persistence/lifecycle 回归 `14 passed`；不替换 Regime、不产生决策/执行，真实 shortfall/PIT/OOS/stable label/owner authorization/monitoring/Promotion 仍缺，R6 继续 `blocked`。
2026-08-07 R3 governed read 续批完成 exact regime/OOS/trial/Promotion/monitoring 重放与现场复算；governed-read `10 passed`，runner/ledger regression `36 passed`；不发布 current，真实 vintage/代理资产/assignment/OOS/owner Promotion 仍缺，R3 继续 `blocked`。

2026-08-07 R7 result lifecycle 续批完成 `research.0010` Research-owner authorization/event/audit-snapshot 三本 append-only ledger、ID-only exact PIT apply、终态 retirement 与物化 snapshot manifest 审计分页。Audit 首屏锁定完整 PIT result graph，并在 manifest hash/restore 中封存 `result_persisted_at`；Promotion 仅表示内部研究记录晋级，始终禁止概率发布、决策和执行。Raw header/payload/FK substitution、hash-chain、ORM private shortcut、Collector 删除、race/rollback、签名 cursor 篡改/跨快照均 fail closed。新增 unit/component/migration `11/8/2 passed`，另有 `1 skipped` 的 PostgreSQL 双连接并发测试；既有 result + lifecycle 七文件回归 `35 passed, 1 skipped`。真实 owner authorization、forecast/outcome 历史和合格研究证据仍缺，R7 继续 `blocked`。

### R6-S0：简单基准缺口取证

Owner：`regime` + `research`。

先冻结 PMI/CPI/Regime/Pulse 简单基准，记录：

- 真实误判案例和影响的用户决策；
- 状态转折、持续期和置信度的样本外指标；
- 数据 vintage、切分、embargo 和 benchmark；
- 状态经济标签与失效条件。

没有明确改善目标时 R6 保持备忘状态。只有 R6-S0 通过，才允许开 Markov/HMM 或政策反应函数实验；实验结果必须走 Research Experiment/PromotionDecision，不能直接替换 current Regime。

2026-08-05 开发先行状态：S0 基准不足 evaluator 与外部高级状态 artifact evidence validator 均已实现。后者不训练模型，要求 `PROVEN` shortfall、完整 PIT、稳定经济标签、有效概率/转移/持续期、优于简单基准的 OOS 指标、policy target 和独立 artifact attestation；即使全部通过也固定 `must_not_replace_regime=true`。

2026-08-07 qualification evidence 已完成七指标同窗比较、预注册 family/split/embargo、S2 PIT/artifact/threshold exact replay、独立 derived metric bundle、政策反应系数与回归诊断。Study ID 由完整 body hash 派生，Application 只接受 ID/time 并逐 owner 重读；同 ID 重封、裸 `ACCEPTED`、provider substitution、公开 mint、future/stale/retired 均 fail closed。R6 相关回归 `57 passed`，Luna Max 最终复核 P0/P1 为 0。成功结果仍固定 research-only，仅允许人工晋级复核；真实 shortfall、PIT/OOS 数据、qualification persistence、monitoring/retirement/Promotion 均未完成，R6 总门禁不变。

### R7-C0：情景 Forecast Ledger 扩展

Owner：`risk_center` + `signal` + `audit`，独立 plan/迁移。

最小纵切只做证据积累：

1. 将 forecast entry 类型化绑定 scenario revision 和可选 set revision；
2. 分开保存 subjective probability 与 model probability，后者在模型未晋级时必须为空；
3. 保存 horizon、review date、invalidation、期后 outcome 和 PIT data version；
4. 评分口径按 scenario version 聚合，历史 revision 不被最新修订覆盖；
5. 无 outcome 或样本不足时只返回 `insufficient_evidence`，不输出模型概率。

在完整预测—复核—兑现记录达到经批准的样本策略之前，不进入 Brier calibration curve、历史类比或路径概率训练。

2026-08-05 实施状态：上述证据积累纵切已完成代码实现和 `signal.0010_scenario_forecast_binding` 迁移。Outcome 使用独立 `scenario_realized` 计算 subjective/model row-level Brier，绝不复用 directional `hit`；Application 可按精确 revision/set 与 probability source 查询不可变观测。当前没有回填历史 outcome、没有训练模型，也没有基于真实样本的 calibration evidence，因此 R7 总能力仍保持 `blocked`，等待真实 outcome 与获批样本策略。

同日进一步实现 research-only 校准与类比合同：在获批 policy 的样本量、coverage、类别支持、窗口和 expiry 全部通过时，分别计算 subjective/model binary Brier、multiclass Brier 和分箱命中率；历史类比强制 PIT manifest/as-of，路径/条件/转移概率只作为证据，invalidation 只生成 `dispatch_requested=false` 的 review intent。空 outcome 仍返回 `insufficient_evidence`，不会训练或补出模型概率。

2026-08-05 reminder 续批进一步完成 Research-owned append-only 人工复核 ledger/internal outbox。Intent 固定锚定 invalidation time，并封存 forecast observation、revision/set 与 probability policy hash；typed path evidence 按 period 绑定 conditional/transition identity。Lifecycle 只允许 `scheduled / due / escalated / acknowledged / expired`，internal pull 和 human-authorized ACK 均禁止自动审批、执行或外部发送。`research.0002_scenario_review_reminder_ledger` 为 schema-only、零 seed，保留 0001 既有研究记录。该能力只解决“证伪后提醒人工复核”的软件闭环，不提供模型概率，不解除 R7 `blocked`。

### R8-O0：Portfolio canonical snapshot 与执行反馈

Owner：`portfolio` + `broker_execution`，在 R3/R4/R5 晋级前可独立建设数据真源，但不得建设优化器。

交付：

- Portfolio-owned immutable canonical snapshot、content hash、as-of 和 position/cash version；
- Account、Risk Center、Strategy 通过 Application Protocol 消费，禁止跨 App ORM；
- transition plan/order intent 与 broker order/fill/reconciliation 的稳定关联；
- 计划值与真实成交的费用、滑点、成交率、拒单和约束原因对账；
- 现金需求、持仓上下限、流动性和各市场交易规则的版本化契约。

2026-08-05 R8-O0 实施状态：已新增 Portfolio-owned `portfolio_canonical_snapshot` 和 `portfolio_execution_feedback` 追加式真源及 `portfolio.0005_canonical_portfolio_snapshot_and_feedback` 迁移。Canonical snapshot 从 cash/positions owner evidence 的原始 observation time 推导 `as_of`，绑定各自 version、64 位内容摘要、逐持仓来源与估值时间；Account、Risk Center、Strategy 的后续消费者只能使用 Portfolio Application query protocol，不得读取该 ORM。Execution feedback 使用字符串稳定引用关联 snapshot、transition plan、order intent、broker client/order event/fill/reconciliation，不增加跨 App FK，并复算计划费用与真实费用差、成交率、买卖方向滑点、拒单和约束偏差。缺任一 broker event 或 reconciliation evidence、source digest 不一致、时间倒置或非有限数值均 fail closed。本纵切未生成或提交订单、未实现优化器，也没有把合成测试数据写入正式证据；在真实 snapshot/成交/对账样本形成前，`portfolio_canonical_snapshot` 与 `execution_feedback_reconciled` readiness 仍不得手工改为 `verified`。

### R8-O1：多资产优化最小纵切

只有 R3、R4、R5 均有 approved PromotionDecision，且 R8-O0 通过后才允许启动：

2026-08-05 已完成 O1 输入边界及受约束研究求解纵切：`OptimizerInputContract`、owner-attested evidence、promotion reference、canonical numerical problem、约束验证、等权/资产风险平价基准和 deterministic local search。Application 必须先通过现有 readiness gate，并逐项比对 snapshot、universe、所有 input hash、execution feedback 与 R3/R4/R5 promotion；非 PSD、不可行、过期或比较不完整均 blocked。求解器只报告 local stationary/iteration limit，明确禁止 global optimum 声明，全部输出固定 `must_not_execute=true`。

2026-08-06 O1/O2 无数据续批完成 13 类 typed 数值 payload、版本化 current baseline、Portfolio-owned 可投资 universe、四市场 `available_at` 规则、逐期 path drawdown、四候选完整性/argmin/守恒重算，以及 append-only result/lifecycle ledger。完整 problem/result/event graph 使用 Decimal/UTC canonical hash；Promotion 必须由 Research exact provider 重读，retirement/rollback 必须由 Portfolio owner authorization provider 重读。无法在 weight 层证明手数、T+1、基金结算、债券应计或商品保证金时稳定返回 blocker，不把近似权重当作可执行结果。`portfolio.0006` 为 schema-only、零 seed，只创建 result/lifecycle 两表；input set 虽封入 result evidence graph，但独立 canonical input receipt/provider 尚未建立。该实现不注册 API/TUI/Celery/订单或 transition plan，真实证据门仍保持 `blocked`。

2026-08-09 readiness/composition P1 收口：治理清单不再用 `CanonicalPortfolioSnapshot` class/repository 证明真实 `portfolio_canonical_snapshot`，运行时该 requirement 在没有 owner evidence 时保持 `unverified`；`optimizer_baseline_fail_closed_policy` 改由 Portfolio owner 以四候选/完整阻断测试签署机制 evidence。新增 production composition 组装 deterministic engine、append-only repository 和 lifecycle use case，但 canonical input-set、Research exact Promotion 与 Portfolio lifecycle authorization 均使用显式 unavailable provider；缺证据时在任何 result/lifecycle 写入前失败。独立 input receipt/concrete owner provider 继续作为后续 P1，真实 snapshot、晋级和 broker reconciliation 总门不变。

- 第一版离线 research-only；
- 明确等权和现有配置基准；
- 输入绑定 PIT manifest、portfolio snapshot、scenario set、factor covariance 和 constraint version；
- 不可行、非正定/病态矩阵、stale 或缺失输入时 fail closed；
- 输出目标组合草案及约束影子信息，不直接生成可执行订单；
- 经 Research PromotionDecision 和人工审批后，才可进入 Portfolio transition plan。

现有 implementation 只允许离线 comparison，不注册订单、transition plan 写入、API/TUI 或任务；fixture 中的“完整输入”不构成真实 R8-O0 或 R3/R4/R5 晋级证据。

2026-08-05 交叉复核整改补强了三条边界：R5 的曲线角色、币种和 curve kind 由 canonical semantic provider 给出，三类 publication/dataset/hash 身份必须独立且一致，持久结果封存输入/输出 hash 并在数据库层禁止用于决策；R7 的类比 cutoff/release lag、校准 horizon/censoring、路径 shock/state/sample/PIT provenance 必须精确一致；R8 canonical snapshot 必须由受治理的 cash/position owner 原始 payload 生成 digest，优化结果重算并封存 solver weight 下的宏观风险贡献。上述机制均保持 research-only。

## 5. 测试与门禁

M0 必须覆盖：

- readiness registry 不允许重复 capability/requirement key；
- 缺失 requirement 自动 `blocked`；
- 未知、跨 capability 和未来时间证据拒绝；
- 任一 `missing/unverified/stale` 使 decision 为 `blocked`、`can_start=false`；
- 只有所有必需项均 `verified` 才返回 `ready`；
- evidence reference 和 blocked reason 非空；
- R7 本地空账本不会生成概率模型或 calibration 输出；
- R8 在 R3/R4/R5 未晋级时不能单独变为 ready。

建议验证命令：

```bash
pytest tests/unit/research/test_capability_readiness.py -q
python scripts/check_mypy_regression.py apps/research/domain/capability_readiness.py apps/research/application/capability_readiness.py
ruff check apps/research/domain/capability_readiness.py apps/research/application/capability_readiness.py tests/unit/research/test_capability_readiness.py
black --check apps/research/domain/capability_readiness.py apps/research/application/capability_readiness.py tests/unit/research/test_capability_readiness.py
python scripts/verify_architecture.py --include-audit --format text
```

后续若新增 current/latest 决策面，必须同步 `governance/current_data_contracts.json`；若新增 Celery 批量计算任务，必须登记 `governance/celery_task_contracts.json`。本 M0 不新增上述运行面。

## 6. 明确非目标

- 不把规则分数、Regime 分布或 LLM 判断称为模型概率；
- 不从现有收益率点或默认利率插值生成“已发布曲线”；
- 不创建默认债券票息、到期日、现金流、信用等级和流动性；
- 不在 `factor` App 中复用股票横截面引擎冒充 R3/R4；
- 不在 R3/R4/R5 未晋级时运行多资产优化；
- 不新增 Classic Django 业务页面、raw MCP tool 或自动交易入口；
- 不因本地数据库非空就跳过 PIT、Publication、coverage 和 freshness 复核；
- 不触发 VPS 部署、数据库写入或生产状态变更。

## 7. 复核触发与交接

| 触发事件 | 复核范围 | 必需新增证据 |
|---|---|---|
| 固收 Data Center 数据集完成 Publication | R5 | 两曲线、信用估值、Bond Master、CashFlow、Calendar、对账 |
| 出现 simple Regime 真实误判取证 | R6 | 基准误差、PIT 样本、OOS 指标和稳定标签协议 |
| 情景 Forecast Ledger 积累完整 outcome | R7 | revision 绑定、概率来源、review/outcome、样本策略 |
| Portfolio canonical snapshot 与 broker feedback 稳定 | R8-O0 | snapshot/hash/as-of、fill/reconciliation、约束版本 |
| R3/R4/R5 获得 approved PromotionDecision | R8-O1 | promotion IDs、输入版本、基准、fail-closed policy |

每次复核必须重新生成 evidence report；不得手工把 capability status 改为 ready。解除门禁后仍需为对应能力新建独立阶段 plan 和 commit 组。
