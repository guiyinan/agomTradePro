# STRAT-01 R1–R8 业务定义包

> 包版本：`strat-01-business-definition-pack.v1.0.0`
> 完成状态：`READY_FOR_OWNER_ATTESTATION`
> 编制日期：`2026-09-01`
> 业务 owner：`阿狗涅夫`（用户声明的项目 owner 展示名）
> owner 身份：`agomtradepro-personal-project-owner`
> owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)
> 生效边界：本文档包完成不等于 owner 已签署、生产已登记或 capability 已晋级。

## 1. 包目的

本目录给出 STRAT-01 所需的 R1–R8 完整业务定义。每份定义都可独立作为审核附件，并覆盖：

- definition、policy、calendar、scope/universe；
- minimum duration、periods、samples、coverage；
- qualification thresholds 与 falsification conditions；
- 适用的 benchmark、cost、liquidity、label 语义；
- invalidation、retirement 与 rollback 条件；
- owner、版本、拟议有效期与明确的非授权边界。

这些文件是候选版本无关的业务语义真源。具体 release 的审核报告负责绑定候选、owner 决定、文档 SHA-256 和 dry-run 生成的 canonical content hash；业务文档本身不预填 canonical content hash。

## 2. 文档清单

| 能力 | 业务定义 | 主结果 |
|---|---|---|
| R1 Forecast Baseline | [行业经营驱动与盈利预测基准](r1-forecast-baseline.md) | 形成可回放、可与简单基准配对比较的季度预测 |
| R2 Market Structure | [市场结构与投资者资金流](r2-market-structure.md) | 形成有 PIT membership 的描述性、解释性资金结构证据 |
| R3 Macro Factor | [高频宏观因子与 nowcast](r3-macro-factor.md) | 形成经嵌套时序验证的宏观因子研究版本 |
| R4 Risk/Allocation | [宏观敞口与宏观因子风险平价](r4-risk-allocation.md) | 同窗比较等权、资产风险平价与宏观因子风险平价 |
| R5 Relative Value | [固收相对价值与久期](r5-relative-value.md) | 形成含成本、流动性和容量约束的固收相对价值证据 |
| R6 State Model | [高级状态模型与政策反应函数](r6-state-model.md) | 仅在简单基准不足获证后评估高级状态模型 |
| R7 Scenario Research | [情景概率、历史类比与路径](r7-scenario-research.md) | 分离主观/模型概率并验证校准、类比和多期路径 |
| R8 Optimization Monitoring | [多资产优化与执行反馈监控](r8-optimization-monitoring.md) | 比较四类候选并用真实组合/券商反馈持续监控 |

每份 Markdown 文件旁的 `.sha256` 是该文件的提交附件摘要。文档修改后必须重新生成 sidecar；旧摘要不得继续引用。

## 3. 统一术语

| 术语 | 本包内的唯一含义 |
|---|---|
| `effective_at` | 事实或规则所描述的业务时点 |
| `available_at` | 该事实首次可被系统合法获知的时点 |
| `recorded_at` | 证据进入权威台账的服务端时点 |
| `as_of` | 查询或决策截止时点；只允许读取当时已 available 且未失效的版本 |
| `PIT` | 以 `available_at/revision/manifest` 约束的时点可知数据，不是今天看到的历史最终值 |
| `coverage` | 实际可用成员数除以预注册完整分母；不得删除缺失成员来提高比例 |
| `benchmark` | selection 前登记、与候选使用同一窗口和数据可见性的比较对象 |
| `qualification` | 允许提交人工 Promotion review 的研究门槛，不是生产授权 |
| `invalidation` | 已形成的研究证据不再可依赖的客观条件 |
| `retirement` | owner 授权后停止当前研究版本继续作为 active candidate |
| `rollback` | 只回到同 scope、同 lifecycle stream 的上一个完整 active 版本，即 `stack[-2]` |

`latest` 只表示排序最新，不代表 fresh、reliable 或可用于决策。任何缺失、过期、未来可见、owner 错配、hash 错配或覆盖不足均返回 `BLOCKED`，不得以默认值或人工猜测补齐。

## 4. 统一权限与安全边界

1. 全部 R1–R8 初始输出均为 `research_only=true`、`must_not_use_for_decision=true`、`must_not_execute=true`。
2. 本包不授权生产写、PIT/OOS backfill、Promotion、consumer UAT、策略执行或交易。
3. owner attestation 只批准业务语义；append-only registration 仍需候选绑定 dry-run 和单独的第二阶段授权。
4. Data Center 事实、测试 fixture、空表、代码存在或迁移成功都不能替代 owner definition。
5. 自动化可复算、校验和生成草稿，但不能替代 owner 签署或制造历史观察期。
6. R1 通过后仍需单独授权 Valuation 消费；R2 不发布预测信号；R6 不自动替换现有 Regime；R8 不生成可直接执行的订单。

## 5. 跨能力依赖

| 能力 | 硬依赖 |
|---|---|
| R1 | 连续经营 KPI、财务 actual Publication/PIT、完整配对 trial |
| R2 | taxonomy/calendar Publication、恰好两个完整市场周期、真实 Audit outcome |
| R3 | 宏观 vintage、代理资产 PIT、发布日历、连续合约规则、Research family |
| R4 | active 且未失效的 R3 Promotion；Portfolio canonical covariance/exposure/constraint graph |
| R5 | 两条可靠曲线、信用估值、Bond Master、CashFlow、Calendar、成本与流动性事实 |
| R6 | `simple_baseline_shortfall=PROVEN`、稳定经济标签、PIT/OOS 结果 |
| R7 | 完整预测—复核—兑现历史、获批 sample policy、独立 outcome source |
| R8 | active R3/R4/R5 Promotion、Portfolio canonical snapshot、Broker reconciliation |

依赖不完整时，对应能力保持 `BLOCKED`；不得用下游 assessment 反充上游 owner evidence。

## 6. 拟议有效期与变更规则

- 本包拟议业务窗口为 `2026-09-01T00:00:00+08:00` 至 `2027-08-31T23:59:59+08:00`。
- 实际 `valid_from` 取 owner attestation 和 append-only registration 两者中较晚时点；若届时已无正有效期，必须发布新版本，不能延长旧文件。
- 阈值、scope、calendar、label、benchmark、成本或流动性口径任一变化都需要新版本、新 SHA-256 和新 dry-run。
- 只修正文案且不改变 canonical 语义时也生成新文档摘要，并在审核记录中说明非语义变更。

## 7. 审核顺序

1. owner 逐份核对业务含义和数值门槛；
2. 生成最终 owner decision report，引用文档及 sidecar；
3. 校验 schema、SHA-256、有效期、scope overlap 和 current head；
4. 执行 canonical dry-run，由系统计算 canonical content hash；
5. 另行批准 append-only registration；
6. 注册后复核 rows、hashes 和 current head；
7. 待真实 PIT/OOS 历史形成后，再分别处理 Promotion 与 consumer UAT。

## 8. 依据

- [策略研究能力后续开发备忘](../../strategy-research-capability-roadmap-memo-2026-08-04.md)
- [R1/R2 启动门整改计划](../../../plans/strategy-research-r1-r2-readiness-plan-2026-08-05.md)
- [R3/R4 分阶段实施计划](../../../plans/macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md)
- [R5–R8 分阶段实施计划](../../../plans/strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md)
- [R6 简单基准不足计划](../../../plans/r6-simple-baseline-shortfall-and-state-model-staged-delivery-2026-08-05.md)
- [STRAT-01 审核团队交接](../../../deployment/evid-strat-review-team-handoff-2026-08-30-36b72d2f.md)
