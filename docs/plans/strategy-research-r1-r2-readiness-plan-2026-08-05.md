# R1/R2 策略研究能力启动门整改计划（2026-08-05）

> 状态：**R1 持久证据桥接、精确 baseline/Promotion 生命周期与 R2 expected-period coverage 已实现；真实数据和真实晋级证据仍缺失，R1/R2 能力保持 Blocked**
> 依据：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)
> 复核基线：`dev/refactor-scenario-governance-quick-wins`
> 本轮主任务：判断 R1 行业经营驱动与盈利预测、R2 市场结构与投资者资金流是否具备启动条件。
> 主结果：输出可审计的启动决定；证据不足时稳定 fail closed，不用页面、代理数据或默认值替代前置条件。

## 1. 执行结论

R1、R2 当前均不得进入真实 pilot 或生产消费阶段；R1 research-only 软件切片可继续收口，但不得据此发布业务预测。

- R1 的 QW-7 仍没有真实使用反馈、连续经营事实或真实预测误差历史；Data Center 已新增无 seed 的经营指标版本定义和 PIT observation 合约，但没有把“结构存在”解释为真实数据已具备。
- R2 已新增治理数据驱动的 actor/measure/source/proxy 定义、资产组 revision 与 PIT membership 合约；完整主体分类、两个市场周期覆盖和正式 Publication 仍未具备。
- Data Center 已具备 Publication 和 PIT 技术基座；技术路径存在不等于生产数据已经通过门禁。没有 production publication、coverage、manifest 和 as-of 证据时，相关条件保持 `unverified`。
- Research 已具备 R1 专用 exact PromotionDecision、trial seal 与 retirement/rollback 生命周期；但尚无真实 trial、approved decision 或 Valuation consumer，因此不能把软件门禁的存在解释为 R1 已 ready。

本轮已交付统一 typed readiness contract，以及 Data Center-owned 定义、append-only PIT writer/query facade、无 seed 迁移和 Equity-owned 可审计预测/季度偏差账本。账本只提供安全积累与复算结构，不包含行业公式、自动预测或默认业务数据；不得新增 Classic 页面，不发布盈利预测或“增量/存量/减量博弈”结论。

### 1.1 2026-08-05 数据基础实施状态

- R1：`OperatingMetricDefinition` 由治理数据定义 code/unit/frequency/source；`OperatingObservation` 强制区分 `observed_fact / human_assumption / model_inference`，且三类 lineage 互斥。
- R2：`InvestorFlowDefinition` 强制 measure semantics、单位、频率、来源与 proxy methodology；`AssetGroupRevision` 和 `PITAssetGroupMembership` 保存版本及双时间证据。
- Infrastructure 复用 `PITFactVersionModel` 与 `DjangoPITDataView`，不创建第二份事实真源；三张新表只保存治理定义，不包含业务分类 seed。
- Application 查询必须显式 `as_of_time`、`KnowledgeScope` 和 observation kind，不允许事实与假设混查。
- 这批代码让未来真实数据可以安全进入系统，但 R1/R2 readiness 仍因真实使用、coverage、Publication/PIT manifest 和研究验证证据不足而保持 `blocked`。

### 1.2 2026-08-05 R1 预测账本实施状态

- Equity 新增 immutable `OperatingForecastVersion`，保存 forecast key/version、as-of、季度 horizon、行业/公司、methodology 和稳定 content hash。
- 每个版本必须同时包含 `base / bull / bear`，每个情景都必须有 Data Center `research.operating_observation.v1` 的 latest-public、verified、`observed_fact` PIT 锚点；旧修订、未来不可知版本、人工假设或模型推断不能冒充事实。
- 假设逐项保存值、单位、理由和唯一 lineage；`observed_fact / human_assumption / model_inference` 在 Domain 与数据库约束中互斥，未内置行业公式、默认增长率或 LLM 预测。
- Sector append-only run 通过 `run_key/run_version` 进入 Equity，调用方不能提交自称可信的 run result；template/run identity、通用 driver PIT identity、cash flow 和三情景六阶段输出全部进入 v2 seal。
- 每个情景保存收入、净利润、现金流、可复算利润率，以及 Equity-owned typed 估值敏感性输入、输出、单位、方法版本和 source artifact hash。
- 季度 actual 到达后，账本一次性追加三情景对比，保存 revenue/profit/margin 的 signed error、absolute error 与适用的 absolute percentage error，并引用当时可知的 operating PIT actual evidence。
- v2 当前强制 research-only，旧的 decision-id-only checker 不能将预测标为 `valuation_consumable`。Research 已实现 PromotionDecision 对 forecast artifact hash、template run hash、owner、purpose、sensitivity evidence 和 trial result 的精确绑定；只有未来取得真实 approved decision 并另建 Valuation consumer 阶段后，才可考虑开放消费。
- 能力仍为 `blocked`：当前实现证明可安全积累数据，不证明任何行业 forecast 已有效、已晋级或可用于投资决策。

### 1.3 2026-08-06 R1 精确 baseline、trial 与 Promotion 实施状态

- Equity 新增强制 owner approval 的 baseline spec 合同、baseline artifact 和 trial result；预测、基线与 actual 使用独立 manifest，并按完整 period×metric 集合逐项配对，保留原始值、单位、误差和来源时间。
- Trial 预注册 canonical scope、calendar、metric set、样本窗口、比较指标、通过/失效条件以及 forecast/template-run/sensitivity seal；缺行、重复行、单位错配、未来知识或跨 scope 替换均 fail closed。
- Research 新增 R1 专用 typed policy/decision，而不是套用通用 Sharpe/FDR/DSR 规则；approved/rejected 都有稳定 receipt，生命周期支持 promoted、retired、rolled_back，并按 subject/industry/scenario/purpose/horizon/calendar/metric-set 隔离。
- Research 只通过 Equity Application query port 重读 canonical artifact/trial，active 查询会重验 policy、owner row、bundle receipt、hash chain 和 expiry；调用方不能用 decision id、自报 hash 或伪造 receipt 解锁。
- Equity 四张、Research 五张 append-only ledger 均由 schema-only、零 seed 迁移建立；当前没有 Valuation consumer、API/TUI/Celery 或生产读取接线。
- 能力仍为 `blocked`：真实 QW-7、连续经营事实、Production Publication、真实 trial/approved decision 均未到位。

## 2. 目标与非目标

### 2.1 目标

1. 把备忘中的 R1/R2 启动条件变成稳定、可测试的 requirement 与 owner 证据契约。
2. 明确区分 `verified / missing / unverified / stale`，缺项不得被中性值或请求时间补齐。
3. 每份 verified evidence 必须携带 canonical owner、可追溯引用、timezone-aware `observed_at` 和明确的 `valid_until`；未来时间证据被拒绝，评估时已过期自动转为 `stale`。
4. 只有所有 requirement verified 时，readiness 才可返回 `ready`；`ready` 只允许新建独立 pilot plan，不代表模型可直接晋级生产。
5. 保存当前代码审计的稳定 blocked reason，便于数据、产品反馈或研究纪律补齐后复核。

### 2.2 非目标

- 不创建 R1 盈利预测模型、行业公式、默认 base/bull/bear 假设或估值结果。
- 不创建 R2 投资者资金流综合分数、主观主体映射或交易信号。
- 不用当前行业/概念成分回填历史资产组。
- 不把 `CapitalFlowFact.main_net/retail_net` 解释为产业资本、外资、险资、公募等真实主体流量。
- 不把 ETF 份额变化、开户数或融资余额代理包装成真实主体净流入。
- 不绕过 Data Center Publication/PIT，不从 Equity/Sector/Research Application 直接读取其他 App ORM。
- 不新增 Classic Django 页面、raw MCP tool、Celery 任务、生产部署或 VPS 操作。

## 3. 架构边界

| 能力 | Canonical owner | 本阶段职责 |
|---|---|---|
| 启动门与研究晋级 | `research` | 保存通用 readiness schema，收集 owner-attested evidence，输出启动决定 |
| QW-7 真实使用反馈 | `risk_center`（当前 QW surface owner） | 提供真实任务、使用频次、失败案例和结果反馈，不由代码存在替代；产品 owner 变更时需更新 contract |
| 公司经营模型/预测评估规范 | `equity` | 定义一个行业 pilot 的 horizon、baseline、误差指标、假设分层和预测结果 |
| 行业 KPI 模板与比较语义 | `sector` | 定义行业业务口径，不保存 Data Center 第二份事实 |
| 经营事实、资金流事实、主体分类、单位、PIT membership | `data_center` | 保存事实、来源、Publication、revision、available-at 和覆盖证据 |
| 正式估值消费 | `valuation` | 只消费已批准预测，不生成经营假设 |
| 结构比较 | `sector` / `asset_analysis` | 只消费已发布事实和 PIT membership，输出描述性比较 |
| 资金流解释力验证 | `audit` / `research` | 检验样本外解释力，不反向改写 canonical fact |

Readiness Application 只能通过 Protocol 收集 owner evidence。它不得 import Data Center、Equity、Sector 或 Valuation Infrastructure。

## 4. R1 启动条件审计

| Requirement | Owner | 当前状态 | 仓库证据 | 稳定阻断原因 |
|---|---|---|---|---|
| QW-7 真实使用反馈 | `risk_center` | `missing` | `AssetGroupRevision`、`SensitivityTemplate`、`RunSensitivityWorksheet` 仅见于 `apps/risk_center/domain/quick_wins.py`、`apps/risk_center/application/quick_wins.py` 与单元测试；Quick Wins 计划明确真实端到端接线仍未完成 | `industry_earnings_forecast.quick_win_usage_feedback.missing` |
| 至少一个行业的连续、可审计经营事实 | `data_center` | `missing` | 未发现公司门店、同店销售、客单价、销量/吨价、培训人数/学费等 canonical operating-fact entity、catalog、Publication 或 repository | `industry_earnings_forecast.auditable_operating_fact_series.missing` |
| 财务事实 Publication/PIT | `data_center` | `unverified` | `FinancialFact.available_at`、financial Publication publisher/query 和 PIT manifest 基座已存在；没有本轮生产 publication/coverage/manifest 证据 | `industry_earnings_forecast.financial_publication_pit.unverified` |
| 估值事实 Publication/PIT | `data_center` | `unverified` | `ValuationFact.available_at` 与 published valuation query 已存在；没有本轮生产 publication/coverage/manifest 证据 | `industry_earnings_forecast.valuation_publication_pit.unverified` |
| horizon、误差指标与 baseline | `equity` | `missing` | 已实现 owner-approval-enforced baseline spec 合同、完整 period×metric 配对、独立 actual manifest、预注册 trial 和误差/失效门槛；尚无真实 owner approval receipt、样本与 trial 结果 | `industry_earnings_forecast.forecast_evaluation_spec.missing` |
| R1 绑定的 Research PromotionDecision | `research` | `unverified` | 已实现 R1 专用 exact forecast/run/sensitivity/trial binding、owner-authorized lifecycle 与 active replay；没有真实 R1 trial、approved decision 或 Valuation 读取证据 | `industry_earnings_forecast.research_promotion_gate.unverified` |

### 4.1 R1 可启动的最小 pilot

所有启动门 verified 后，另建独立计划和分支，只选择一个行业：

1. 先建经营 KPI 字典、单位、频率、来源、available-at 和 revision 契约。
2. 用一个简单 baseline（历史同期或经批准外部一致预期）作为基准。
3. 只输出 base/bull/bear 假设、收入/利润/利润率与估值敏感性；事实、人工假设和模型推断分层保存。
4. 按季度冻结预测并对 actual 记录 MAE/MAPE 或计划指定指标，不用后续修订数据回填历史。
5. 结果先保持 exploratory；只有 PIT trial 通过 Research PromotionDecision 后，Valuation 才能消费批准版本。

上述 pilot 的可审计账本与 Sector-owned 行业模板基础已先行实现。模板使用有限 typed AST、显式单位规则和六阶段 DAG，无业务 seed；运行时缺三情景 driver、verified PIT fact、单位一致性或有效模板即整体 blocked。真实行业公式、生产数据运行和 Valuation 消费仍不得启动，因为 QW-7、连续经营事实和 R1 approved PromotionDecision 均无证据。

## 5. R2 启动条件审计

| Requirement | Owner | 当前状态 | 仓库证据 | 稳定阻断原因 |
|---|---|---|---|---|
| 主体分类、定义、单位、频率、来源和修订规则 | `data_center` | `unverified` | 已实现版本化 actor taxonomy、series definition 与 append-only repository；尚无获批生产定义和真实主体覆盖 | `market_structure_investor_flow.flow_taxonomy_and_units.unverified` |
| 两个市场周期的 PIT 覆盖 | `data_center` | `missing` | Publication/PIT 基座存在，但没有按主体、周期、频率发布的 coverage manifest 或两轮周期验收证据 | `market_structure_investor_flow.two_cycle_pit_coverage.missing` |
| 自定义资产组 PIT membership | `data_center` | `unverified` | 已实现事件时间/知识时间分离的 exact membership snapshot 与 evidence hash；尚无目标资产组的 Production Publication | `market_structure_investor_flow.pit_asset_group_membership.unverified` |
| 代理指标显式标注 | `data_center` | `unverified` | series/observation 强制 proxy target 与 methodology；尚无覆盖目标主体的获批代理定义 | `market_structure_investor_flow.proxy_labelling.unverified` |
| 资金量、持仓变化、交易净流入严格区分 | `data_center` | `unverified` | typed `flow/holding/stock/transaction` 与底层 measure kind 不可互换，聚合会拒绝口径混合；尚无真实 series evidence | `market_structure_investor_flow.measure_semantics.unverified` |

### 5.1 R2 可启动的最小 pilot

所有启动门 verified 后，另建独立计划和分支，从两类口径最清晰、授权明确的主体开始：

1. 先定义 actor、measure kind、unit、frequency、gross/net、source、revision、available-at 和 proxy 标签。
2. 资产组成员使用 effective-from/effective-to 的 PIT membership，不以当前成员回填历史。
3. 第一阶段只输出总量变化、加速度、历史分位、覆盖率和跨主体差异。
4. 输出保持 `structure_description_only`，不自动变成交易信号。
5. Audit/Research 使用两个市场周期做样本外解释力验证；覆盖或口径不足时必须 blocked。

上述 pilot 的 schema、PIT 读取和描述性聚合机制已实现。版本化 expected-period calendar 现在是 coverage 的唯一期间来源，Application 对 request series × period 全量枚举；整期所有 series 都无可靠 observation 时显式 blocked，不再因没有记录而隐身。Calendar 无 seed、append-only，并封存 identity/frequency/as-of/active/expiry 与完整 hash。仍不得对外发布“增量/存量/减量博弈”结论：批准 taxonomy、真实 calendar、两个市场周期 PIT coverage manifest 和真实 series evidence 尚未满足。

## 6. Typed readiness contract

统一 contract 应至少支持：

```text
ResearchCapability
  ├─ industry_earnings_forecast
  └─ market_structure_investor_flow

ReadinessEvidence
  requirement
  owner
  state = verified | missing | unverified | stale
  observed_at (timezone-aware, <= evaluated_at)
  valid_until (verified 必需；<= evaluated_at 时自动 stale)
  evidence_ref (verified 必需)
  blocking_reason (非 verified 必需)

CapabilityReadinessReport
  contract_version
  evaluated_at
  decision = ready | blocked
  evidence[]
  blockers[] {requirement, owner, reason_code, detail}
```

R1 requirements：

- `quick_win_usage_feedback` — owner: `risk_center`（当前 QW surface owner）
- `auditable_operating_fact_series` — owner: `data_center`
- `financial_publication_pit` — owner: `data_center`
- `valuation_publication_pit` — owner: `data_center`
- `forecast_evaluation_spec` — owner: `equity`
- `research_promotion_gate` — owner: `research`

R2 requirements：

- `flow_taxonomy_and_units` — owner: `data_center`
- `two_cycle_pit_coverage` — owner: `data_center`
- `pit_asset_group_membership` — owner: `data_center`
- `proxy_labelling` — owner: `data_center`
- `measure_semantics` — owner: `data_center`

契约不得内置“当前已通过”的生产默认值。缺失 owner provider、证据引用或观测时间时自动 materialize `missing` blocker。

## 7. 验收标准

### 7.1 Readiness contract

- R1/R2 requirement set 有精确测试，新增或删除 requirement 必须显式评审。
- 空 evidence、缺少一项、`unverified` 或 `stale` 均返回 `blocked`。
- 全部 requirement verified 时才返回 `ready`，且 next step 仅为创建 bounded pilot plan。
- verified evidence 缺少 canonical owner、`evidence_ref`、timezone-aware `observed_at` 或 `valid_until` 时拒绝。
- future evidence、错误 owner、重复 requirement、跨 capability evidence 均拒绝。
- Application 通过 injected Protocol 收集证据，不直接碰其他 App ORM。

### 7.2 R1 pilot 前置验收

- 有一份真实 QW-7 使用反馈摘要，包含用户主任务、有效/无效案例和明确决策缺口。
- 至少一个行业的 KPI 字典、数据授权、单位、频率、available-at、revision 和覆盖报告通过 Data Center Publication/PIT。
- 财务与估值 production publication、member coverage 和 PIT manifest 可引用并可复算。
- horizon、baseline、误差指标、样本切分、失效条件和季度 actual 对账规则获得 owner 批准。
- R1 trial 到 PromotionDecision 再到 Valuation approved forecast 的权限和回滚路径已测试。

### 7.3 R2 pilot 前置验收

- 每一入选主体流的 actor、measure kind、单位、频率、source、revision 和 proxy 定义完成。
- 两个市场周期的 PIT coverage manifest 可引用，覆盖缺口不由代理或当前数据补齐。
- custom asset group membership 按版本和有效期保存并通过 Publication。
- 资金量、持仓变化与交易净流入在 schema 和输出中不可混淆。
- 无可靠数据时，所有结论保持 blocked；描述性结果不能自动晋级交易信号。

## 8. 测试与门禁

最小回归：

```bash
pytest tests/unit/research/test_capability_readiness.py -q
pytest tests/unit/equity/test_operating_forecast.py -q
pytest tests/component/equity/test_operating_forecast_repository.py -q
pytest tests/migrations/test_equity_operating_forecast_ledger_migration.py -q
pytest tests/unit/equity/test_forecast_baseline.py tests/unit/equity/test_forecast_baseline_application.py -q
pytest tests/unit/equity/test_forecast_baseline_codec.py tests/component/equity/test_forecast_baseline_repository.py -q
pytest tests/migrations/test_equity_forecast_baseline_ledger_migration.py -q
pytest tests/unit/research/test_r1_forecast_promotion.py tests/unit/research/test_r1_forecast_promotion_application.py tests/unit/research/test_r1_forecast_promotion_codec.py -q
pytest tests/unit/research/test_r1_forecast_promotion_lifecycle.py tests/unit/research/test_r1_forecast_promotion_lifecycle_application.py -q
pytest tests/component/research/test_r1_forecast_promotion_repository.py tests/component/research/test_r1_forecast_promotion_repository_hardening.py -q
pytest tests/migrations/test_r1_forecast_promotion_migration.py -q
pytest tests/unit/sector/test_industry_operating_template.py tests/component/sector/test_industry_operating_template_repository.py -q
pytest tests/migrations/test_sector_industry_template_migration.py -q
pytest tests/unit/data_center/test_market_structure.py tests/component/data_center/test_market_structure.py -q
pytest tests/migrations/test_market_structure_migration.py -q
python scripts/check_mypy_regression.py \
  apps/research/domain/capability_readiness.py \
  apps/research/application/capability_readiness.py \
  apps/equity/domain/operating_forecast.py \
  apps/equity/application/operating_forecast.py \
  apps/equity/infrastructure/operating_forecast_models.py \
  apps/equity/infrastructure/operating_forecast_repository.py \
  apps/equity/operating_forecast_composition.py \
  apps/data_center/application/research_data_foundation.py \
  apps/data_center/infrastructure/research_data_foundation_repository.py
ruff check apps/research/domain/capability_readiness.py \
  apps/research/application/capability_readiness.py
black --check apps/research/domain/capability_readiness.py \
  apps/research/application/capability_readiness.py
isort --check-only apps/research/domain/capability_readiness.py \
  apps/research/application/capability_readiness.py
python scripts/verify_architecture.py --include-audit --format text
```

若后续新增 current/latest readiness API 或 TUI 面，必须同步 `governance/current_data_contracts.json`，并覆盖 missing、stale、owner mismatch、future evidence 和 observation preservation。当前阶段不新增该决策面。

2026-08-05 交叉复核整改已把 R1 observed assumption 与 quarterly actual 逐字段绑定到 company/metric/value/unit 的 PIT fact；R2 actor/series 查询同时约束 effective、available、expiry 和 request as-of，并逐 series/period 封存 expected/observed/missing membership coverage。外部 source evidence 必须与 sealed payload 精确一致，Equity、Sector、Data Center PIT/R2 的 QuerySet/Manager 更新、批量更新和删除路径均 fail closed。以上机制仍不替代真实 Publication、两个市场周期 coverage 或 approved PromotionDecision。

2026-08-06 R1 精确 baseline/Promotion 续批验证：Domain/Application `80 passed`；Equity unit/component 合计 `99 passed`、migration `2 passed`；Research 拆分后 unit/component/migration 为 `48 / 24 / 3 passed`（unit+component 合计 `72 passed`）。相关生产文件增量 mypy 0 regression，Ruff、Black、isort、Equity/Research migration drift、Django system check、架构、业务配置和治理门禁均通过；Luna Max 最终只读复核无 P0/P1。以上仍不替代真实 owner approval、Publication、trial、approved decision 或 Valuation 消费授权。

2026-08-07 R2 Publication/Promotion 软件续批：Data Center taxonomy actor/series 与 period-calendar 已接入 Canonical Publication/member 精确 attestation，Research `0009` 已落地 policy/decision/PROMOTE-RETIRE-ROLLBACK append-only ledger、ID-only shared-UoW 与 PIT active replay。unit `24 passed`、Data Center component `6 passed`、Research component `2 passed`、migration `2 passed`；真实 taxonomy/calendar Publication、两个市场周期 coverage manifest 与 owner policy/authorization 仍缺，R2 继续 `blocked`。

2026-08-09 R2 两周期 trial/monitoring Phase A：新增纯 Domain/Application 的预注册解释力 trial 与 monitoring 合同。Policy 精确封存 taxonomy/calendar Publication projection、canonical series×period manifest、恰好两个完整且不重叠的市场周期、selection cutoff、指标/阈值、Holm-v1 与 invalidation；Audit outcome 与 monitoring facts 只能通过 ID-only exact provider 重读，coverage/denominator、adjusted p-value、stability 与 `delta_r2` 均现场派生。所有结果固定 descriptive/research-only，并强制禁止 predictive signal/current/decision/execution；targeted `31 passed`，独立复核 P0/P1/P2 均为 0。真实两周期数据、Publication、Audit outcome 与生产 provider 尚未形成，因此 readiness 不变。

## 9. 回滚

- Contract 回滚：移除 R1/R2 requirement 注册和对应测试，不修改任何事实、Publication、PIT manifest 或研究历史。
- Pilot 回滚：停止读取新 pilot version，保留不可变输入、预测和实际偏差记录；不得删除历史或切回 Python 静态假设。
- R1 读取回滚：Valuation 继续只消费现有已批准输入，未晋级预测保持 exploratory。
- R2 读取回滚：Pulse/Strategy 继续消费既有已发布聚合，不读取未验证主体流或 custom group 结果。
- 数据回滚：只回滚到已验证 Publication/version；禁止 destructive reset 或用最新事实覆盖历史 as-of。

## 10. 复核触发

出现任一以下证据后重新执行 readiness，而不是直接开始编码：

1. QW-7 完成真实用户任务并积累可引用反馈；
2. 一个行业经营 KPI 已进入 Data Center Publication/PIT；
3. R1 预测评估规范和 baseline 获得 owner 批准；
4. R2 主体 taxonomy 与 measure semantics 获得批准；
5. 两个市场周期的 R2 PIT coverage manifest 可复算；
6. custom asset group PIT membership 完成并通过 Publication。

每次复核必须保存 evidence ref 和 observed-at；“代码里有模型/字段”不能作为生产 readiness 证据。
