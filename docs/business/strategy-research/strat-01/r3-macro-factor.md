# STRAT-01 R3：高频宏观因子与 Nowcast 业务定义

> Capability：`R3 / Macro Factor`
> Definition：`strat.r3.macro-factor-nowcast / 1.0.0`
> Policy：`strat.r3.nested-temporal-research.policy / 1.0.0`
> Calendar：`strat.r3.cn-trading-and-release-calendar / 1.0.0`
> Scope：`strat.r3.cn-macro-target-proxy-universe / 1.0.0`
> Qualification：`strat.r3.oos-factor-qualification / 1.0.0`
> 状态：`READY_FOR_OWNER_ATTESTATION`
> 拟议 `valid_from`：`2026-09-01T00:00:00+08:00`
> 拟议 `valid_until`：`2027-08-31T23:59:59+08:00`

## 1. Owner 与生效条件

- accountable owner：`阿狗涅夫`；repository identity：`agomtradepro-personal-project-owner`；角色：`project_owner / strategy_research_business_owner`。
- owner receipt：[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../../../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，SHA-256 `f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`。
- R3 definition registration 不授权训练数据回填、模型运行、current Publication 或 Promotion；真实 definition provider、PIT manifest 和 Research family 必须另行形成。

## 2. 业务目标

R3 通过可交易代理资产与高频事实，分别研究增长、通胀、利率、信用、流动性和汇率目标，形成“当前状态”和“未来若干月预期”的日频研究因子。模型选择必须是时序嵌套、PIT 可复算且保存失败试验，不能把股票横截面 FactorEngine 复用为宏观时间序列因子。

## 3. Target 与 proxy universe

每个 target definition 必须声明：经济含义、canonical unit、频率、release calendar、revision policy、current/forward horizon 和禁止使用的替代口径。

首版 target family：

- `growth`：实体活动与增长动量；
- `inflation`：价格水平与通胀动量；
- `rates`：政策利率和利率曲线状态；
- `credit`：信用条件与信用利差；
- `liquidity`：货币/融资流动性；
- `fx`：人民币相关汇率条件。

proxy universe 只纳入具有连续 PIT 价格、明确交易日历、成本模型和流动性证据的资产。期货必须有版本化 continuous roll policy 和合约链；ETF/指数代理必须说明可交易性差异。具体代码由 universe registry 在 selection 前冻结，本文不内嵌资产名单。

## 4. Calendar、PIT 与 inference chronology

- IANA timezone：`Asia/Shanghai`。
- 日频研究 cutoff：每个交易日 `16:30`；只能读取 cutoff 前已 available 的 release、价格和合约信息。
- 宏观 release 以官方发布时间或 owner-approved publication lag 为 available time，不以所属期或请求时间代替。
- 训练/OOS row 必须含 target label；current/forward inference row 必须无 label/value，并与 target calendar period 单独绑定。
- `CURRENT` target period 不晚于 knowledge cutoff；`FORWARD` target period 必须晚于 cutoff。
- 历史修订作为新 vintage 保存；不得用最终修订值覆盖历史首次可知值。

## 5. Model family 与 benchmark

候选方法为标准化 Lasso + OLS refit。每个 outer fold 内：

1. 只在 inner training/validation 选择预注册 alpha；
2. outer OOS 不参与 alpha、变量或符号选择；
3. final fold fit 只使用该 fold 的 train + validation；
4. 保存完整 alpha family、入选与未入选变量、标准化参数、系数、权重、显著性、BIC 和 adjusted R²。

每个 fold 同窗比较两个强制 benchmark：

- `historical_mean`：只用 fold training label 的历史均值；
- `fixed_fmp`：selection 前冻结的固定代理资产及权重。

候选必须同时优于两个 benchmark；不得按结果选择较弱 benchmark。

## 6. Cost 与 liquidity semantics

成本由 Portfolio canonical cost model 按资产和 period 提供，包括 bid-ask、手续费、滑点、市场冲击、期货换月和适用的资金成本。成本按目标调仓只计一次，报告 gross、cost、net 和 turnover；缺任一成本成员即 `BLOCKED`。

proxy liquidity 必须满足：

- 评估窗有效价格/成交覆盖不低于 `0.98`；
- 拟模拟交易不超过当日可交易 notional 的 `5%`；
- 期货合约在 roll window 内使用登记规则，不选择事后最优换月日；
- stale、停牌、无报价或不可交易 proxy 不以零收益填充。

## 7. Sample window 与 temporal split

| 项目 | 最低要求 |
|---|---:|
| duration | 8 个连续自然年 |
| daily samples | 每个 target 至少 2,000 个完整交易日 row |
| coverage | target、全部入选 proxy 与 calendar membership 均不低于 `0.98` |
| training | 首个 fold 至少 5 年 |
| validation | 每个 fold 至少 126 个交易日 |
| OOS | 合计至少 504 个交易日 |
| walk-forward folds | 至少 5 个、严格按时间递增 |
| embargo | train/validation/OOS 边界至少 5 个交易日 |

样本 split、alpha grid、optimization metric、random seed 和多个检验 family 必须在首次 selection 前登记。

## 8. Qualification thresholds

全部 target 分别评价，不以表现好的 target 抵消失败 target。

| 指标 | 门槛 |
|---|---:|
| OOS MSE 相对 `historical_mean` 改善 | 至少 `5%` |
| OOS MSE 相对 `fixed_fmp` 改善 | 至少 `5%` |
| 聚合 OOS R² | 至少 `0.02` |
| 各 fold 正向改善占比 | 至少 `0.70` |
| 入选变量方向稳定率 | 至少 `0.70` |
| proxy/target/calendar coverage | 至少 `0.98` |
| 成本后 improvement | 必须仍为正 |
| current/forward freshness | manifest 与 inference row 均在 policy 有效期内 |

同时必须报告 MAE、MSE、R²、IC、adjusted R²、BIC、换手和成本。显著性不替代经济含义；Lasso 非零系数不自动等于合格宏观因子。

## 9. Falsification 与 invalidation

以下任一条件证伪当前因子版本：

1. 连续 3 个完整月的滚动 OOS improvement 对任一强制 benchmark 不为正；
2. 6 个月滚动 OOS R² 小于或等于 `0`；
3. 入选变量方向稳定率低于 `0.60`；
4. 成本后收益不再优于 benchmark，或 turnover/cost graph 不完整；
5. target、proxy、roll policy、release calendar 或 unit 未升版即改变；
6. PIT coverage 低于 `0.98`，或任一未来 vintage/label 泄漏进入历史 row；
7. current/forward output 复用了历史 OOS label row；
8. proxy liquidity 违反 `5%` participation 上限或出现不可解释的长期失配。

## 10. Retirement、rollback 与 Publication

- 任一 chronology/PIT/hash 破坏立即 `BLOCKED`；性能证伪连续 3 个 monitoring period 时要求人工 retirement review。
- owner `RETIRE` 后停止发布该 factor version，但保留完整 artifact、outputs、trial 和 lifecycle history。
- rollback 只允许回到同 target/universe/split/cost scope 的 `stack[-2]`，并重验旧版本 PIT source、calendar、Promotion、monitoring 和有效期。
- 研究 qualification 只允许提交 Research Promotion review；只有 approved Promotion、未退休 lifecycle 和 consumer UAT 全部存在时，才可另行考虑 current Publication。
