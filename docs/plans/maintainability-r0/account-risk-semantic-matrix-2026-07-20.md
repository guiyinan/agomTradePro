# R0 Account / Risk Center 语义矩阵

> 状态：已冻结
> 原则：只合并同语义、同单位、同作用域字段；持仓状态与账户政策不得因名称相似而合表

## 1. Risk Center 政策字段

| 字段 | 语义与单位 | 作用域 | 当前消费者 | 优先级 | 迁移目标 |
|---|---|---|---|---|---|
| `max_total_position_pct` | 总仓位上限，0-1 | global/template/account | risk resolver、trade guard | exception > global floor约束 > account override > template | 留 `risk_center` |
| `max_single_position_pct` | 单标的仓位上限，0-1 | 同上 | trade guard | 同上 | 留 `risk_center` |
| `max_daily_loss_pct` | 日损失上限，0-1 | 同上 | risk checks | 同上 | 留 `risk_center` |
| `max_drawdown_pct` | 最大回撤上限，0-1 | 同上 | risk checks | 同上 | 留 `risk_center` |
| `max_stop_loss_pct` | 账户允许的单持仓止损距离上限，0-1 | 同上 | account stop-loss use case、trade guard | 对持仓配置取 `min(config, effective_policy)` | 留 `risk_center`，不吞并持仓配置 |
| `take_profit_pct` | 账户止盈政策上限，0-1 | 同上 | account take-profit use case、trade guard | 对持仓配置取 `min(config, effective_policy)` | 留 `risk_center`，不吞并持仓配置 |
| `min_cash_pct` | 最低现金比例，0-1 | 同上 | risk resolver/check | floor 取更严格下限，exception 可放宽 | 留 `risk_center` |
| `force_stop_loss` | 是否强制启用止损 | 同上 | risk resolver | global floor true 优先，exception 可放宽 | 留 `risk_center` |
| `hard_exclusions` | 禁投集合 | 同上 | risk resolver/trade guard | floor union，exception 显式覆盖 | 留 `risk_center` |

## 2. Account 交易配置模型

| 模型/字段族 | 语义与单位 | 作用域 | 当前消费者 | 与 Risk Center 关系 | 迁移目标 |
|---|---|---|---|---|---|
| StopLossConfigModel | 持仓实际止损类型、正数 pct、追踪高价、激活/触发状态 | position | account stop-loss use cases/admin | 受 `max_stop_loss_pct` 和 `force_stop_loss` 约束，不同语义 | `portfolio` |
| TakeProfitConfigModel | 持仓实际止盈 pct、分批点位、active 状态 | position | account take-profit use cases/admin | 受 policy `take_profit_pct` 上限约束，不同语义 | `portfolio` |
| StopLossTriggerModel | 已发生触发价格、时间、原因、PnL | position/audit event | stop-loss 执行与审计 | 事实记录，绝不并入参数 mixin | `portfolio` |
| TradingCostConfigModel | 组合实际佣金/印花税/过户费与最低佣金 | portfolio | account portfolio API/services | 非风险政策 | `portfolio` |
| TransactionCostConfigModel | 市场×资产类别成本与滑点/预警阈值 | market/asset class | transaction-cost use case | 非风险政策；可作为组合默认值来源 | `portfolio`（执行成本目录） |
| MacroSizingConfigModel | regime/pulse/温度/回撤驱动的版本化仓位系数 | system/global | account config API、sizing workflow | 不是仓位上限；最终 sizing 仍受 risk policy 约束 | `portfolio`（sizing policy） |
| InvestmentRuleModel | 建议文案与匹配条件 | user/global recommendation | account 建议 UI | 非风险执行政策 | R4 暂留 account；后续 recommendation 单评审 |

## 3. 冻结的消费者切换顺序

1. 新 `portfolio` owner 以旧表和旧 `app_label/db_table` 建立 repository facade；
2. account Interface/Application 切到 portfolio facade，API path/serializer 不变；
3. risk_center 继续输出 effective policy，portfolio 止损止盈通过 Protocol 读取；
4. 验证单位均为 0-1 后再切写入口；
5. 只有双读比对通过后，才评审模型 app identity 的 state migration。

R4 不得把 strategy/simulated_trading 自有的百分比字段顺手合并；它们的单位存在 0-100 与 0-1 差异，必须另立语义迁移。
