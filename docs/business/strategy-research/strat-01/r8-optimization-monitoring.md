# STRAT-01 R8：多资产优化与执行反馈监控业务定义

> Capability：`R8 / Optimization Monitoring`
> Definition：`strat.r8.governed-multi-asset-optimization / 1.0.0`
> Policy：`strat.r8.four-candidate-oos.policy / 1.0.0`
> Calendar：`strat.r8.cn-monthly-portfolio-cycle / 1.0.0`
> Scope：`strat.r8.rmb-long-only-multi-asset / 1.0.0`
> Qualification：`strat.r8.optimization-monitoring-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与硬前置条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- R8 只有在 Portfolio canonical snapshot 与 Broker reconciliation 可精确回读，且 R3、R4、R5 均存在 active、未退休、有效期覆盖 input set 的 Promotion 时才可运行。缺一项即 `BLOCKED`，不得以代码可求解或 fixture 完整解除门禁。

## 2. 业务目标与四候选比较

R8 在同一 canonical Portfolio snapshot、universe、PIT input set、objective 和约束下比较四类确定性候选：

1. `current_configuration`：真实当前配置，primary benchmark；
2. `equal_weight`：对所有可投资非现金成员等权并保留最低现金；
3. `asset_risk_parity`：按资产协方差形成的风险平价 reference；
4. `deterministic_search`：受约束的确定性局部搜索目标。

四类必须全部计算或给出可复算的不可行 blocker，不能删除表现差或不可行的 reference。`deterministic_search` 最多声明 `local_stationary` 或 `iteration_limit`，禁止声明 global optimum。

R8 输出目标权重草案、约束影子和 monitoring evidence；不输出订单，不修改 current holdings，不写 transition plan，也不调用 Broker Execution。

## 3. Scope 与 investable universe

v1 scope 是人民币计价、long-only、fully-invested 的个人多资产研究组合，可包含具有 canonical instrument master 和完整行情/成本/流动性历史的：A 股、场内 ETF、人民币债券或债券基金、黄金/商品 ETF 与现金类工具。

以下不在 v1 scope：融资融券、卖空、期货、期权、场外衍生品、结构化产品、跨币种敞口和未建模保证金。加入任一项都需要新 scope/version。

具体 universe 必须由 Portfolio owner 在每个 formation cutoff 前冻结，成员不得硬编码。每个成员必须有 instrument identity、asset class、currency、current position/cash、tradability、lot/T+1/settlement、minimum/maximum weight、maximum trade weight、成本和流动性证据。无法在 weight 层证明的交易约束必须阻断，不能用“之后下单时再修正”绕过。

## 4. Calendar 与形成时点

- IANA timezone：`Asia/Shanghai`。
- formation/holding/monitoring 频率：月度。
- formation cutoff：月末最后交易日 `16:30`；候选权重最早从下一交易日的可执行窗口生效。
- 当前持仓、现金、universe、全部 13 类 input、R3/R4/R5 Promotion、约束和 broker feedback 必须在同一 cutoff 下可见且有效。
- monitoring period 为连续自然月；Portfolio calendar 必须在首个 period 前登记，不允许事后删月或重排。
- input set 从创建到使用期间任一 owner graph 替换、Promotion retire 或有效期结束均使本次结果失效。

## 5. 完整 canonical input graph

每次求解必须封存且逐项绑定 canonical owner 的 13 类 payload：

`expected_return`、`macro_exposure`、`asset_covariance`、`scenario_loss`、`drawdown_risk_budget`、`transaction_cost`、`turnover_limit`、`liquidity_limit`、`position_bounds`、`trading_constraints`、`manual_restrictions`、`cash_requirement`、`execution_feedback`。

每类 payload、owner evidence、universe 与 Portfolio snapshot 的 version/hash/as-of 必须一致；不得用同类 payload 的默认值补缺。covariance 必须对称、PSD 且与 universe exact aligned；expected return 只作为版本化研究假设，不得伪装成确定收益。

## 6. Objective、数值与硬约束

objective 由非负的 expected-return、variance 和 transaction-cost 权重组成，必须在 OOS 解封前冻结。v1 使用以下最低治理边界：

| 项目 | 边界 |
|---|---:|
| weight sum | `1.00 ± 0.000001` |
| covariance symmetry/PSD tolerance | `0.00000001` |
| minimum cash weight | `0.05` |
| monthly portfolio turnover | 至多 `0.25` |
| rebalance total cost rate | 至多 `0.005` |
| adverse slippage rate | 至多 `0.002` |
| single-asset planned trade / tradable notional | 至多 `0.05` |
| liquidity utilization | 至多 `0.80` |
| capacity utilization | 至多 `0.80` |
| constraint/reconciliation breach | `0` |

逐资产 position bounds、maximum trade weight、manual restriction、scenario maximum loss、drawdown budget 和 macro risk budget 取 exact owner policy，不在本文用统一数字覆盖。任何 candidate 违反一项即不可行；不得先裁剪权重再宣称原 solver output 合格。

## 7. Benchmark、cost 与 liquidity

primary benchmark 是 `current_configuration`；equal weight 和 asset risk parity 是 required references。四候选共享同一 return path、cost、liquidity、settlement、scenario、drawdown 和 execution feedback。

成本按真实调仓方向 once-only 计入，包括费用、税费、bid-ask、冲击、滑点、融资/结算（若适用），并报告 gross objective、turnover、cost 与 net outcome。current benchmark 也必须计入真实维持/调仓成本，不能人为设为零。

liquidity 和 capacity 使用 formation 时可知的可交易 notional；未来成交量不能回填。某资产不足时保留 blocker 和原 denominator，不删除成员后重算一个更容易的 universe。

## 8. Sample window 与真实反馈

| 项目 | 最低要求 |
|---|---:|
| paired OOS history | 36 个连续月度 period |
| complete four-candidate comparisons | `36` |
| real Portfolio/Broker feedback | 至少 `12` 个连续月度 period |
| canonical input coverage | `1.00` |
| 每个 period 可投资资产 | 至少 4 个，且至少覆盖 3 类资产 |
| constraint/reconciliation coverage | `1.00` |

shadow backtest 不能替代 12 期真实 execution feedback。若某 period 无交易，仍需 zero-trade reconciliation 证明，而不是省略该 period。

## 9. Qualification thresholds

目标 `deterministic_search` 必须为 `local_stationary`、完整可复算，并同时满足：

| qualification item | 门槛 |
|---|---:|
| 相对 current 的成本后净收益 | 不低于 `0` |
| 相对 current 的最大回撤增加 | 不高于 `0` |
| absolute maximum drawdown | 不高于 `0.15` |
| 相对 current 的 realized volatility increase | 不高于 `0` |
| monthly turnover | 不高于 `0.25` |
| rebalance total cost rate | 不高于 `0.005` |
| adverse slippage rate | 不高于 `0.002` |
| liquidity/capacity utilization | 均不高于 `0.80` |
| constraint breach/reconciliation break | 均为 `0` |
| minimum cash | 不低于 `0.05` |

权重、objective、risk contribution、path drawdown、scenario loss、turnover 和成本全部由服务端根据封存输入重算。只要四候选不完整、R3/R4/R5 任一失效、或 deterministic candidate 仅到 `iteration_limit`，就不能 qualification。

## 10. Post-promotion monitoring

每个完整月度 period 必须收齐 Portfolio 与 Broker owner facts并重算 11 项指标：

| metric | 健康条件 |
|---|---:|
| `net_realized_return` | 至少 `-0.03` |
| `max_drawdown` | 至多 `0.15` |
| `turnover_rate` | 至多 `0.25` |
| `total_cost_rate` | 至多 `0.005` |
| `adverse_slippage_rate` | 至多 `0.002` |
| `liquidity_utilization` | 至多 `0.80` |
| `capacity_utilization` | 至多 `0.80` |
| `constraint_breach_rate` | 至多 `0` |
| `reconciliation_break_rate` | 至多 `0` |
| `label_drift_rate` | 至多 `0` |
| `data_drift_score` | 至多 `0.10` |

minimum complete periods 为 6，required consecutive breaches 为 2；period lag 不得超过 45 个自然日，owner evidence 必须在 period end 后 10 个工作日内记录。任一指标连续 2 期 breach 输出 `RETIREMENT_REVIEW_REQUIRED`；`automatic_retirement=false`。constraint/reconciliation、owner/hash、Promotion 或 input integrity 破坏立即 `BLOCKED`。

## 11. Label、falsification 与 invalidation

允许的 candidate label 仅为四个 `CandidateKind`；selected 只表示在预注册 objective 和可行集合中的确定性排序赢家，不表示最优资产配置、global optimum 或未来收益保证。

以下任一条件证伪或使版本失效：

1. canonical snapshot、universe、13 类 payload 或 R3/R4/R5 Promotion 不完整、过期、冲突或 hash 不一致；
2. covariance 非 PSD、matrix/universe 错位、数值守恒或权重和失败；
3. 四候选比较不完整，或 target 未达到 `local_stationary`；
4. OOS 净收益、drawdown、volatility、turnover、cost、slippage、liquidity 或 capacity 未达门槛；
5. 任一交易、现金、manual、scenario、drawdown 或 macro risk constraint breach；
6. Broker fill 与 Portfolio position/cash 无法 reconciliation；
7. label/data drift 超限，或未来 return/volume/fill 泄漏到 formation。

## 12. Retirement、rollback 与执行隔离

- owner `RETIRE` 后，Research/Portfolio consumer 停止读取该 active research result；历史 input receipt、result、monitoring 和 lifecycle 不删除。
- rollback 只回到同 snapshot/universe/objective/constraint/cost/upstream-Promotion scope 的 `stack[-2]`，并重新验证当前 input graph 与 11 项 monitoring freshness。
- 无合格旧版本时回到人工管理的 `current_configuration`，不自动运行新搜索、不降低约束。
- 即使 R8 Promotion 完成，进入 Portfolio transition plan、订单生成和 Broker Execution 仍需独立人工批准、consumer UAT 与执行风控；本定义不提供这些授权。
