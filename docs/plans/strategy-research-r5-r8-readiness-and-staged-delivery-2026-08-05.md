# 策略研究 R5—R8 启动门禁与分阶段实施计划（2026-08-05）

> 状态：M0 启动条件审计完成；R7-C0 与 R8 输入合约纵切已实现，R5、R6、R7、R8 的能力门禁仍保持 `blocked`
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
| `portfolio_planning_constraints` | `verified` | Portfolio Domain 已覆盖部分 A 股数量、T+1、价格、流动性、费用和滑点约束 | — |
| `risk_center_scenario_input` | `verified` | Risk Center 已有情景影响及运行证据契约 | — |
| `portfolio_canonical_snapshot` | `missing` | 只有 snapshot 值对象和 legacy/account/broker 快照，Portfolio App 无 canonical snapshot repository/provider | `r8_portfolio_canonical_snapshot_missing` |
| `r3_promoted_factor_version` | `missing` | 无 approved R3 PromotionDecision | `r8_r3_not_promoted` |
| `r4_promoted_macro_risk_version` | `missing` | R4 依赖 R3，当前无可晋级的宏观风险暴露/协方差 | `r8_r4_not_promoted` |
| `r5_promoted_fixed_income_version` | `missing` | R5 数据门未通过 | `r8_r5_not_promoted` |
| `execution_feedback_reconciled` | `missing` | 本地无 broker snapshot/fill/reconciliation 样本可估计滑点、拒单和约束偏差 | `r8_execution_feedback_missing` |
| `optimizer_input_contract` | `verified` | Portfolio Domain/Application 已实现 versioned requirement、canonical owner、有效期、universe hash 和 R3/R4/R5 promotion reference 校验；缺项、过期、冲突均 fail closed | — |
| `optimizer_baseline_fail_closed_policy` | `missing` | 无等权/现有配置基准、不可行问题处理和矩阵异常策略 | `r8_optimizer_safety_policy_missing` |

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

### R6-S0：简单基准缺口取证

Owner：`regime` + `research`。

先冻结 PMI/CPI/Regime/Pulse 简单基准，记录：

- 真实误判案例和影响的用户决策；
- 状态转折、持续期和置信度的样本外指标；
- 数据 vintage、切分、embargo 和 benchmark；
- 状态经济标签与失效条件。

没有明确改善目标时 R6 保持备忘状态。只有 R6-S0 通过，才允许开 Markov/HMM 或政策反应函数实验；实验结果必须走 Research Experiment/PromotionDecision，不能直接替换 current Regime。

### R7-C0：情景 Forecast Ledger 扩展

Owner：`risk_center` + `signal` + `audit`，独立 plan/迁移。

最小纵切只做证据积累：

1. 将 forecast entry 类型化绑定 scenario revision 和可选 set revision；
2. 分开保存 subjective probability 与 model probability，后者在模型未晋级时必须为空；
3. 保存 horizon、review date、invalidation、期后 outcome 和 PIT data version；
4. 评分口径按 scenario version 聚合，历史 revision 不被最新修订覆盖；
5. 无 outcome 或样本不足时只返回 `insufficient_evidence`，不输出模型概率。

在完整预测—复核—兑现记录达到经批准的样本策略之前，不进入 Brier calibration curve、历史类比或路径概率训练。

2026-08-05 实施状态：上述证据积累纵切已完成代码实现和 `signal.0010_scenario_forecast_binding` 迁移。Outcome 使用独立 `scenario_realized` 计算 subjective/model row-level Brier，绝不复用 directional `hit`；Application 可按精确 revision/set 与 probability source 查询不可变观测。当前没有回填历史 outcome、没有训练模型，也没有 calibration 输出，因此 R7 总能力仍保持 `blocked`，等待真实 outcome 与获批样本策略。

### R8-O0：Portfolio canonical snapshot 与执行反馈

Owner：`portfolio` + `broker_execution`，在 R3/R4/R5 晋级前可独立建设数据真源，但不得建设优化器。

交付：

- Portfolio-owned immutable canonical snapshot、content hash、as-of 和 position/cash version；
- Account、Risk Center、Strategy 通过 Application Protocol 消费，禁止跨 App ORM；
- transition plan/order intent 与 broker order/fill/reconciliation 的稳定关联；
- 计划值与真实成交的费用、滑点、成交率、拒单和约束原因对账；
- 现金需求、持仓上下限、流动性和各市场交易规则的版本化契约。

### R8-O1：多资产优化最小纵切

只有 R3、R4、R5 均有 approved PromotionDecision，且 R8-O0 通过后才允许启动：

2026-08-05 已先完成 O1 的输入边界合约：`OptimizerInputContract`、owner-attested evidence、promotion reference 和 research-preview readiness。它不包含优化算法，且成功报告仍固定 `must_not_execute=true`；因此不会绕过 R8-O0、上游晋级或真实执行反馈门禁。

- 第一版离线 research-only；
- 明确等权和现有配置基准；
- 输入绑定 PIT manifest、portfolio snapshot、scenario set、factor covariance 和 constraint version；
- 不可行、非正定/病态矩阵、stale 或缺失输入时 fail closed；
- 输出目标组合草案及约束影子信息，不直接生成可执行订单；
- 经 Research PromotionDecision 和人工审批后，才可进入 Portfolio transition plan。

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
