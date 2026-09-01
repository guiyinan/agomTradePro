# STRAT-01 R5：固定收益相对价值与久期业务定义

> Capability：`R5 / Relative Value`
> Definition：`strat.r5.fixed-income-relative-value / 1.0.0`
> Policy：`strat.r5.paired-oos-relative-value.policy / 1.0.0`
> Calendar：`strat.r5.cn-fixed-income-daily / 1.0.0`
> Scope：`strat.r5.cny-cash-bond-relative-value / 1.0.0`
> Qualification：`strat.r5.relative-value-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与生效条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- 本定义只有在国债曲线、政策性金融债曲线、信用估值、Bond Master、CashFlow、交易日历、成本和流动性均有真实 Publication，且久期/凸性完成外部金样本对账后才可注册。任何一项缺失均为 `BLOCKED`。

## 2. 业务目标与研究边界

R5 研究同币种、可比期限和可解释风险来源下的固定收益相对价值，回答“候选组合相对于久期/DV01 中性的简单基准，在完整成本、流动性、容量和信用损失约束后是否仍有增量价值”。v1 只允许四类可分解证据：

1. 历史利差分位；
2. 评级迁移；
3. 流动性溢价；
4. 曲线、关键期限、陡峭/平坦、蝶式或信用利差相对价值。

结果是研究组合和风险拆解，不是债券推荐、收益承诺或订单。单点宏观收益率不能拼成曲线，ETF 久期标签不能替代券级现金流，缺失票息、到期日、信用等级或流动性不得默认填充。

## 3. Scope、universe 与分组

v1 universe 为人民币固定利率现券：记账式国债、政策性金融债，以及具有可验证信用估值的 AAA 信用债。浮息债、可转债、资产证券化产品、永续债、含权债、违约/重组债、境外债、跨币种工具和衍生品不在 scope。

每个候选成员必须同时满足：

- exact Bond Master、settlement-specific CashFlow 和交易日历可回读；
- clean/dirty price、应计利息、YTM、Macaulay/modified duration、convexity 和 DV01 可复算；
- curve kind、currency、issuer type、rating、maturity bucket 和 cohort 在 formation cutoff 前已发布；
- 报价、成交活跃度、bid-ask、可交易 notional、融资和借券/shortability（如策略需要）均有时点证据；
- 不处于停牌、违约、重大条款变更或数据失效状态。

同一比较组必须币种一致、curve role 明确、modified duration 差异不高于 `0.25` 年，并遵守同一评级/发行人/税收/清算规则。任何人工排除都必须在 formation 前登记，不能依据后续收益删样本。

## 4. Calendar、价格与结算语义

- IANA timezone：`Asia/Shanghai`。
- 研究形成频率：交易日；formation cutoff：每个中国银行间/交易所共同交易日 `17:00`。
- 最早可执行观察窗口：下一共同交易日，即 `T+1`；不得把 cutoff 后报价、成交或曲线 revision 计入当日 formation。
- clean price 不含应计利息；dirty price 等于 clean price 加 settlement date 对应应计利息；收益和成本使用实际结算现金流。
- coupon、day-count、付息频率、business-day convention、ex-coupon、税收和 settlement lag 全部来自 exact Bond Master/CashFlow/Calendar，不在代码或报告中推断。
- 早于 `available_at` 的 revision、未来评级迁移或事后修订曲线一律视为泄漏。

## 5. 计量、对账与组成

所有研究结果必须同时报告价格、收益率和风险量纲，且通过以下最低对账：

| 对账项 | 最大绝对差异 |
|---|---:|
| clean/dirty price | 每 100 元面值 `0.01 CNY` |
| YTM | `1 bp` |
| modified duration | `0.05` 年 |
| cash-flow date/amount | 必须 exact match |
| 组合 DV01/CS01/convexity 恒等式 | `0.01%` 相对误差 |

Composite score 必须保留历史分位、评级迁移、流动性溢价和曲线相对价值四项原始贡献；缺一项时不能把剩余权重归一化成完整分数。score 仅是有向排序，不是违约概率、上涨概率或预期收益率。

## 6. Benchmark、cost 与 liquidity

primary benchmark 为同一 universe、formation 和 holding window 下的 `duration_dv01_neutral_carry_hold`；无法构造该基准时使用预注册的 `no_trade_current_holdings`，并在整个 trial 内保持不变。候选与 benchmark 共用价格源、结算规则、信用事件、成本和可交易性。

成本按实际腿和方向 once-only 计入：bid-ask、手续费、税费、冲击、融资、借券和 settlement cost；不得既在 price 中扣减又在 portfolio outcome 中重复扣减。每个 round trip 的总 target cost rate 不高于 `0.005`。

每腿 planned notional 不得超过 formation 时可交易 notional 的 `5%`；组合 peak capacity utilization 不高于 `0.80`。无 shortability 的空头腿、流动性 breach 或无法完成 settlement 的候选直接不可行，不能用理论价格替代。

## 7. Sample window

| 项目 | 最低要求 |
|---|---:|
| 历史 duration | 5 个连续自然年 |
| PIT daily observations | `1,000` 个 |
| paired OOS periods | `24` 个完整月度 period |
| complete observation count | `24` 个 |
| universe/price/outcome coverage | `0.95` |
| 每个比较组有效债券 | 至少 5 只 |

coverage 分母是预注册的完整候选集合；停牌、缺报价和信用事件成员仍留在分母。每个 OOS period 必须配对同一候选与 benchmark，不能拼接非重叠赢家。

## 8. Qualification thresholds

候选必须同时满足 Research-owned Promotion policy 的全部门槛：

| policy field | 门槛与量纲 |
|---|---:|
| `minimum_observation_count` | `24` 个完整月度 observation |
| `minimum_coverage_ratio` | `0.95` |
| `minimum_excess_net_return` | 年化成本后至少 `0.01` |
| `maximum_drawdown_increase` | 相对 benchmark 至多 `0.02` |
| `maximum_total_cost` | 每次 round trip 至多 `0.005` |
| `maximum_liquidity_breach_ratio` | `0` |
| `maximum_capacity_utilization` | `0.80` |
| `maximum_realized_credit_loss` | `0` |

资格只允许进入人工 Promotion review。任何一项失败、单位不一致、outcome 非 Portfolio owner、或 fixed-income result 与 Portfolio outcome 不配对时，整体为 `BLOCKED`，不得按多数票通过。

## 9. Post-promotion monitoring

每个完整月度 period 必须由 canonical owners 发布以下七项 raw metric：

| metric | 健康条件 |
|---|---:|
| `coverage_ratio` | 至少 `0.95` |
| `excess_net_return` | 至少 `0` |
| `drawdown_increase` | 至多 `0.02` |
| `total_target_cost` | 至多 `0.005` |
| `liquidity_breach` | 至多 `0` |
| `peak_capacity_utilization` | 至多 `0.80` |
| `realized_credit_loss` | 至多 `0` |

minimum complete periods 为 6；evidence delay 不得超过 period end 后 10 个共同交易日，period age 不得超过 45 个自然日。任一指标连续 2 个完整 period breach 进入人工 retirement review；信用损失、owner/hash/PIT 破坏或不可结算事件立即 `BLOCKED`。monitoring 不自动退休版本。

## 10. Label、falsification 与 invalidation

R5 label 只能是 `relative_value_candidate`、`benchmark`、`blocked`、`qualified_for_review` 四种研究角色；它不是买入/卖出标签。以下任一条件证伪或使当前版本失效：

1. clean/dirty price、YTM、duration、convexity、DV01/CS01 或现金流不能在容差内复算；
2. 曲线、评级、cohort、成本、流动性、容量、借券或结算证据缺失、过期、未来可见或 hash 不一致；
3. 成本后超额收益、drawdown、coverage、liquidity、capacity 或 credit loss 未达门槛；
4. 组合不再 duration/DV01 neutral，或 candidate 与 benchmark 的 universe/window 不同；
5. 债券条款、评级协议、curve role、税收或会计口径发生语义变化；
6. 事后信用事件、当前成分或最终修订价格泄漏到 formation。

## 11. Retirement、rollback 与下游边界

- owner 决定 `RETIRE` 后停止 active publication，但保留完整 result、outcome、decision 和 lifecycle history。
- rollback 只回到同 currency/universe/split/cost/liquidity scope 的 `stack[-2]`，并重新验证所有 Publication、现金流、外部对账和 freshness。
- 无合格旧版本时回到 `no_trade_current_holdings` 研究基准，不自动寻找新券或降低门槛。
- R5 Promotion 只可供 R8 作为一个受治理的输入引用；不授权 current 投资建议、Portfolio transition plan、订单或执行。
