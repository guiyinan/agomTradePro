# STRAT-01 R1：行业经营驱动与盈利预测基准业务定义

> Capability：`R1 / Forecast Baseline`
> Definition：`strat.r1.forecast-baseline / 1.0.0`
> Policy：`strat.r1.forecast-baseline.policy / 1.0.0`
> Calendar：`strat.r1.cn-quarterly-reporting / 1.0.0`
> Scope：`strat.r1.cn-a-share-operating-model-pilot / 1.0.0`
> Qualification：`strat.r1.paired-forecast-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与生效条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- 本定义只有在 owner 对本文内容作最终 attestation、候选绑定 dry-run 通过且 append-only registration 获单独授权后才生效。
- 文档阶段不创建盈利预测、actual、trial、Promotion 或 Valuation 消费授权。

## 2. 业务目标与主结果

R1 将行业经营事实、研究员假设和模型推断严格分层，形成可解释的季度链路：

```text
经营驱动 → 收入 → 成本/毛利率 → 费用 → 经营利润 → 归母净利润
         → 经营现金流 → base/bull/bear 敏感性 → 估值输入候选
```

主结果是一份完整配对的季度预测试验：每个 `period × metric` 同时存在候选预测、selection 前登记的简单基准和当时可知的 actual manifest。任何缺格都使整个 trial `BLOCKED`。

## 3. Scope 与 universe

首版只覆盖中国 A 股中满足以下全部条件的单一 owner-approved 行业 pilot：

1. 行业使用独立、版本化的经营模板，不与其他行业共用含混公式；
2. 公司连续盈利，评估窗内所有 MAPE 指标 actual 均非零；
3. 至少 12 个连续季度具有 canonical 财务 actual 和核心经营 KPI 的 PIT 版本；
4. 财务、经营 KPI、行业 membership、报告日历和单位规则均有 Data Center Publication/PIT manifest；
5. 预测只服务研究比较，不自动进入估值、组合或交易。

首个行业优先使用“连锁餐饮/门店型消费”语义，核心 driver 至少包括期初门店、净开店、同店销售、客单价、翻台/订单量、毛利率和费用率。具体公司名单不写入本文；由 scope registry 按上述规则在 selection 前冻结并哈希。

下列对象不进入 v1 universe：评估窗内持续亏损公司、财务重述未完成公司、缺 PIT actual 的公司、经营模板无法解释主要收入来源的多元化公司，以及仅靠 LLM 生成且不可复算的预测。

## 4. 事实、假设与推断

| 类型 | 定义 | 允许来源 | 强制 lineage |
|---|---|---|---|
| `observed_fact` | 截止预测时点已公开且可验证的经营/财务事实 | Data Center canonical fact | dataset、subject、period、metric、unit、revision、available_at、manifest |
| `human_assumption` | owner 或获授权研究员显式给出的未来 driver 假设 | 签署的 scenario assumption set | author、reason、base/bull/bear、recorded_at、valid_until |
| `model_inference` | 由已批准模板和输入现场计算的派生值 | Equity/Sector typed template run | template/version、input seal、code version、output hash |

三类 lineage 互斥。历史预测不得因新公告、重述或当前最佳认知而覆盖；修订必须形成新版本并保留旧版本。

## 5. Calendar 与 cutoff

- IANA timezone：`Asia/Shanghai`。
- 基本频率：自然季度；period end 为 `03-31 / 06-30 / 09-30 / 12-31`。
- 预测 origin：公司最近一期定期报告 canonical `available_at` 后的首个交易日 `16:30`；同一 trial 的 1Q–4Q horizon 共用一个 origin。
- cutoff：只允许使用 `available_at <= forecast_origin_at` 且 manifest 未过期的版本；公告所属期、发布时间和入库时间不能互相替代。
- actual：以 owner-approved actual source definition 的 first eligible vintage 为主评估值；后续重述单独进入 revision sensitivity，不回填原 trial。

## 6. 预测 horizon、scenario 与输出

- horizon：未来 4 个完整季度；滚动更新产生新 forecast revision，不修改旧 revision。
- scenario：`base / bull / bear` 三套 driver 必须完整；qualification 只比较 selection 前指定的 `base`，bull/bear 只用于敏感性和证伪。
- 必须输出：营业收入、毛利率、经营利润、归母净利润、经营现金流及关键 driver；估值敏感性必须引用同一 forecast revision。
- 若 driver 单位、模板 DAG、calendar 或 actual metric set 不一致，整个 run `BLOCKED`。

## 7. Benchmark 与成本语义

主 benchmark 为 `seasonal_naive`：对流量/金额指标使用同季度上年 actual，对利润率指标使用上年同季度值；只能读取 forecast origin 时已 available 的 actual。若 4 季度 lag 不完整，该 subject 不参加 qualification，不使用 last-available 值补齐。

`external_consensus` 可作为附加观察，但不得替代主 benchmark，也不得在候选构建后选择更弱的 benchmark。

R1 是预测准确性研究，不形成交易，因此 transaction cost 与 market liquidity 在本定义中不适用。数据许可、采集成本和人工维护成本写入运维预算，不从预测误差中扣减。

## 8. Sample window

| 项目 | 最低要求 |
|---|---:|
| duration | 36 个连续自然月 |
| periods | 12 个连续季度 |
| samples | 每个 metric 至少 12 个完整配对样本；五项核心 metric 合计至少 60 格 |
| coverage | 每个 metric 与完整 `period × metric` manifest 均不低于 `0.95` |
| horizon coverage | 1Q、2Q、3Q、4Q 各至少出现 3 次 |

同一 company/industry/scenario/purpose/horizon/calendar/metric-set 才能合并；跨 scope 样本不得拼接。

## 9. Qualification thresholds

误差均在完整 paired rows 上现场重算；`minimum_improvement` 表示候选误差相对 benchmark 误差的绝对改善量。

| metric | error metric | 最大候选误差 | 相对 benchmark 最小改善 | 零 actual 规则 |
|---|---|---:|---:|---|
| `revenue` | MAPE | `0.15` | `0.03` | `BLOCK` |
| `gross_margin` | MAE（小数比例） | `0.03` | `0.005` | 不涉及除零 |
| `operating_profit` | MAPE | `0.25` | `0.03` | `BLOCK` |
| `net_profit_attributable` | MAPE | `0.25` | `0.03` | `BLOCK` |
| `operating_cash_flow` | MAPE | `0.30` | `0.03` | `BLOCK` |

全部 metric 同时通过、coverage 通过、所有 invalidation rule 未触发，trial 才为合格。误差相同由 benchmark 获胜。合格只允许请求人工 Promotion review。

## 10. Falsification 与 invalidation

以下任一条件证伪当前版本：

1. 任一核心 metric 连续 2 个季度超过上表最大误差；
2. 任一季度 actual/PIT coverage 低于 `0.95`；
3. 财务重述使原 actual 的收入或归母净利润绝对变化超过 `5%`；
4. 实际门店数、同店销售或毛利率连续 2 季度落在 base 假设区间之外；
5. 行业模板、metric unit、calendar、source definition 或 scope membership 发生未版本化变化；
6. forecast origin 之后才 available 的事实进入任何历史输入；
7. 经营现金流方向连续 2 季度与利润方向背离且模板未能给出已签署解释。

证伪后停止向下游提供 active candidate，生成 owner review，而不是自动改写假设。

## 11. Label、retirement 与 rollback

- 标签只允许 `observed_fact / human_assumption / model_inference` 与 `base / bull / bear`；不得把规则分数写成概率。
- 出现 lineage 泄漏、未来数据、hash/canonical owner 错配时立即 `BLOCKED` 并进入 retirement review。
- 连续 2 个已完成 monitoring period 触发第 10 节任一性能条件时，要求人工 `RETIRE`。
- rollback 只允许回到同 scope lifecycle 的 `stack[-2]`，并重验旧版本的 source、calendar、valid_until 和完整 trial；证据过期的旧版本不能恢复。
- 未存在可恢复版本时保持无 active R1 forecast，不回退到未治理的旧预测或人工默认值。

## 12. 下游授权边界

R1 Promotion 只表示内部研究预测版本合格。Valuation 读取、正式估值展示、决策使用和交易执行分别需要独立 consumer contract 与 UAT；本定义不授予这些权限。
