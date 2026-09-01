# STRAT-01 R6：高级状态模型与政策反应函数业务定义

> Capability：`R6 / State Model`
> Definition：`strat.r6.advanced-state-model / 1.0.0`
> Policy：`strat.r6.simple-baseline-first.policy / 1.0.0`
> Calendar：`strat.r6.cn-macro-monthly / 1.0.0`
> Scope：`strat.r6.four-state-policy-reaction / 1.0.0`
> Qualification：`strat.r6.comparative-state-model-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与启动前置条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- R6 只有在同窗简单 Regime 基准的 shortfall report 为 `PROVEN` 时才允许提出高级模型研究。`NOT_PROVEN` 或 `BLOCKED` 都不能启动、训练、选择或晋级高级候选。

## 2. 业务目标与明确非目标

R6 评估简单增长/通胀动量 Regime 在转移、持续期、概率校准和决策损失上是否存在已证实的系统性不足，以及预注册的 Markov switching、Hidden Markov Model、dynamic Bayesian 或 policy-reaction 候选能否在同一 PIT/OOS window 中稳定改善。

R6 不追求用更复杂模型替代现有 Regime。任何结果固定为 `research_only=true`、`must_not_use_for_decision=true`、`must_not_replace_regime=true`；state probability 是不确定性表达，不是收益概率或交易指令。

## 3. Label protocol 与 scope

v1 沿用业务公理层的四个稳定经济标签，标签身份、名称和对齐方法在 selection 前冻结：

| state id | 业务含义 |
|---|---|
| `Recovery` | 增长动量加速、通胀动量减速 |
| `Overheat` | 增长动量加速、通胀动量加速 |
| `Stagflation` | 增长动量减速、通胀动量加速 |
| `Deflation` | 增长动量减速、通胀动量减速 |

增长与通胀动量必须按 [`AgomTradePro_V3.4.md`](../../AgomTradePro_V3.4.md) 的 Regime 定义计算；HP 滤波在每个历史时点使用扩张窗口，不能全样本回填。高级模型的 latent state 必须使用预注册的 assignment/alignment method 映射到上述四类，并以 permutation-invariant 方式评估；训练后人工挑选最有利映射无效。

输入 scope 限于经 Publication/PIT 约束的增长、通胀、利率、信用、流动性、汇率和人工 Policy 档位事实。Policy `P1–P3` 仍由人工标注，高级模型不得反向生成或覆盖该档位。

## 4. Calendar、样本可见性与模型族

- IANA timezone：`Asia/Shanghai`。
- 形成频率：月度；cutoff 为当月最后一个已完成宏观 release batch 的次日 `18:00`。
- 在 cutoff 前未发布的指标继续使用上一个可知 vintage 或标记缺失；禁止用后来修订值回填。
- prediction horizon：1 个自然月；state duration 以完整月度 period 计。
- 外部预计算 artifact 必须绑定 code、parameter、PIT manifest、label protocol、producer 和 hash；本系统只复核证据，不从数据库现状推测模型。

同一 qualification study 只允许比较一个预注册候选与一个 sealed simple baseline。模型族、超参数搜索空间、随机种子和终止条件必须在 OOS 解封前登记；不得在看过 OOS 后换族。

## 5. 简单基准不足证明

simple baseline key 为 `canonical-regime-growth-inflation-momentum`。在至少 120 个完整月度 observation 上，下列三项必须全部跨过 shortfall 边界，才得到 `simple_baseline_shortfall=PROVEN`：

| metric | shortfall direction | 边界 |
|---|---|---:|
| `transition_accuracy` | below minimum | `< 0.55` |
| `duration_mae_periods` | above maximum | `> 2.00` 个月 |
| `decision_loss_utility` | above maximum | `> 0.02` |

任一指标不跨界即 `NOT_PROVEN`；样本、PIT、label、单位、有效期或证据不完整则 `BLOCKED`。三项规则使用“全部满足”，不能只展示最差的一项作为启动理由。

## 6. Sample window 与 validation

| 项目 | 最低要求 |
|---|---:|
| PIT history duration | 10 个连续自然年 |
| complete monthly observations | `120` |
| initial training window | `72` 个月 |
| validation window | `24` 个月 |
| sealed OOS window | `24` 个月 |
| rolling/expanding OOS folds | 至少 `4` 个 |
| input/label coverage | `0.98` |
| 每个 state 的 resolved OOS observations | 至少 `12` 个 |
| policy-reaction complete observations | 至少 `60` 个 |

训练、validation 和 OOS 按时间严格有序且不重叠；同一 economic release 的 revisions 不得跨 fold 泄漏。缺失类别不能通过合并 state 提升 coverage。

## 7. Candidate qualification

候选必须先满足绝对门槛，再满足相对 sealed baseline 的最小改善：

| required metric | 绝对门槛 | 相对改善 |
|---|---:|---:|
| `transition_accuracy` | 至少 `0.60` | 至少 `+0.05` |
| `log_loss` | 至多 `0.90` | 至少降低 `0.05` |
| `calibration_error` | 至多 `0.10` | 至少降低 `0.02` |
| `duration_mae_periods` | 至多 `2.00` | 至少降低 `0.25` 个月 |
| `decision_loss_utility` | 至多 `0.02` | 至少降低 `0.005` |
| `complexity_score` | 至多 `20` 个 effective parameters | 不得高于预注册上限 |
| `label_stability_score` | 至少 `0.80` | 至少 `+0.05` |

probability row sum tolerance 为 `0.000001`；transition matrix 每行同样必须在该容差内归一。全部七项、各 fold 和 aggregate summary 均须完整；复杂候选不能以收益解释或单一 accuracy 抵消校准、持续期或稳定性失败。

## 8. Policy reaction qualification

若候选包含政策反应函数，必须预注册政策工具、target set、lag、系数预期符号和最小绝对幅度，并额外满足：

| diagnostic | 门槛 |
|---|---:|
| complete sample count | 至少 `60` |
| adjusted R² | 至少 `0.25` |
| residual autocorrelation p-value | 至少 `0.05` |
| heteroskedasticity p-value | 至少 `0.05` |
| parameter stability p-value | 至少 `0.05` |
| condition number | 至多 `100` |

系数符号、置信区间或 target binding 任一失败即整体不合格。相关性不能表述为政策因果；政策反应函数只描述该 specification 下的经验关系。

## 9. Cost、liquidity 与 benchmark 语义

R6 的直接 state-model qualification 不生成持仓，因此交易成本和 liquidity 为 `not_applicable_to_state_qualification`，不能填零冒充已评估。若计算 `decision_loss_utility` 使用影子组合，则必须让 candidate 与 baseline 共用另行批准的 cost/liquidity policy，且只把净结果用于比较；该影子结果不构成执行授权。

benchmark 永远是同一 PIT、label、window 和 loss function 下的 canonical simple Regime，不得用更弱的随机分类器替换。可另列 climatology，但不能取代 primary benchmark。

## 10. Post-promotion monitoring

每个完整月度 period 必须发布以下 11 项 raw metric：

| metric | 健康条件 |
|---|---:|
| `transition_accuracy` | 至少 `0.55` |
| `log_loss` | 至多 `0.90` |
| `calibration_error` | 至多 `0.12` |
| `duration_mae` | 至多 `2.50` 个月 |
| `decision_loss` | 至多 `0.02` |
| `label_stability` | 至少 `0.80` |
| `policy_adjusted_r_squared` | 至少 `0.20` |
| `policy_residual_autocorrelation_p_value` | 至少 `0.05` |
| `policy_heteroskedasticity_p_value` | 至少 `0.05` |
| `policy_parameter_stability_p_value` | 至少 `0.05` |
| `policy_condition_number` | 至多 `100` |

minimum observation count 为 6 个完整 period；任一指标连续 2 期 breach 触发人工 retirement review。label identity/hash 漂移、PIT 泄漏、artifact 替换或 probability 不守恒立即 `BLOCKED`，无需等待连续期数。monitoring 不自动 RETIRE。

## 11. Falsification、retirement 与 rollback

以下任一条件证伪当前版本：simple baseline shortfall 不再成立；候选七项资格或政策诊断失败；label 无法稳定对齐；未来 revision 泄漏；transition/duration/probability 不能复算；artifact、parameter、PIT 或 owner hash 不一致；OOS window 被重新选择。

- owner `RETIRE` 后停止发布该 research candidate，但不删除 artifact、assessment、monitoring 或 lifecycle history。
- rollback 只回到同 baseline/PIT/label/methodology/threshold scope 的 `stack[-2]`，并重新验证 simple-baseline shortfall 仍为 `PROVEN`。
- 没有合格旧版本时仅停止高级模型，canonical Regime 继续按既有规则运行；不得自动降门槛或换标签。
- 任何 R6 lifecycle 决定都不自动替换 Regime、Policy、准入矩阵、信号或组合配置。
