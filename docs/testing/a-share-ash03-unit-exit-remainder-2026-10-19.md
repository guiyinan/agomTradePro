# ASH-03 原 §7 的剩余开发与验收范围

**状态：静态库存，未重跑测试。** 依据原计划 §7、§19.72 与已提交的有限交付清单。本次有限 ASH-03 切片已交付 legacy 持仓承接、券商成交事实保全、普通模拟及自动引擎即时成交共用结算 UoW；这不等于原 §7 整单元完成。ASH-03 仍保留为未完成项，当前仓库焦点仍为 ASH-04，本清单不调整该顺序。外部券商现金/持仓核验、Owner M2/M3、实盘资格与完整 ASH-06 回测真实性不列为本批开发前置。

按可独立验收的业务组，原 §7 尚余 **7 组**：

| 组 | 可复用能力、入口与缺口 | 最小后续批次 | 可验证的退出条件 |
|---|---|---|---|
| **1. 订单预留与四种现金状态** | `apps/simulated_trading/application/execution_settlement_uow.py::ExecuteSettlementBoundSimulatedTradeUseCase.execute` 和其 Infrastructure UoW 能锁账户并原子完成即时成交、费用与账本写入。`SimulatedAccountModel` 只有账面现金、现金知识标记与核对状态；没有交易可用、委托冻结、可取余额或未成交订单预留。`PositionModel` 有已知可卖量，但无冻结量。`OrderIntentModel`、`LiveOrderModel.estimated_amount`、`OrderLeaseModel` 分别是意图、金额估值和 Agent 短租约，均未接入模拟账本预留。 | 以现有 simulated-trading settlement / order-intent owner 为边界，在现有账本模型中表达缺少的持久 hold 与幂等状态；复用现有 intent 仅限其接口和归属核验通过后，不新建并行账本。BUY 预留资金和费用预算，SELL 预留已知可卖量；明确账面、交易可用、冻结、可取四种状态的计算关系。仅限模拟，不接通券商实盘。 | 两笔并发订单不能共用同一笔现金或股份；费用预算纳入 BUY 预留；未知现金或可卖量不能产生可用 hold；失败回滚不留 hold；已成交买入的 T+1 待结算记录不当作未成交订单预留。 |
| **2. 部分成交、撤单与费用差额释放** | `apps/broker_execution/infrastructure/models.py` 已有 LiveOrder、OrderLease、BrokerOrderEvent、BrokerFill 与 BrokerCommand；`broker_repository_agent_runtime.py` 已记录逐笔事件、部分成交状态和撤单命令。事件事实可按键去重，但这些对象没有改变模拟预留或释放余量。Live-order evidence gate 仍关闭，不能视为当前可用的预留闭环。 | 为预留账本实现部分成交消费和撤单最终态释放；之后才在单独授权的接线批次把 broker callback 映射到该账本。 | 500 股只成交 300 股后，只消费对应份额并释放剩余 200 股 hold；撤单成功、重复回报和费用实收差额各自只处理一次；撤单待定或拒绝不伪装成取消完成。 |
| **3. 订单预留的停机恢复** | 逐笔模拟成交幂等、T+1 释放和自动 run no-reentry guard 已存在；它们分别保护已提交的交易、已成交待结算行和单次任务，不恢复未成交订单的资金/股份预留。broker lease 过期只清理 Agent 提交租约。 | 针对已持久化的订单 hold，重启时先对照订单、成交事件和当前账本，再继续、释放或保持待核对；不加入整批自动运行续跑。 | 在 reserve 后、成交回执前中断并重启，不重复预留、成交或释放；缺少/冲突的成交事实时保持阻断，不盲目重发，也不将未知结果记成拒单或已取消。 |
| **4. 实际成交费用的修订与冲正** | broker 成交事实有原件保存和重复事实冲突保护。旧费用修改入口 `RecordTransactionCostUseCase.record_actual_cost` → `apps/account/infrastructure/repositories.py::update_transaction_costs` 会直接更新旧 Transaction 字段，未产生追加式费用修订记录。 | 沿现有成交/费用 owner 记录有来源、可追溯且幂等的差额修订或冲正，不另建平行账本；先确定该费用是否已经计入现金。若现金已按旧费用入账，净调整为新实收费用与已入账费用的差额；更高费用产生额外扣款，更低费用产生合法退款，不能一概拒绝负差额。若交易关联不明，或现金是否已含该费用未知，保持 pending，不做现金写入。不得盲目再次扣除完整新费用。 | 原成交、原费用和修订均可读；旧费用 7 改为 9 时仅按 2 的差额调整一次，9 改为 7 时能按 2 退款一次；重复修订不重复扣/退；关联或现金包含关系未知时无现金变更且明确待核对。 |
| **5. 历史可卖量差异与有界修复** | `apps/simulated_trading/management/commands/migrate_account_ledger.py::_migrate_positions` 有 `--dry-run` 摘要，但未提供逐行源—目标差异。实际迁移路径将可卖量设为总量，冲突合并亦将其设为合并总量。已交付的 legacy adoption 会把无来源可卖量保留为 unknown；这没有完成历史差异预览或证据限定修复。 | 先做按账户、source mapping、证券严格匹配的只读逐行差异；修复只针对有结算/成交来源证据的行，保留原值、备份和回滚点。 | dry-run 零写并显示源/目标原值、知识状态和差异；总量 300、证据只支持可卖 100 时只能修为 100；未知或映射歧义保持 unknown 并拒绝修复；可按行回滚。 |
| **6. 普通模拟与回测的 §7 最小结算/成本一致性** | 模拟 UoW 复用 Rule V3、当前交易日历及 Fee V2。回测入口包括 `apps/backtest/domain/services.py::BacktestEngine`、`stock_selection_backtest.py::StockSelectionBacktestEngine` 和 `alpha_backtest.py`；成本口径仍分别包括 flat `transaction_cost_bps` 与 `commission_rate`/`slippage_rate`，未发现它们接入普通结算 UoW / Fee V2 / 当前结算日历。 | 为 §7 退出只选一个现有可达回测入口、一个确定输入和一组支持范围内的买卖，核对与普通模拟 UoW 的费用、现金净额与结算日一致。明确成交价是否已反映滑点，避免再次加收。**ASH-06** 另行承担 PIT、上市退市、公司行为、历史成分及全量回测可信度；这些不扩成本批 §7 最小一致性门。 | 同输入的测试买卖在支持范围内得到相同成交数量、结算会话、费用分项与现金变化；未知费用不伪装为零，滑点不重复计费。ASH-06 全回测退出条件单独登记，不以此项的小样本替代。 |
| **7. 旧自动止损卖出调用** | 入口已存在并注册：`core/settings/celery_schedule.py` 的 `account-check-stop-loss-take-profit-intraday` → `apps/account/application/tasks.py::check_stop_loss_and_take_profit_task` → `AutoStopLossUseCase._execute_stop_loss` → `apps/account/infrastructure/position_repository.py::PositionRepository.close_position`。该路径会关闭旧 Position 并写 legacy SELL；成本各字段用 0 占位并标为 unknown，不经过标准模拟 SELL/Fee V2 或统一可卖量校验。源码注册不能证明当前存在有效配置或任务实际运行，故不标成 dead/inactive。 | 将支持的模拟账户止损接到已存在的普通 SELL 结算及费用入口；对 legacy 账户或缺失可卖/费用证据明确阻断或提示。只处理此现有调用者，不启用实盘或重做全自动止损平台。 | 可验证触发止损沿用普通 SELL 的费用、日历和可卖量规则；资料未知时不关闭全量持仓、不记成已知零费；触发记录、通知及任务 outcome 保持可解释。 |

建议后续按依赖先做第 1 组的模拟订单预留原语，再接第 2、3 组的生命周期和恢复；沿现有 settlement/order owner 增补最少状态，不另建平台或并行账本。第 5 组只读差异预览可独立先做，不替代 OMS 退出条件。第 4 组必须先区分“费用已进现金账本”与“只记录成交事实”，再算可正可负的差额。第 6 组只完成 ASH-03 要求的有限同输入对照，不把 ASH-06 的 PIT、公司行为或完整回测真实性搬入本阶段。第 7 组应保留为旧调用路径的实际兼容缺口，不能因为用户配置/任务运行状态未核验而从计划删除。

本清单为静态整理，没有重新运行测试、QA 或检查数据库中的开放订单、止损配置、历史差异；表内退出条件均为建议验收标准，不代表已通过。ASH-03 有限切片交付与原 §7 整单元退出分开记录；ASH-04 当前 focus 不变。

依据：[主实施计划](../plans/a-share-usability-implementation-plan-2026-10-16.md)；[有限切片交付清单](a-share-ash03-finite-exit-checklist-2026-10-19.md)。实际状态继续由主计划与唯一 registry 登记，本清单不另建状态真源。

## 2026-10-20 G1 局部交付更新

上表保留2026-10-19静态盘点原文。第1组中的持久预留、现金/股份竞争保护及既有写口防绕行已在G1完成本地定向验收并接入开发树；第2组只交付尚未消费hold的取消释放，部分成交消费与事件链尚待后批，第3组重启恢复未完成。详见[G1 验收](./a-share-ash03-g1-order-reservation-2026-10-20.md)。这不关闭七组整单元退出条件，不改变ASH-04焦点、ASH-07前置或生产门禁。

## 2026-10-20 G2A 局部交付更新

第2、3组新增不可变成交回执和完整链只读重放，已完成本地定向验收；尚无原子消费/合格来源接线及停机恢复用户流程，仍未满足整组退出条件。详见[G2A验收](./a-share-ash03-g2-fill-receipt-reader-2026-10-20.md)。第4–7组、ASH-04焦点和ASH-07前置保持。
