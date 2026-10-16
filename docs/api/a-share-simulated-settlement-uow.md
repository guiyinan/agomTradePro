# 普通模拟成交与结算事务端口

本端口是 ASH-02 的局部基础设施候选，不代表 ASH-03 完成。现有 `ExecuteBuy/ExecuteSell`、自动模拟、真实成交导入和 QMT 尚未切换。缺少正式日历发布适配器、明确费用适用范围及调用方交易准入检查时，不应将此端口装配成用户可用交易入口。

## 装配和责任

`apps.simulated_trading.execution_settlement_composition` 提供两个显式工厂：`build_execute_settlement_bound_simulated_trade_use_case()` 和 `build_release_due_simulated_settlements_use_case()`。调用方必须提供数据库 alias、带时区的 clock、Risk V3 rule reader，以及正式发布日历 reader；没有默认规则、交易所、日历、时钟或网络刷新。成交工厂让账本和 FeeConfig 读取共用同一个 alias 的 repository。

该事务只更新普通模拟账户。调用方仍须在成交前完成数量、价格、证券身份与状态、盘中阶段、账户能力和风险准入；日级日历不能证明这些条件。真实成交导入保留券商事实与实收费用，不走模拟预估扣款。

## 成交输入与重放

`SimulatedTradeIntent` 绑定用户、账户、证券身份、精确资产代码、资产类型、市场、板块、方向、数量、价格和账户内幂等键。Decimal 数值等价的输入，例如 `100` 与 `100.000000`，使用相同规范化请求摘要；不同业务输入重用同键返回冲突。

Application 在锁外读取 V3 bundle、费用快照与完整日历证据。Repository 在单个同 alias 事务中依次锁定账户、目标持仓及按主键排序的未结算买入成交，然后重新读取时钟，校验时钟未倒退、证据仍有效、日期及覆盖仍一致。账户锁串行化同账户成交；重放只返回已持久化、内容完整且摘要匹配的结果，不重复变更账本。

新增买入增加总持仓；可卖量仅按显式结算 lag 释放。卖出消耗已可卖股份，不消耗待结算批次。现金、费用分项、持仓、账户汇总和成交记录一起提交，任一写入失败整笔回滚。账户市值按本次目标持仓重估差额调整，保留其他资产部分；这不修复历史失真的账户汇总。部分卖出从持仓实际存储总成本按比例分摊，最后清仓带走剩余成本，避免从已舍入均价重建成本。

卖出费用高于成交毛额时，可由账户现金支付差额；资金不足则阻断并回滚，不允许透支。此行为属于正常模拟估算，不声称券商实收一致。

## 结算释放

每笔新买入在现有成交行中保存原 V3 bundle、结算 policy、原 lag、交易会话和当时正式日历引用。后续释放依据当前完整已发布日历，从原买入会话重新数开市会话，并使用该批次的原 lag。日历修订导致原预计释放日不再满足会话数时，应延后释放；不得仅比较旧预测日期，也不得改用新规则的 lag。

释放是显式写用例。查询没有隐式释放副作用；释放使用同一账户、持仓、批次锁顺序。已释放批次不重复加可卖量，并另外保存实际释放使用的日历与知识时点。原交易 bundle 失效不永久禁止其历史已成交股份结算，但释放日历和账户范围仍须完整验证。

## 发布摘要与费用边界

日历 snapshot 的 `content_hash/record_digest/raw_payload_hash` 是带 `sha256:` 的摘要；正式 member 的 `fact_content_hash`、publication hash、policy hash 是独立的 64 位摘要。它们各有验证用途，不能互相代替。仅有未发布的 source snapshot 不满足 `PublishedExecutionCalendarReader`。

当前费用来源是 FeeConfig 实际存储的 binary64 值，使用 `Decimal.from_float` 保留，并标记 `NORMAL_SIM_ESTIMATED / DATABASE_BINARY64`；按分项 HALF_EVEN 舍入至分，完整快照及口径纳入摘要。新成交要求[费用 V2 的完整精确 case](a-share-simulated-fee-policy-v2.md)，未知市场、资产、板块或方向不能落入零费用。原 V1 快照/hash/公式仅保留用于历史收据核验，不自动升级或重扣。真实费率、适用范围和正式日历仍需配置及联合验收，不能因本地政策算法通过而声称沪深北实费制已覆盖；旧问题与迁移边界见[费用适用范围缺口](a-share-simulated-fee-applicability-gap.md)。

## 迁移与验收边界

`simulated_trading.0024_settlement_bound_trade_uow` 在现有成交表增加可空追踪字段与成对幂等约束。旧成交不会被自动标成已结算，不重算旧实收费用，不重写旧可卖量，也不创建第二套账本。日历事实由 `data_center.0099_exchange_calendar_snapshot` 承载。

局部验收包括 SQLite 与 PostgreSQL 真实迁移 operations 的升级、回退、再升级，以及旧 real 账户、费用和 RawPayload 保持不变；这与全历史数据库回放、生产迁移和用户入口验收分别报告。并发验收必须使用 PostgreSQL 两个连接，SQLite 跳过不算通过。
