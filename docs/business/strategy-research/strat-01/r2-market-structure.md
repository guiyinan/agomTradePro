# STRAT-01 R2：市场结构与投资者资金流业务定义

> Capability：`R2 / Market Structure`
> Definition：`strat.r2.market-structure / 1.0.0`
> Policy：`strat.r2.explanatory-trial.policy / 1.0.0`
> Calendar：`strat.r2.cn-monthly-market-structure / 1.0.0`
> Scope：`strat.r2.cn-a-share-investor-structure / 1.0.0`
> Qualification：`strat.r2.two-cycle-explanatory / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与生效条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- 本文批准的是描述性/解释性研究口径。它不授权生成投资者行为预测、当前交易信号或执行建议。

## 2. 业务目标

R2 统一回答“哪些主体以何种可观测口径改变了哪些资产组的资金或持仓结构”，并强制区分真实观察与代理解释。输出包括总量变化、变化速度、历史分位和跨主体差异，但不把代理数据写成真实主体行为。

## 3. Actor taxonomy 与 measure semantics

v1 taxonomy 至少覆盖：

- `industrial_capital`：回购、增减持、解禁后可交易供给等发行人/大股东行为；
- `foreign_investor`：有合法来源的跨境持有或成交变化；
- `household`：居民直接/间接入市的可审计代理；
- `margin_financing`：融资余额及融资交易；
- `insurer`：保险资金可观察持仓/流量；
- `mutual_fund_etf`：公募基金、ETF 申赎和持仓变化。

每条 series 必须且只能选择一种 measure：

| measure | 含义 |
|---|---|
| `flow` | 某期间进入/流出定义边界的金额 |
| `holding_change` | 期末持仓减期初持仓，包含估值与交易拆分说明 |
| `stock` | 某时点存量，不得称为净流入 |
| `transaction_net_flow` | 买入成交减卖出成交，不能与申赎或持仓变化互换 |

每条 series 同时登记 unit、frequency、source、revision policy。代理 series 必须标记 `is_proxy=true`，给出 target actor 和 methodology；直接 series 不得携带 proxy 标签。

## 4. Scope 与 versioned asset groups

- 市场范围：中国 A 股及在境内交易、以 A 股为主要底层的 ETF。
- 资产组允许行业、风格、规模、AI/非 AI、新旧经济、内外需等 owner-approved 分类，但每组必须有 revision 和 PIT membership。
- formation 时点只能使用当时已 available 的成分；禁止用当前成分回填历史。
- 同一研究快照中的 actor、series、asset group、calendar 和 taxonomy 必须属于同一 Publication graph。
- 无法取得可靠定义的 actor 保留缺失，不用“主力资金”等含混字段替代。

## 5. Calendar 与 cutoff

- IANA timezone：`Asia/Shanghai`。
- 基本频率：月度；period 为自然月半开区间，月末最后交易日结束。
- cutoff：次月第 5 个交易日 `18:00`。只有此时前 available 的 series revision 和 membership 可进入该 period。
- 晚到数据进入下一 revision；不得覆盖已封存 period。
- taxonomy/calendar Publication 必须在 selection cutoff 前记录并覆盖完整试验窗。

## 6. Sample window 与两个市场周期

| 项目 | 最低要求 |
|---|---:|
| duration | 72 个连续自然月 |
| periods | 72 个非重叠月度 period |
| market cycles | 恰好 2 个完整、互不重叠且 selection 前定义的 cycle；每个至少 24 个月 |
| samples | 每个 `series × period` 至少 1 个 canonical observation；每个 actor 至少 72 个 period 值 |
| membership coverage | 每个 `series × period` 不低于 `0.90` |
| actor count | 每个 trial 至少 4 类 actor，其中至少 2 类为 direct measure |

cycle label 由 owner-approved classification version 给出，只用于分层验证；不得在看到试验结果后移动 cycle 边界。

## 7. Benchmark 与 explanatory design

基准模型只含同期市场收益、已实现波动、成交额变化和月度固定效应。候选解释模型在完全相同样本上增加预注册 actor-series 特征。

R2 只评估增量解释力：

- 不发布未来收益预测；
- 不把相关性写成因果；
- Audit 必须从 canonical observations 现场复算结果；
- 两个 cycle hypothesis 构成固定 family，使用 `holm-v1`，最大 adjusted p-value 为 `0.05`。

业务语义字段 `cost` 与 `liquidity` 均为 `not_applicable_to_descriptive_trial`：交易成本和市场流动性不直接适用于描述性 R2 trial，不能填零表示已评估。若未来把 R2 结果用于策略信号，必须新建含成本、流动性和可交易性的独立 Promotion policy。

## 8. Qualification thresholds

| metric | unit | trial threshold | monitoring threshold | 方向 |
|---|---|---:|---:|---|
| `coverage_ratio` | `ratio` | `0.90` | `0.85` | at least |
| `stability_score` | `ratio` | `0.70` | `0.60` | at least |
| `incremental_explanatory_power` | `delta_r2` | `0.02` | `0.01` | at least |

补充门槛：

- 两个 cycle 的 coverage、stability 和 `delta_r2` 均分别通过；不以合并样本掩盖单周期失败；
- Holm-adjusted p-value 均不高于 `0.05`；
- minimum observations per series-period 为 `1`；monitoring 至少有 12 个完整月；最新事实年龄不超过 45 天；
- label protocol 和 expected label-set hash 必须与 policy 一致；
- 全部结果固定为 `descriptive / explanatory / research_only`。

## 9. Falsification 与 invalidation

以下任一情况证伪当前解释：

1. 任一 cycle 的 `delta_r2 < 0.02` 或 adjusted p-value `> 0.05`；
2. 加入 actor 特征后仅样本内改善，另一个 cycle 不改善；
3. proxy 与 direct measure 方向长期冲突且 methodology 无法解释；
4. membership coverage 低于 `0.90`，或完整分母被事后缩小；
5. flow、stock、holding change、transaction net flow 被混用；
6. taxonomy、calendar、asset group 或 revision policy 在未升版时改变；
7. 任何 observation、membership 或 Publication 在其 `available_at` 前被历史查询读到；
8. label drift、source license 失效或数据提供方改变核心口径。

## 10. Retirement 与 rollback

- 任一最新 period breach 产生 `BREACHED`；同一 metric 连续 3 个完整 period breach，或出现 label drift，要求人工 retirement review。
- PIT 泄漏、owner/hash 错配、Publication 被替换或 family 不完整时立即 `BLOCKED`。
- `RETIRE` 不删除历史 snapshot、trial、monitoring 或 Audit outcome。
- rollback 只回到同 taxonomy/calendar/scope lifecycle 的 `stack[-2]`；旧版本必须仍有有效 Publication、完整两个 cycle 和未过期 evidence。
- 没有合格 rollback target 时不发布 R2 active explanation。

## 11. 用户文案边界

允许表述“在给定口径和样本内，某主体代理与市场结构变化存在稳定解释关系”。禁止表述“某类资金一定入场/撤离”“该资金流将导致上涨/下跌”或任何未获独立验证的因果结论。
