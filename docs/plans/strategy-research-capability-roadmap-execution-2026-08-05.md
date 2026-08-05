# 策略研究能力路线图 R1—R8 执行状态（2026-08-05）

> 状态：M0 合约、运行时取证及 R1/R2/R7/R8 数据积累纵切已完成；真实数据、晋级和模型阶段仍待实施，R1—R8 均 `blocked`
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

## 2. 启动状态矩阵

| 能力 | 决策 | 解除阻断所需的核心证据 | 独立阶段计划 |
|---|---|---|---|
| R1 行业经营驱动与盈利预测 | `blocked` | QW-7 真实使用反馈、连续经营事实、财务/估值 PIT、预测评估规范和 R1 晋级绑定 | [R1/R2](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| R2 市场结构与投资者资金流 | `blocked` | 主体分类和单位语义、两个周期 PIT 覆盖、历史资产组 membership、代理标识 | [R1/R2](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| R3 高频宏观因子与 nowcast | `blocked` | 宏观 vintage/代理资产 PIT、发布日历、连续期货规则、专属 benchmark 和成本模型 | [R3/R4](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| R4 宏观敞口与风险平价 | `blocked` | R3 晋级版本、资产暴露、协方差、权重/换手/流动性约束和对照基准 | [R3/R4](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| R5 固收相对价值与久期 | `blocked` | 两条已发布曲线、信用估值、Bond Master、现金流/交易日历和久期凸性对账 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R6 高级状态模型 | `blocked` | 简单基准不足证据、PIT 输入、稳定标签协议、样本外转移基准和政策目标契约 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R7 情景概率校准 | `blocked` | 情景版本与预测账本绑定、完整 outcome 历史、校准样本政策和类比 PIT manifest | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| R8 多资产优化 | `blocked` | canonical portfolio snapshot、R3/R4/R5 晋级版本、执行反馈和统一优化输入契约 | [R5—R8](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |

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
| `portfolio` | `portfolio_planning_constraints`、`optimizer_input_contract` | transition planning 约束和 research-only 输入门禁；不代表 canonical snapshot、上游晋级或优化算法已完成 |
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

当前尚未接线的 owner 为 `equity`、`macro_factor`、`fixed_income`、`policy`、`audit`、`broker_execution`；其中 `macro_factor` 与 `fixed_income` 尚无独立 App。已接线 owner 中，所有数据覆盖、Production Publication、晋级版本和样本历史 requirement 仍保持 `unverified`，运行时不查询空表，也不以模型或迁移存在推断 `verified`。

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

回滚点是 readiness contract、owner registry、治理 attestation 清单、测试和上述四份文档；本阶段无迁移、无数据库写入、无任务注册、无 API/MCP/TUI 发布，也不影响现有研究和决策运行路径。
