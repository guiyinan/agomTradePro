# STRAT-01 R7：情景概率、历史类比与多期路径业务定义

> Capability：`R7 / Scenario Research`
> Definition：`strat.r7.scenario-probability-research / 1.0.0`
> Policy：`strat.r7.forecast-realization-sample.policy / 1.0.0`
> Calendar：`strat.r7.cn-monthly-forecast-cohort / 1.0.0`
> Scope：`strat.r7.owner-approved-scenario-revisions / 1.0.0`
> Qualification：`strat.r7.calibration-analogy-path-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与生效条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- 只有 owner-approved、不可变的 scenario revision 或 scenario-set revision 才能进入 scope。Forecast Ledger、review、outcome、sample policy、PIT manifest 和 lifecycle 任一 owner/hash 缺失都返回 `BLOCKED`。

## 2. 业务目标与结果家族

R7 对已经发布的情景判断做事后可校准研究，并形成三个相互独立的结果家族：

1. `probability_calibration`：比较主观概率、可选模型概率与简单基准；
2. `historical_analogy`：重建历史时点可知的相似案例；
3. `multi_period_path`：检查连续路径、shock 与 transition probability 的内部一致性。

历史类比不能直接产生概率，多期路径不能把 conditional transition 当作无条件预测。三个家族分别 qualification、Promotion、monitoring、retirement 和 rollback；某一家族通过不能替另一家族背书。

## 3. Scope 与 scenario semantics

- standalone scope 必须且只能绑定 1 个 scenario revision；scenario-set scope 至少包含 2 个 revision。
- 同一 scenario set 的成员必须在一个 forecast group 内互斥且穷尽，概率和为 1；无法证明穷尽时只能按独立 binary scenario 处理，禁止归一化。
- 每个 revision 必须明确事件、地理/市场范围、起止时点、客观 realization rule、独立 outcome source、invalidation condition 和 version。
- revision 发布后不得回写定义；语义变化必须产生新 UUID。旧预测继续按旧 revision 的 realization rule 兑现。
- subjective probability 与 model probability 分栏保存。model probability 只有在绑定独立 Promotion decision 时才允许存在，缺一字段时整行无效。

R7 不把情景名称、叙事相似度、LLM 置信度或当前市场共识当作 realized outcome。

## 4. Calendar、horizon 与 censoring

- IANA timezone：`Asia/Shanghai`。
- forecast cohort：月度；cutoff 为每月最后一个工作日 `18:00`。
- forecast horizon：cutoff 后 `90` 个自然日；outcome 只能由 horizon end 时适用的 realization rule 解析。
- censoring lag：horizon end 后 `30` 个自然日。届时仍无 realized 或 invalidated outcome 的 observation 必须 censored/blocked，不能继续等待到有利结果出现。
- multi-period path：6 个连续月度 period；period index 必须从 1 连续到 6，且所有初始 scenario revision 都必须有 path evidence。
- outcome evidence 最长可用于历史 calibration 的年龄为 5 年；每次新生成的 analogy/path research evidence 最长有效 30 天；invalidation 发生后 7 天内完成 review。

`published_at < horizon_end`，outcome 的 `effective_at/available_at/recorded_at` 必须可验证。事后结果、修订数据或 horizon 内尚不可知的信息不能进入原预测。

## 5. Sample policy 与 minimum window

| policy field | 最低/固定要求 |
|---|---:|
| sample history duration | 3 个连续自然年 |
| `minimum_forecasts_per_revision` | `30` |
| `minimum_resolved_outcomes_per_revision` | `24` |
| `minimum_outcome_coverage` | `0.80` |
| `minimum_binary_class_observations` | realized 与 not-realized 各至少 `10` |
| `minimum_multiclass_groups` | `24` 个完整 forecast group |
| `minimum_multiclass_class_observations` | 每个 class 至少 `5` |
| `calibration_bin_edges` | `0, 0.2, 0.4, 0.6, 0.8, 1` |
| `probability_sum_tolerance` | `0.000001` |
| `minimum_historical_analogies` | `10` |
| `minimum_path_probability_observations` | `20` |
| `path_horizon_periods` | `6` |

coverage 分母是 sample window 内所有预注册 Forecast Ledger rows。invalidated、censored 和缺 outcome 的行保留在分母并单列，不能删除以提高分数。每个 probability bin 少于 5 个 resolved observation 时只报告不足，不外推校准结论。

## 6. Benchmark 与 probability metrics

binary primary benchmark 是在 forecast cutoff 前由历史 resolved rows 得到的 PIT climatology；multiclass secondary benchmark 是同一 set 内的等概率分布。benchmark 必须冻结在 prediction 前，不能用当前完整样本重算过去 base rate。

每个 binary revision 使用 Brier score `mean((p-y)^2)`；subjective 与 model 使用完全相同的 resolved denominator。另报告 calibration error、coverage、bin counts 和 reliability table。不得把 score 转写为“预测准确率”，也不得只选最有利概率来源。

成本和 liquidity 对 probability、analogy 和 path qualification 均为 `not_applicable_to_research_evidence`，不能用 0 伪装已评估。任何使用情景概率的下游组合必须另行绑定 cost、liquidity、constraint 和 consumer UAT。

## 7. Qualification thresholds

只有 sample policy 全部满足后，结果家族才能单独进入人工 Promotion review：

| 结果 | qualification gate |
|---|---|
| subjective probability | Brier score 至多 `0.24`；calibration error 至多 `0.10`；coverage 至少 `0.80` |
| model probability | Brier score 至多 `0.22`，且不高于 subjective 与 primary benchmark；calibration error 至多 `0.10`；coverage 与 subjective denominator exact match |
| historical analogy | 至少 10 个独立 PIT candidate；每个 candidate 的 decision cutoff、release lag、feature version 和 outcome window 可复算；不发布 probability estimate |
| multi-period path | 至少 20 个 observation；6 期连续；shock、state、transition horizon 和 PIT provenance exact match；每行 probability sum 在容差内 |

model 缺失不影响 subjective 家族评估；但不能填入 subjective 值冒充 model。analogy similarity 和 path coherence 只作为证据完整性结论，不得因样本少而给出数值概率。

## 8. Falsification 与 invalidation

以下任一条件证伪对应结果版本：

1. scenario revision 的 realization rule 不再客观可判定，或 set 不再互斥/穷尽；
2. subjective/model source、Promotion decision、PIT manifest、horizon 或 censoring rule 无法精确绑定；
3. outcome 由预测编制者事后主观补写，或 evidence 超龄；
4. probability sum 超容差、class/bin 样本不足、coverage 低于 `0.80`；
5. subjective Brier 超过 `0.24`，或 model Brier 超过 `0.22`/劣于比较对象；
6. historical analogy 使用 candidate 当时尚不可知的 feature，或用结果相似性筛选案例；
7. path index 不连续、shock 与 transition horizon 不一致，或遗漏初始 state；
8. revision、outcome 或 research evidence hash 发生不解释的变化。

情景自身的 falsification condition 触发时，必须记录 invalidation，不得把“不再适用”重新标成“未兑现”或删除记录。

## 9. Post-promotion monitoring

每个新完成的 90 日 forecast cohort 按 exact prediction members 和 outcome rows 重算：

| metric | 健康条件 |
|---|---:|
| `subjective_brier_score` | 至多 `0.24` |
| `model_brier_score` | 有 model 时至多 `0.22` |
| `forecast_outcome_coverage` | 至少 `0.80` |
| `subjective_probability_coverage` | 必须等于 eligible denominator 的 `1.00` |
| `model_probability_coverage` | 有 model 时必须与其预注册 eligible denominator exact match |

任一完整 cohort breach 即进入人工 review；连续 2 个 cohort breach 要求 owner 做 retirement decision。owner/hash、probability source、scenario set 或 outcome integrity 破坏立即 `BLOCKED`。monitoring 不允许自动退休，也不能把新 outcome 写回旧 prediction。

## 10. Retirement、family rollback 与下游边界

- owner 可以分别 `RETIRE` calibration、analogy 或 path family；其他 family 不随之自动晋级或退休。
- rollback 只允许回到同 scenario/scope/policy/horizon/censoring family 的 `stack[-2]`，并重验旧版本的 sample window、outcome validity 和 monitoring freshness。
- 若同 family 没有合格旧版本，则停止发布该 research result，不回退到未审核概率或人工默认值。
- R7 Promotion 不授权修改 Risk Center scenario、生成 Signal、覆盖主观概率、改变 Portfolio 或触发执行；每个 consumer 仍需单独 contract 与 UAT。
