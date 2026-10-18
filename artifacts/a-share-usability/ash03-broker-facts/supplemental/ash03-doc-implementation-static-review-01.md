# ASH03 API 文档与实现静态核对

范围：只读对照 `docs/api/a-share-broker-trade-reconciliation.md` 的现金、成本、绩效与回退段，核验 Sim 0032/0033、每日净值阻断、自动退出阈值和 Position 通用保存语义。没有运行 QA、测试、项目导入、数据库操作或 Git。

## 结论

未发现会造成错误金融行为描述的 P1/P2。0032/0033、DNV 的早退和自动退出阈值与文档主张一致。建议收窄两处文案，以便读者不把零写保证扩大到调用链的所有记录，也不把成本经济字段理解为所有持仓字段。

## 逐项核对

- 文档第 71 行关于现金：0032 的 forward 只更新 `cash_known` 与 `cash_reconciliation_status`；模拟账户标成 `True/simulated_ledger`，real 账户标成 `False/unverified`，不改现金数值或时钟。当前组合 Facade 在 `cash_known` 不是 True 时将现金和总资产返回为 `None`，策略现金读取抛出 `ACCOUNT_CASH_UNKNOWN`。与文档相符。0032 reverse 检查 real 账户、未知现金及非 `simulated_ledger` 状态，并在 PostgreSQL 原子迁移内锁账户表；文档第 85 行的保护说明准确。
- 文档第 73 行关于历史成本：0033 仅添加 `NULL` 默认的成本/费用知识列，forward 不重写经济值；reverse 对 Position 和 SimulatedTrade 中任一 `NULL/False` 标记拒绝删列，并在 PostgreSQL 事务内锁相关表。文档第 85 行准确。
- 文档第 77 行关于 DNV：`DailyNetValueService.record_and_update_performance()` 依次在现金未知、已执行 SELL 成本/费用/PnL 不完整、持仓估值未知时返回 `outcome="blocked"` 和稳定原因。这三处都发生在读取历史净值、upsert 每日记录、重算绩效及保存账户之前；就该 DNV 用例自己的账户绩效与每日净值/快照写入而言是零写。若“历史”意指调用链所有执行结果/诊断信息，范围略宽：`AutoTradingEngine._record_performance_outcome()` 会将后续绩效失败加入返回的自动交易 outcome，代码为 `ACCOUNT_PERFORMANCE_UPDATE_FAILED`。建议把句子明确限定为“该净值用例的 blocked 分支不写账户绩效或每日净值历史/快照；调用方保留阻断结果”。这是边界澄清，不是 DNV 零写行为的反例。
- 文档第 77 行关于自动退出：`auto_trading_exit_evaluator.py` 仅在 `valuation_known is True` 且 `cost_basis_known is True` 时依据浮动盈亏百分比触发 `ACCOUNT_STOP_LOSS` 或生成浮亏卖出文案；禁投池等独立建议在这些阈值判断之前处理。与“价格/收益阈值需要估值与成本已知，独立证伪与建议沿用原规则”一致。
- 文档第 73 行关于通用保存：现有行的合并规则确实不会让 `False` 升级，也不会在经济字段未显式带知识状态且相关值变化时继续保留旧 `True`。`position_repository.py` 在覆盖模型字段前，以 Decimal 比较 `quantity`、`avg_cost`、`total_cost`；旧状态 `True` 在这三项不变时保持 True，任一变化且 incoming 状态为 `None` 时降为 `None`。已有 `False` 保持 False；已有 `None` 经该现有行合并即使 incoming 是 True 也仍为 None。新行由 mapper 按传入状态初始化。文档没有与这些规则直接矛盾，但“经济字段”较宽泛且省略 None 不升级这一点。建议明确写为“现有行的 quantity、avg_cost 或 total_cost 变化且未传入知识状态时，旧 True 降为 None；False 保持 False，通用合并不将历史 None 升为 True；新行仍按显式输入初始化”。

## 核对字节

| 文件 | SHA-256 |
|---|---|
| `docs/api/a-share-broker-trade-reconciliation.md` | `1eac72f37d01677c640f5306a77b175c2fad34cf9484f651d37e10b15983f6a3` |
| `apps/simulated_trading/migrations/0032_cash_knowledge.py` | `33f70e51043c4b6654532701c585d6753a40cfa2f8c00ae791359b0c1d7249ff` |
| `apps/simulated_trading/migrations/0033_cost_basis_knowledge.py` | `be6aecbe962a1dc4e6cd49c25358c4197158536859cb267dd3fb6df6ed0ae092` |
| `apps/simulated_trading/application/daily_net_value_service.py` | `9dbc6e5ab099e918b9f844e76b63e9f73af44eaf35f7efe5edd1e583854c54ac` |
| `apps/simulated_trading/application/auto_trading_exit_evaluator.py` | `211d7e574d67f64f1ae2cd2ab4af104f72d7514b93aa13503556e186621798d0` |
| `apps/simulated_trading/application/auto_trading_engine.py` | `eb93b2cb85f0418fb135e16a69e1d1938e101ceb8d2085e5adf03766b6dab394` |
| `apps/simulated_trading/infrastructure/position_repository.py` | `18cace68b560a7aa02600f16b80e500dfe6c224c427a145596b9c7104c188294` |

