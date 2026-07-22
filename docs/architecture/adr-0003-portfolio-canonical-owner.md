# ADR-0003：portfolio 作为组合构建唯一 owner

状态：Accepted（2026-07-22）

## 决策

`strategy` 只输出 `TargetPortfolio`；`portfolio` 根据冻结持仓、价格和市场事实完成差额、约束、订单草案、审批与执行交接。`simulated_trading` 只消费已批准且未过期的计划。原 transition plan 和 order intent 表不搬数据，通过 `SeparateDatabaseAndState` 转交 Django owner，旧模块仅保留一个稳定版本的兼容入口。

## 后果

回测、模拟盘和未来实盘可以共享同一套纯 Domain 规则。切换 flag 默认关闭；旧写入归零一个稳定版本后才能删除兼容层。

