# STRAT-01 R4：宏观敞口与宏观因子风险平价业务定义

> Capability：`R4 / Risk/Allocation`
> Definition：`strat.r4.macro-risk-allocation / 1.0.0`
> Policy：`strat.r4.three-method-oos.policy / 1.0.0`
> Calendar：`strat.r4.cn-monthly-formation / 1.0.0`
> Scope：`strat.r4.multi-asset-macro-risk / 1.0.0`
> Qualification：`strat.r4.macro-risk-parity-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与生效条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- R4 必须读取 active、未过期、未退休的 R3 Promotion。R3 缺失时，R4 无论本地算法是否可运行都保持 `BLOCKED`。

## 2. 业务目标

R4 估计资产/组合对增长、通胀、利率、信用、流动性和汇率因子的滚动暴露，并将总方差拆为宏观因子与残差来源。目标方法是宏观因子风险平价，不是资产波动率倒数。

每个 formation window 必须从同一 sealed owner graph 由服务端构造并比较：

1. `equal_weight`；
2. `asset_risk_parity`；
3. `macro_factor_risk_parity`。

调用方不能预填权重、资格或派生风险贡献。

## 3. Scope 与 universe

v1 universe 是可由个人多资产组合合法持有且有完整 canonical return/cost/liquidity history 的人民币计价资产代理，覆盖 A 股宽基/风格、国债或债券基金、黄金、商品和现金类工具。具体资产由 Portfolio universe policy 在 selection 前冻结。

入选条件：

- 具有 active R3 exposure 和完整 factor covariance；
- 具有 Portfolio asset covariance、current weights、权重上下限、成本、换手和流动性约束；
- 形成时点可知且有效期覆盖本 fold；
- 不允许用缺失 exposure 的零值、未来协方差或当前成分回填。

杠杆、卖空、衍生品和跨币种敞口不在 v1 scope；若需加入必须升版。

## 4. Calendar 与形成时点

- IANA timezone：`Asia/Shanghai`。
- 频率：月度 formation / 月度 OOS holding period。
- formation cutoff：月末最后交易日 `16:30`；调仓生效为下一交易日开盘后的可执行窗口。
- exposure、factor covariance、asset covariance、constraint、cost、current weights、universe 和 Regime assignment 必须在同一 cutoff 下可见。
- OOS return path 不得进入 formation、权重构建或协方差估计。

## 5. Covariance、暴露与数值门禁

| 项目 | 门槛 |
|---|---:|
| exposure regression minimum R² | `0.20` |
| exposure stability score | `0.70` |
| covariance coverage | `0.98` |
| covariance condition number | 不高于 `1,000,000` |
| weight sum tolerance | `0.000001` |
| covariance symmetry/PSD tolerance | `0.00000001` |
| risk contribution identity tolerance | `0.0001` |
| macro risk contribution target deviation | 不高于 `0.05` |

非 PSD、rank 不足、condition number 超限、coverage 不足或风险贡献之和与总风险不一致时 fail closed；不静默替换为对角矩阵或等权结果。

## 6. Cost、turnover 与 liquidity

- 成本使用 Portfolio canonical one-way cost，在一次 rebalance 中按实际交易方向和 notional 计一次；报告 gross、turnover、expected cost 和 net。
- 单次组合 turnover 不高于 `0.50`；单次 expected cost 不高于组合净值的 `0.005`。
- 单资产交易不得超过 owner liquidity policy 的 `5%` 可交易 notional；组合容量 utilization 不高于 `0.80`。
- 权重上下限、最低现金和人工限制来自 exact constraint snapshot；缺失时不求解。

## 7. Benchmark 与 sample window

三个方法共享完全相同的 snapshot、universe、formation/OOS window、exposure、两类 covariance、cost 和 constraint。不得让目标方法使用更晚或更完整的数据。

| 项目 | 最低要求 |
|---|---:|
| duration | 60 个连续自然月 |
| OOS periods | 60 个完整月度 period |
| walk-forward folds | 至少 12 个 |
| regime-covered folds | 至少 `75%`，且四类经济 Regime 中至少覆盖 3 类 |
| input/return coverage | `0.98` |
| assets | 每个 fold 至少 4 个可投资资产 |

## 8. Qualification thresholds

目标 `macro_factor_risk_parity` 必须满足：

| 比较项 | 门槛 |
|---|---:|
| 相对最佳 reference 的成本后净收益 | 不低于 `0` |
| 相对最大回撤增加 | 不高于 `0.02` |
| 相对实现波动增加 | 不高于 `0` |
| 相对总成本增加 | 不高于 `0.0025` |
| minimum fold count | `12` |
| minimum regime coverage | `0.75` |
| 风险贡献 identity | 误差不高于 `0.0001` |

全部 fold 和 aggregate summary 均由服务端重算。目标方法即使收益更高，只要风险、成本、coverage 或可复算性失败，也不得 qualification。

## 9. Post-promotion monitoring

每个完整月度 period 必须提供以下 11 项 raw metric；阈值是相对 Promotion trial/benchmark 的同口径值：

| metric | 健康条件 |
|---|---:|
| `relative_net_return` | 至少 `-0.02` |
| `relative_drawdown_increase` | 至多 `0.03` |
| `relative_volatility_increase` | 至多 `0.02` |
| `relative_cost_increase` | 至多 `0.0025` |
| `covariance_condition_number` | 至多 `1,000,000` |
| `covariance_coverage_ratio` | 至少 `0.98` |
| `risk_contribution_error` | 至多 `0.05` |
| `beta_drift` | 至多 `0.25` |
| `regime_stability_ratio` | 至少 `0.70` |
| `label_drift_ratio` | 至多 `0` |
| `data_drift_ratio` | 至多 `0.10` |

minimum observations 为 6 个完整 period，单个 metric 连续 2 个 period breach 时要求人工 retirement review。monitoring 不自动 RETIRE。

## 10. Falsification 与 invalidation

以下任一条件证伪当前 R4 版本：

1. 风险贡献和不再等于组合风险，或 covariance/exposure 不能复算；
2. 目标方法在同窗成本后不再优于或持平 reference；
3. drawdown、volatility、cost、turnover、liquidity 或 capacity 超过门槛；
4. active R3 Promotion 失效、退休、被替换或 label set 改变；
5. universe、current weights、constraint 或 Regime assignment 与 formation snapshot 不一致；
6. label/data drift 超阈值；
7. OOS path、未来宏观 revision 或未来 covariance 泄漏进入 formation。

## 11. Retirement 与 rollback

- owner/hash/PIT/R3 依赖破坏立即 `BLOCKED`；性能门槛连续 2 期 breach 进入人工 review。
- `RETIRE` 后 Risk Center、Portfolio preview 和其他 consumer 必须停止读取该 active version。
- rollback 只回到同 universe/factor/split/cost scope 的 `stack[-2]`，并重验 R3 Promotion、完整 input graph 和 monitoring freshness。
- 无合格旧版本时回到规则化现有组合流程，而不是把资产波动率倒数结果冒充宏观风险平价。
- 本定义不授权订单、transition plan 或 execution。
