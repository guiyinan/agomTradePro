# 策略研究能力路线图 R1—R8 执行状态（2026-08-05）

> 状态：R1—R8 第一批无数据先行研究纵切已实现；完整审计确认仍有无数据可开发 P1，且真实数据、生产 Publication、样本历史和真实 approved PromotionDecision 尚未形成，能力门禁均保持 `blocked`
> 来源：[策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)
> 适用分支：`dev/refactor-scenario-governance-quick-wins`
> 决策边界：本文件完成的是“能否启动”的可执行治理，不把缺少数据和研究证据的长期能力声明为完成。

## 1. 本轮结果

路线图要求每项能力在实施前满足数据可用性、Publication/PIT、研究验证和产品使用证据，并拆成独立计划。本轮已完成：

1. 将 R1—R8 的启动条件固化为 `research-capability-readiness.v1` typed contract。
2. 每个 requirement 绑定 canonical owner；非 owner 证据、未来时间证据、重复证据均被拒绝。
3. 缺失、未验证或过期证据统一 fail closed，并生成稳定 blocker code。
4. 为 R1/R2、R3/R4、R5—R8 分别建立独立阶段计划、边界、最小纵切、回归范围和回滚点。
5. 明确没有启动 Lasso/Nowcast、风险平价、固收定价、HMM、概率校准或优化器，也没有新增 Classic Web/TUI 占位任务。
6. 建立运行时 owner evidence registry；它只发布显式、限时、可定位到代码与契约测试的机制证据，其他 requirement 稳定物化为 `missing / unverified`。
7. 在不伪造数据的前提下，完成 R1/R2 治理定义与 PIT 写入、R7 scenario forecast binding，以及 R8 research-only optimizer input contract；这些纵切用于开始积累证据，不解除能力总门禁。
8. 继续交付 R1 三情景经营预测与误差台账、R5 固收研究内核、R6 简单基准不足取证器，以及 R8 canonical portfolio snapshot/执行反馈台账；所有缺数据入口均 fail closed。
9. 完成 R1 Sector 行业模板安全 AST/DAG、R2 市场结构研究证据、R3 独立 `macro_factor` App、R4 宏观风险候选验证、R6 外部高级状态证据验证、R7 校准/历史类比/路径研究，以及 R8 受约束确定性研究优化；这些实现均不生成生产数据、不训练缺证据模型，也不解除 readiness。
10. 完成三组 Luna Max 交叉复核并关闭全部 13 项 P1：所有研究结果均绑定 canonical input identity、PIT/as-of/coverage 或 owner evidence，追加式记录拒绝更新和删除；复核无 P0。
11. 对完整路线图重新执行三组 Luna Max 完成度审计，确认上一条只代表限定清单关闭；新审计无 P0，但发现 R1 bridge、R2 expected periods、R3 runner/output、R5 组合风险、R7 reminder outbox、R8 typed input/market constraints 等仍可无数据开发的 P1。
12. 本批先完成 R5 组合级 DV01/CS01/凸性/流动性风险预算及利率/信用压力测试，并修复 R4 exact-expiry 与完整 report seal。完整剩余队列见[完成度审计](strategy-research-capability-completion-audit-2026-08-05.md)。
13. 继续完成 R1 Sector→Equity 持久证据桥接、cash-flow/六阶段/template-run seal、通用 driver PIT 绑定与 legacy dual-read；完成 R2 版本化 expected-period calendar、series×period 完整 coverage 和整期全缺门禁。两项均保持 research-only/blocked，不使用 seed 或代理数据解除门禁。
14. 完成 R7 Research-owned append-only reminder ledger/internal outbox，精确绑定 forecast/revision/policy 与逐期 path evidence，并实现 deterministic due/ack/escalate/expiry；只允许内部人工 pull/ACK，明确禁止外发、自动审批与执行。
15. 完成 R3 exact-PIT historical-mean/FMP、nested temporal-CV runner、canonical artifact bytes、dated current/forward output ledger 和 append-only retirement lifecycle。所有产物继续三重 decision-blocked，不接 current、组合或执行链。
16. 完成 R8 13 类 typed 数值输入、current baseline、可投资 universe、四市场约束、path drawdown、四候选可复算比较及 append-only result/Promotion/retirement/rollback lifecycle；canonical provider 重读、Decimal/UTC hash 和无法证明的数量约束均 fail closed，未接 transition plan 或执行链。`portfolio.0006` 实际只持久化 result/lifecycle，独立 input receipt 尚未建立。
17. 完成 R1 owner-approval-enforced baseline spec、forecast/baseline/actual manifest 精确封存、完整 period×metric 配对 trial，以及 Research 专用 exact Promotion/retirement/rollback lifecycle；所有消费均从 canonical provider 重读，未用 fixture 解锁 Valuation。
18. 完成 R4 typed rolling/Regime exposure、等权/资产风险平价/宏观因子风险平价同窗 OOS 比较与 authoritative R3 attestation provider contract；所有形成时点和派生结果 fail closed、可复算，未新增持久化、晋级或生产消费入口。
19. 完成 R4 Portfolio-owned append-only receipt/result ledger、canonical typed replay、server-clock/UoW 写保护、covariance condition/rank/coverage diagnostics 和 exact PIT Application query；未实现 Research R4 Promotion/lifecycle 或下游激活。
20. 完成 R4 Research Promotion Phase A：stable semantic scope、selection 前预注册 policy、Portfolio/current-R3 exact trial seal、派生 decision、scope-local Promotion/retirement/rollback stack 与 PIT active provider；五表 ORM/migration 和 concrete providers 留给 Phase B。
21. 完成 R4 Research Promotion Phase B：五表 append-only ledger、schema-only `0004`、strict codec、server-clock policy registration、private UoW/insert claim、concrete providers/composition、并发 exact winner 与持久 lifecycle replay；未接 consumer/current/execution。
22. 完成 R5 relative-value Phase A：PIT spread percentile、rating migration、liquidity premium/cost decomposition、signed curve portfolio/capacity 与四组件 ID-only composite；逐 owner exact reread并现场重算 derived liquidity，未新增 persistence/Promotion/consumer。
23. 完成 R5 relative-value Phase B1：fixed_income 两表 append-only receipt/result ledger、strict codec、server clock、完整历史 evidence clock graph、跨 owner shared UoW、closure-bound ID-only writer 与 exact PIT query；未新增 Research Promotion/lifecycle/consumer/current/execution。
24. 完成 R6 qualification evidence：content-addressed study、S2 exact gate replay、独立 derived metric bundle、七指标同窗比较、政策反应系数/诊断与 ID-only authoritative qualification；仅允许送人工晋级复核，未新增 persistence/Promotion/current/Regime 接线。
25. 完成 R5 Promotion Phase A：content-addressed scope/policy/trial/decision/lifecycle、FI+Portfolio OOS owner seals、shared-UoW ID-only decision/event、PROMOTE/RETIRE/ROLLBACK stack 与 PIT active 动态重验；append-only Research persistence/concrete providers 留给 Phase B。
26. 完成 R8 readiness false-positive 与 production composition 收口：真实 `portfolio_canonical_snapshot` 不再由 class/repository 机制 attested，四候选 fail-closed policy 归 Portfolio owner；composition 可构造，但 canonical input-set、Research Promotion 与 Portfolio lifecycle owner source 缺失时显式 unavailable 且零写入。独立 input receipt/provider 继续列为软件 P1。
27. 完成 R2 两周期 explanatory trial/monitoring Phase A：Publication projection、canonical period manifest、Audit 因果、Holm-v1 与 monitoring freshness 均现场复算；结果固定 descriptive/research-only，不生成预测信号。
28. 完成 R6 monitoring Phase B：Research `0011` observation/assessment append-only ledger、strict codec、server-clock/UoW、exact PIT/audit 与 row-header seal；不自动退役、不激活模型或替换 Regime。
29. 完成 R8 canonical input receipt Phase B：Portfolio `0009` 独立 receipt、result v2 receipt binding、ID-only owner reread、Promotion 二次校验与 legacy explicit-only；真实 owner provider缺失时继续 blocked。
30. 完成 R3 inference chronology：训练/OOS 与发布 inference 分离，独立 label-free inference row、target calendar、exact manifest cutoff 和 trusted clock 进入 canonical request/artifact；不把历史 OOS 伪装为 fresh output。
31. 完成 R6 activation Phase A：exact qualification/monitoring/Promotion/authorization 动态重读后记录 internal ACTIVATE/RETIRE/ROLLBACK，rollback 仅允许 `stack[-2]`；无 persistence/consumer 接线。
32. 完成 R8 receipt DB integrity：Portfolio `0010` 精确约束 v1/v2/receipt shape，`0009` 安全逆迁守卫在检查前阻断并发写；无 seed/backfill。
33. 完成 R3 runner contract integrity：完整 spec/request typed semantics、manifest nested seals 与 exact built-in integer domain 进入 canonical replay，runner 无法用同 code 替换定义或引用漂移。
34. 完成 R6 activation Phase B：Research `0012` authorization/event/stream-commit/audit-snapshot ledger、trusted server-ledger cutoff、三方 stream completeness/projection replay、signed immutable audit 与 scope 双唯一序列；生产 mutation 保持 inert。
35. 完成 R8 无状态 production registration façade：runtime 对象图不保存任何真实 writer/UoW/provider/clock，owner provider 缺失时零写 blocked。
36. 完成 R3 authoritative runner-spec gate：command 只携 identity，Research owner provider 精确重读完整 spec，注册时点早于 selection；缺 provider、替换、未来或迟注册均在 runner/ledger 前阻断。通用 Registry 无法无损表达完整 spec，production 保持 unavailable。
37. 完成 R4 post-promotion monitoring Phase A：版本化 11 指标 policy、连续 period calendar、Portfolio raw facts 与 assessment 支持 healthy/breached/manual retirement review；Application 使用 ID/as-of-only shared-UoW owner reread，不自动 RETIRE、不接 current/consumer/execution。
38. 完成 R8 lifecycle 事务治理：严格 ID-only、repository server clock、result/stream/Promotion/authorization 同 UoW 双重重读、selector/UoW/race/fork fail-closed、完整 winner replay，以及 runtime repository/store/token 隔离。
39. 完成 R4 monitoring Phase B：Research `0013` 三张 schema-only append-only ledger、strict codec、同 DB UoW owner 重读、exact PIT、immutable audit snapshot 与确定性签名 cursor；production owner缺失时仍 unavailable。
40. 完成 R8 post-promotion monitoring Phase A：policy 精确绑定 active result/receipt/R8 与 R3/R4/R5 Promotion，11 项 owner metric payload按完整 calendar持续评价；只产生人工 retirement review，不自动改变 lifecycle。
41. 完成 R5 post-promotion monitoring Phase A：独立 raw projection封存七项指标分子/分母、canonical owner role/knowledge clocks和完整 period，identity-only shared-UoW evaluator只产生人工 retirement review。
42. 完成 R8 monitoring Phase B：Portfolio `0011` 三张 schema-only ledger、same-DB authoritative replay、clock-forward idempotency、assessment-scoped raw rows、exact PIT与immutable signed audit；production固定server clock。

## 2. 启动状态矩阵

| 能力 | 决策 | 解除阻断所需的核心证据 | 独立阶段计划 |
|---|---|---|---|
| R1 行业经营驱动与盈利预测 | `blocked` | 已有版本化行业模板、Sector→Equity 持久 bridge、三情景六阶段/cash-flow seal、owner-approval-enforced baseline contract、完整配对 trial 和 Research exact Promotion/lifecycle；仍需 QW-7 反馈、连续 PIT 事实、Production Publication、真实 owner approval/trial/approved decision，且未接 Valuation | [R1/R2](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| R2 市场结构与投资者资金流 | `blocked` | 已有 taxonomy/measure/proxy/PIT membership、版本化 calendar/coverage、Publication/Promotion，以及两周期 explanatory trial/monitoring 纯合同；仍需获批定义、真实 calendar、两个周期真实 PIT 覆盖、owner authorization、Audit outcome 与 concrete providers | [R1/R2](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| R3 高频宏观因子与 nowcast | `blocked` | 已有 exact PIT runner、concrete sklearn Lasso/OLS、逐 fold baseline/FMP/nested-CV、authoritative spec identity/provider gate、独立 label-free inference/target calendar、完整 spec/request/manifest canonical seal、dated outputs、governed read 和 retirement lifecycle；仍需完整 spec persistence owner、真实 inference Publication/calendar、宏观 vintage/代理资产 PIT、benchmark/cost、Regime/OOS trial 与 exact Promotion | [R3/R4](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| R4 宏观敞口与风险平价 | `blocked` | 已有 rolling/Regime/三方法同窗、Portfolio ledger/query、covariance diagnostics、Research 五表 ledger、scope/policy/trial/decision/lifecycle/active provider、concrete composition 与 monitoring Phase A+B 三表持久化；仍需真实 R3 晋级、canonical inputs、monitoring owner facts/composition、owner authorization、OOS trial 和下游 active consumption 验收 | [R3/R4](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| R5 固收相对价值与久期 | `blocked` | 已有定价/久期/曲线/信用、PIT 分位、评级迁移、流动性分解、signed curve portfolio/capacity、fixed_income/Portfolio/Research append-only owner ledgers、exact query/cross-owner UoW、Promotion/retire/rollback及monitoring Phase A；仍需monitoring persistence/owner composition、真实 Publication、PIT/OOS、券级事实、容量/借券、authorization、外部对账和下游验收 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R6 高级状态模型 | `blocked` | 已有简单基准不足、高级证据、qualification/lifecycle ledger、monitoring Phase A+B persistence 及 activation/`stack[-2]` rollback Phase A+B ledger；仍需真实不足/PIT/OOS/稳定标签/政策目标、canonical owner adapters、owner authorization、真实 Promotion 与生产 consumer 验收 | [R6](r6-simple-baseline-shortfall-and-state-model-staged-delivery-2026-08-05.md) |
| R7 情景概率校准 | `blocked` | 已有 source-separated Brier/分箱、PIT 类比、逐期路径证据、reminder/sample-policy/result/lifecycle append-only ledger 与审计 snapshot；仍需完整 outcome 历史、真实 Risk Center owner source/approved policy、真实合格 result/authorization 和生产接线 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R8 多资产优化 | `blocked` | 已有 canonical snapshot/反馈 schema、13 类 typed 输入、四候选比较、独立 input receipt、exact DB version/receipt constraints、ID-only shared-UoW/server-clock lifecycle、post-promotion monitoring Phase A+B、fail-closed composition 与无状态 production façades；仍缺canonical monitoring owner、真实 Portfolio snapshot、broker reconciliation、约束校准及 R3/R4/R5 晋级版本 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |

## 3. 可执行启动门

代码入口：

- Domain：`apps/research/domain/capability_readiness.py`
- Application：`apps/research/application/capability_readiness.py`
- Owner registry：`apps/research/application/capability_readiness_registry.py`
- Runtime attestation loader：`apps/research/infrastructure/capability_readiness_attestations.py`
- Composition：`apps/research/composition.py`
- Governed attestations：`governance/research_capability_mechanism_attestations.json`
- Tests：`tests/unit/research/test_capability_readiness.py`、`tests/unit/research/test_capability_readiness_registry.py`、`tests/component/research/test_capability_readiness_runtime.py`

Application 只依赖 owner evidence provider Protocol，不读取其他 App ORM。证据规则如下：

- `verified` 必须包含 canonical owner、timezone-aware `observed_at`、非空 `evidence_ref` 和明确的 `valid_until`；评估时已过期会自动转为 `stale`；
- `missing / unverified / stale` 必须包含阻断原因；
- 任何 requirement 缺项都会被物化为 `missing`，不得默认为 ready；
- readiness `ready` 只允许创建独立 pilot plan，不等价于生产晋级；
- 模型结果进入决策面仍须遵守对应 Publication/PIT、Research PromotionDecision、freshness 和人工确认契约。

### 3.1 已接线的机制证据

以下项目只是“平台机制存在且契约测试可定位”，不是对应数据、模型或生产运行已经 ready：

| Owner | 已签署的机制 requirement | 证据边界 |
|---|---|---|
| `data_center` | `publication_gate_available` | Publication fail-closed 用例与测试；不代表任一目标数据集已发布 |
| `research` | `experiment_registry`、`multiple_test_family`、`promotion_decision`、`split_and_embargo_policy` | 通用研究完整性机制；不代表 R1/R3/R4/R5 等已有 approved trial |
| `risk_center` | `governed_scenario_versions`、`subjective_model_probability_separation`、`risk_center_scenario_input` | 版本、概率来源分栏和只读矩阵输入契约；不代表已有校准样本 |
| `signal` | `append_only_forecast_ledger`、`scenario_version_ledger_binding` | append-only writer、scenario revision/set 绑定与不可变性测试；不代表已有完整 outcome 历史 |
| `portfolio` | `portfolio_planning_constraints`、`optimizer_input_contract`、`optimizer_baseline_fail_closed_policy` | transition planning、research-only 输入门禁和四候选 fail-closed 比较机制；`portfolio_canonical_snapshot` 是真实 owner 数据条件，不再因 class/repository 存在而 attested，也不代表真实组合样本、上游晋级或执行反馈已形成 |
| `fixed_income` | `fixed_income_research_only_scope` | 固收结果强制研究专用且禁止决策/执行；不代表目标曲线、信用数据或久期凸性外部对账已完成 |
| `regime` | `simple_regime_baseline` | 简单四象限基准与测试；不代表高级状态模型具有增量价值 |

每份 `verified` 机制证据必须从治理清单读取固定 `observed_at / valid_until / evidence_ref`。运行时不会把 `valid_until` 延后；到期后 Domain gate 自动转为 `stale`。清单未签署的同 owner 条件返回 `unverified`，没有适配器的 owner 返回 `missing`。

## 4. 当前证据边界

2026-08-05 对本地开发数据库的只读盘点为：

| 证据对象 | 本地数量 |
|---|---:|
| PIT fact version | 0 |
| PIT dataset manifest | 0 |
| Forecast ledger entry | 0 |
| Forecast outcome | 0 |
| Approved PromotionDecision | 0 |

这些数字只证明本地开发环境无法解除相关启动门，不代表生产环境状态。未来复核必须由 canonical owner 重新提供目标环境证据，且非空记录仍需验证 coverage、freshness、PIT、版本绑定和样本跨度。

当前尚未接线运行时 readiness evidence 的 owner 为 `equity`、`macro_factor`、`policy`、`audit`、`broker_execution`。`macro_factor` 与 `fixed_income` 均已建立独立四层 research-only App，但代码和迁移的存在不等于真实数据、benchmark 或 PromotionDecision 已验证。所有数据覆盖、Production Publication、晋级版本和样本历史 requirement 仍保持 `unverified`，运行时不查询空表，也不以模型或迁移存在推断 `verified`。

## 5. 后续触发与执行顺序

1. Owner 补齐某项 requirement 后，只重跑对应 capability gate；不得批量把其他条件改成 verified。
2. 全部 requirement verified 后，新建该能力的独立 `dev/*` 分支和 pilot plan。
3. Pilot 先交付最小研究纵切和 benchmark，保持 exploratory。
4. 通过 Research PromotionDecision 后，才允许接入下游决策面；用户主任务只进入 TUI，不新增 Classic 页面。
5. R4 必须等待 R3 晋级；R8 必须等待 R3、R4、R5 晋级；R7 必须先形成完整情景版本—预测—复核—兑现历史。

## 6. 回归与回滚

最低回归：

```powershell
pytest tests/unit/research/test_capability_readiness.py -q
pytest tests/unit/research/test_capability_readiness_registry.py tests/component/research/test_capability_readiness_runtime.py -q
python scripts/check_mypy_regression.py apps/research/domain/capability_readiness.py apps/research/application/capability_readiness.py apps/research/application/capability_readiness_registry.py apps/research/infrastructure/capability_readiness_attestations.py apps/research/composition.py
python scripts/verify_architecture.py
```

本批次还应运行 R1/R2/R3/R4/R5/R6/R7/R8 新增的 unit/component/migration 测试，以及 `makemigrations data_center equity fixed_income macro_factor portfolio sector --check --dry-run`。任何真实数据依赖缺失应表现为 blocked/insufficient evidence，而不是用测试 fixture 推断生产 ready。

2026-08-05 初轮联合验证结果：R1—R8 相关 unit/component/migration 共 `158 passed`。Luna Max 交叉复核整改后，从路线图首个提交至当前 HEAD 自动收集 57 个实际测试模块，最终联合回归为 `432 passed`；上述六个 App 均 `No changes detected`，Django system check、43 个 current-data surface、架构边界（2146 files / 0 violations）、业务配置硬编码和 test-tier inventory 全部通过。

2026-08-05 R1/R2 无数据续批验证：R1 unit/component/migration 为 `15 / 10 / 3 passed`，R2 为 `18 / 6 / 2 passed`；主代理联合复跑 unit `27 passed`、component `13 passed`。增量 mypy 14 个生产文件 0 regression，三 App 无 migration drift，Django system check、43 个 current-data surface、架构边界（2150 files / 0 violations）及业务配置硬编码门禁均通过。测试只证明软件合同，不替代 Production Publication、真实 calendar、两个市场周期或 PromotionDecision。

2026-08-05 R7 reminder 续批验证：主代理独立复跑 unit/component/migration 为 `18 / 11 / 2 passed`，8 个生产文件增量 mypy 0 regression；Research 无 migration drift，Django system check、44 个 current-data surface、架构边界（2155 files / 0 violations）、业务配置、governance consistency 与 Celery contracts 均通过。结果仍是 research-only 内部提醒软件证据，不替代真实 forecast/outcome history 或 sample policy。

2026-08-05 R3 runner 续批验证：主代理独立复跑 unit/component 为 `32 / 11 passed`，实现 agent 迁移测试 `1 passed`；16 个生产文件增量 mypy 0 regression，Macro Factor 无 migration drift，Django system check、45 个 current-data surface、架构边界（2168 files / 0 violations）、业务配置与 governance consistency 均通过。软件可复算不替代真实 vintage/price/cost/benchmark、OOS trial 或 exact Promotion attestation。

2026-08-06 R8 governed optimization 续批验证：主代理独立复跑 unit/component/migration 为 `21 / 11 / 2 passed`；19 个生产文件增量 mypy 0 regression，Portfolio 无 migration drift，Ruff/Black/isort、Django system check、45 个 current-data surface、架构边界（2182 files / 0 violations）、业务配置、governance consistency 与 Celery contracts 均通过。Luna Max 最终只读复核无 P0/P1；软件证据不替代真实 R3/R4/R5 Promotion、Portfolio snapshot、broker reconciliation 或约束校准。

2026-08-06 R1 精确基线与晋级续批验证：Domain/Application `80 passed`；Equity unit/component 合计 `99 passed`、migration `2 passed`；Research unit/component/migration 为 `48 / 24 / 3 passed`。相关生产文件增量 mypy 0 regression，Ruff、Black、isort、Equity/Research migration drift、Django system check、架构边界、业务配置和 governance consistency 均通过，Luna Max 最终只读复核无 P0/P1。软件证据不替代真实 QW-7、Production Publication、连续经营事实、真实 trial 或 Valuation 消费授权。

2026-08-06 R4 rolling 续批验证：主代理复跑新增合同/服务/Application 与既有 R4 candidate 共 `29 passed`，实现代理另复跑相关 R8 `15 passed`；5 个生产文件增量 mypy 0 regression，Ruff、Black、isort、架构边界、业务配置和 governance consistency 均通过。Luna Max 两轮定点复核关闭 selection/validation 因果、协方差 estimation-window 穿越和派生 artifact 伪造后无 P0/P1；软件证据不替代真实 R3 Promotion、canonical inputs、历史 OOS 或 R4 lifecycle。

2026-08-06 R4 persistence/query 续批验证：主代理独立聚合复跑 unit/component/migration `43 passed`；11 个生产文件增量 mypy 0 regression，Ruff、Black、isort、Portfolio migration drift、架构边界、治理、业务配置和模块循环均通过。Luna Max 最终复核关闭非 canonical UTC、caller self-attestation、server-clock/UoW、coverage denominator 和 provenance 冲突后无 P0/P1；软件证据不替代真实 inputs、Research R4 Promotion/lifecycle 或下游消费授权。

2026-08-06 R4 Promotion Phase A 验证：主代理复跑 `29 passed`；10 个生产文件增量 mypy 0 regression，Ruff、Black、架构边界、业务配置与模块循环均通过。Luna Max 最终复核 stable scope/exact seal/prereg cutoff/dynamic R3/derived decision/UoW/stack rollback/active replay 后无 P0/P1。Phase B 五表、concrete providers、真实 trial 和 active downstream 仍未完成。

2026-08-06 R4 Promotion Phase B 验证：Phase A + codec `38 passed`，Phase B component `13 passed`，migration `4 passed`；7 个生产文件增量 mypy 0 regression，Black/Ruff、2236-file 架构边界、988-file 业务配置、模块循环与 `makemigrations --check --dry-run` 均通过。Luna Max 最终复核 server-clock preregistration、五表 exact seals、append-only/UoW、atomic rollback、raced winner、fork/tamper 与 dynamic PIT 后 P0/P1 均为 0；真实数据和下游消费仍未完成。

2026-08-06 R5 relative-value Phase A 验证：主代理独立复跑 `32 passed`；7 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界/增量审计、业务配置与模块循环均通过。Luna Max 最终复核 PIT/calendar/revision、rating denominator、liquidity premium/cost、curve topology/risk/cash/capacity、multi-subject liquidity cross-proof、owner graph 与 nested exact reread后 P0/P1 均为 0；Phase B/真实数据仍未完成。

2026-08-07 R5 relative-value Phase B1 验证：codec `15 passed`、component `23 passed`、migration `2 passed`；7 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界/增量审计、业务配置、模块循环与 migration drift 均通过。Luna Max 最终复核 public read-only repository、closure writer、command/draft/owner/UoW binding、historical evidence clocks、append-only ORM、race/rollback 与 strict tamper detection 后 P0/P1 均为 0；Research Promotion/lifecycle、真实数据和下游消费仍未完成。

2026-08-07 R6 qualification evidence 验证：R6 相关回归 `57 passed`；2 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界/增量审计、业务配置与模块循环均通过。Luna Max 两轮攻击复核关闭 content-addressed study、S2 PIT/artifact/threshold replay、derived bundle exact reread、公开 mint 与七指标完整性问题后 P0/P1 均为 0；真实数据、persistence、monitoring 与 Promotion lifecycle 仍未完成。

2026-08-07 R5 Promotion Phase A 验证：完整 suite `26 passed`；9 个生产文件增量 mypy 0 regression，Black/Ruff、架构边界、业务配置与模块循环均通过。Luna Max 最终复核 FI/Portfolio outcome exact binding、shared-UoW、authorization clocks、ID-only lifecycle、stack[-2] rollback、expired RETIRE 与 active dynamic reread 后 P0/P1 均为 0；Phase B persistence、真实 trial/authorization 和下游消费仍未完成。

2026-08-07 R5 Promotion Phase B2a 验证：Portfolio-owned outcome ledger 的 codec/component/migration `12/9/3 passed`；增量 mypy 0 regression，Ruff/Black、架构边界与 migration drift 通过。Outcome 只由 Portfolio 持有，跨 fixed_income 仅经 Application exact query；同 observation 唯一约束、server clock/UoW、append-only guards、race/rollback/raw tamper 均 fail closed。Research B2b、真实 OOS outcome、owner authorization 与下游消费仍未完成。

2026-08-07 R7 approved sample policy 验证：unit/component/migration `8/12/4 passed`；6 个生产文件增量 mypy 0 regression，Ruff/Black/isort、`makemigrations research --check --dry-run` 通过。两表 ledger 只接收 ID/version/cutoff，owner evidence 通过 Risk Center Application port/concrete adapter 在 shared UoW 中重读；UUID、scope-policy coherence、PIT/header/payload/reference tamper、append-only、race/rollback 均 fail closed。生产 composition 在真实 owner source 缺失时固定 unavailable，真实 approved audit、forecast/outcome history 与 calibration evidence 尚缺，R7 仍 blocked。
2026-08-07 R5 Promotion Phase B2b 验证：Research `0006` 五张 append-only ledger 已落地；artifact registration、decision/lifecycle receipt→child、fixed_income/Portfolio exact reread、server-clock/shared-UoW、future PIT cutoff、raw selector recovery、stream fork、race/rollback 与 private append surface 均 fail closed。修复后 component `4 passed`、codec+migration `6 passed`；真实 trial/OOS/owner authorization/Publication 仍缺，R5 仍 blocked。
2026-08-07 R7 result persistence 验证：Research `0007` evidence graph + input receipt/result ledger 已落地；ID-only writer 现场重算 calibration/analogy/path，strict typed codec、exact PIT/future gate、header/payload/transition tamper、append-only、race/rollback 均 fail closed。Unit/component/migration `4/7/3 passed`；真实 owner evidence、forecast/outcome history、approved source 与 Promotion 仍缺，R7 仍 blocked。

2026-08-07 R2 Publication/Promotion 验证：Data Center Canonical Publication/member gate 与 Research `0009` 三本 append-only ledger 已落地；R2 unit `24 passed`、Data Center component `6 passed`、Research component `2 passed`、migration `2 passed`。ID-only/shared-UoW/PIT active replay 动态重读 Publication、policy、decision/lifecycle authorization，未接 current、consumer 或 execution；真实 taxonomy/calendar Publication、两个市场周期和 owner authorization 仍缺，R2 仍 blocked。
2026-08-07 R3 governed read 验证：exact regime assignment/OOS segment/trial family/Promotion/monitoring 重放与复算已落地；governed-read `10 passed`，runner/ledger regression `36 passed`。结果固定 research-only，真实宏观 vintage、代理资产、Regime assignment、OOS trial 和 owner Promotion 仍缺，R3 仍 blocked。
2026-08-07 R6 qualification persistence/lifecycle 验证：schema-only `research.0008` assessment/authorization/event ledger、ID-only exact PIT/audit pagination 与 PROMOTE/RETIRE 终态生命周期已落地；新增 persistence/lifecycle 回归 `14 passed`。无 Regime replacement、decision 或 execution 接线；真实 shortfall/PIT/OOS/stable label/owner authorization/monitoring/Promotion 仍缺，R6 仍 blocked。
2026-08-07 R7 result lifecycle 验证：Research `0010` exact authorization/event/audit-snapshot ledger、ID-only PIT apply、terminal retirement 与物化 snapshot manifest 审计分页已落地。Audit 锁定完整 result graph 后物化并封存 `result_persisted_at`；Promotion 只表示内部研究记录晋级，禁止概率发布、决策和执行。Header/payload/FK/hash-chain、ORM private shortcut、Collector 删除、race/rollback、签名 cursor 篡改/跨快照均 fail closed。新增 unit/component/migration `11/8/2 passed`，另有 `1 skipped` 的 PostgreSQL 双连接并发测试；既有 result + lifecycle 七文件回归 `35 passed, 1 skipped`。真实 owner authorization、forecast/outcome 历史和合格研究证据仍缺，R7 仍 blocked。

2026-08-09 R3/R6/R8 无数据收口验证：R3 Macro Factor unit最终 `133 passed`，完整 spec/request/manifest seal、exact-int 边界与 Domain 模块拆分通过；R6 activation Phase B targeted `42 passed`，独立空 SQLite 实迁移 `research.0012` 成功且四 ledger `0/0/0/0`；R8 inert registration façade定点 `2 passed` 且对象图无 writer/UoW/provider/clock。相关增量 mypy 0 regression，Ruff/Black/isort、large-file governance 与 migration drift 通过。真实 owner/data/Publication/PIT/trial/Promotion/对账仍未形成，三项继续 `blocked`；R6/R8 的真实 PostgreSQL 并发为上线前未验证项。

完整路线图审计后的 R4/R5 增量批次另行复验 fixed-income 全部 unit/component 与 R4 macro-risk，共 `49 passed`；增量 mypy/ruff/black、Django check、架构边界（2148 files / 0 violations）、业务配置硬编码和 43 个 current-data surface 均通过。

回滚点按 R1、R5、R6、R8 四个独立提交组切分。新增迁移只建立 append-only 研究台账与 canonical snapshot/反馈存储；没有任务注册、API/MCP/TUI 发布，也不把研究结果接入现有决策或执行路径。
