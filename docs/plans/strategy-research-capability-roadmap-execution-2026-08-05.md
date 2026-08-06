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
16. 完成 R8 13 类 typed 数值输入、current baseline、可投资 universe、四市场约束、path drawdown、四候选可复算比较及 append-only result/Promotion/retirement/rollback lifecycle；canonical provider 重读、Decimal/UTC hash 和无法证明的数量约束均 fail closed，未接 transition plan 或执行链。
17. 完成 R1 owner-approval-enforced baseline spec、forecast/baseline/actual manifest 精确封存、完整 period×metric 配对 trial，以及 Research 专用 exact Promotion/retirement/rollback lifecycle；所有消费均从 canonical provider 重读，未用 fixture 解锁 Valuation。
18. 完成 R4 typed rolling/Regime exposure、等权/资产风险平价/宏观因子风险平价同窗 OOS 比较与 authoritative R3 attestation provider contract；所有形成时点和派生结果 fail closed、可复算，未新增持久化、晋级或生产消费入口。
19. 完成 R4 Portfolio-owned append-only receipt/result ledger、canonical typed replay、server-clock/UoW 写保护、covariance condition/rank/coverage diagnostics 和 exact PIT Application query；未实现 Research R4 Promotion/lifecycle 或下游激活。
20. 完成 R4 Research Promotion Phase A：stable semantic scope、selection 前预注册 policy、Portfolio/current-R3 exact trial seal、派生 decision、scope-local Promotion/retirement/rollback stack 与 PIT active provider；五表 ORM/migration 和 concrete providers 留给 Phase B。

## 2. 启动状态矩阵

| 能力 | 决策 | 解除阻断所需的核心证据 | 独立阶段计划 |
|---|---|---|---|
| R1 行业经营驱动与盈利预测 | `blocked` | 已有版本化行业模板、Sector→Equity 持久 bridge、三情景六阶段/cash-flow seal、owner-approval-enforced baseline contract、完整配对 trial 和 Research exact Promotion/lifecycle；仍需 QW-7 反馈、连续 PIT 事实、Production Publication、真实 owner approval/trial/approved decision，且未接 Valuation | [R1/R2](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| R2 市场结构与投资者资金流 | `blocked` | 已有 taxonomy/measure/proxy/PIT membership、版本化 expected-period calendar、完整 coverage 和整期全缺阻断；仍需批准定义、真实 calendar、两个周期真实 PIT 覆盖和 Publication 证据 | [R1/R2](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| R3 高频宏观因子与 nowcast | `blocked` | 已有 exact PIT runner、逐 fold baseline/FMP/nested-CV、canonical artifact bytes、dated outputs 和 retirement lifecycle；仍需宏观 vintage/代理资产 PIT、真实 benchmark/cost、regime/OOS trial 和 exact Promotion | [R3/R4](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| R4 宏观敞口与风险平价 | `blocked` | 已有 rolling/Regime/三方法同窗、Portfolio ledger/query、covariance diagnostics 及 Research scope/policy/trial/decision/lifecycle/active provider 软件合同；仍需 Research 五表 repository/migration、concrete providers、真实 R3 晋级和 canonical inputs | [R3/R4](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| R5 固收相对价值与久期 | `blocked` | 已有 research-only 定价/久期/曲线/信用内核；仍需真实 Publication、Bond Master、现金流/交易日历和外部对账 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R6 高级状态模型 | `blocked` | 已有简单基准不足取证器和外部高级状态证据验证；仍需真实不足证据、PIT 输入、稳定标签/OOS/政策目标和晋级 | [R6](r6-simple-baseline-shortfall-and-state-model-staged-delivery-2026-08-05.md) |
| R7 情景概率校准 | `blocked` | 已有 source-separated Brier/分箱、PIT 类比、typed 逐期路径证据和 internal-only reminder lifecycle；仍需完整 outcome 历史、获批样本政策、结果持久化与研究晋级 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R8 多资产优化 | `blocked` | 已有 canonical snapshot/反馈台账、13 类 typed 输入、current/universe/四市场/path 约束、四候选比较及 append-only lifecycle；仍需真实 Portfolio snapshot、broker reconciliation、约束校准及 R3/R4/R5 晋级版本 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |

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
| `portfolio` | `portfolio_planning_constraints`、`portfolio_canonical_snapshot`、`optimizer_input_contract` | transition planning、不可变 snapshot 和 research-only 输入门禁；不代表真实组合样本、上游晋级或优化算法已完成 |
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

完整路线图审计后的 R4/R5 增量批次另行复验 fixed-income 全部 unit/component 与 R4 macro-risk，共 `49 passed`；增量 mypy/ruff/black、Django check、架构边界（2148 files / 0 violations）、业务配置硬编码和 43 个 current-data surface 均通过。

回滚点按 R1、R5、R6、R8 四个独立提交组切分。新增迁移只建立 append-only 研究台账与 canonical snapshot/反馈存储；没有任务注册、API/MCP/TUI 发布，也不把研究结果接入现有决策或执行路径。
