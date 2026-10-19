# ASH03 automatic owner-scope final static review

审查对象为当前四处生产实现和 Engine 的消费点。文件摘要均为原始 `read_bytes()` SHA-256；没有执行 QA、测试、数据库操作、项目导入或 Git 命令。

| 路径 | 原始字节 SHA-256 |
|---|---|
| `apps/simulated_trading/application/execution_settlement_uow.py` | `1d18cee28cce57a8521f7ff78958963e13cd7518f99794f5f8851ddcfad89cf9` |
| `apps/simulated_trading/infrastructure/execution_settlement_uow_repository.py` | `67534c32c35713e7890a6150289645c24bee0dd37f491af2495049114cb14468` |
| `apps/simulated_trading/application/automatic_trade_execution.py` | `8aef70d51492e29a38170ea310ff7e4cbabf98caf1ba9a9532bd1878172174f7` |
| `apps/simulated_trading/application/auto_trading_outcome_state.py` | `adcc63123ccaba25d78c76f1f84b4553c5461309b023e9f35b1c0954349e4120` |
| `apps/simulated_trading/application/auto_trading_engine.py` (消费路径核对) | `ab2165d8ac0882b824bb056bf7bd3e5c18439de57352ac65ab33760fa37fc5da` |

锁内 owner-scope P2 已由当前实现覆盖。`execution_settlement_uow.py:75` 定义专用 `SimulatedTradeAccountScopeUnavailable`，保留 `SimulatedTradeExecutionBlocked` 的兼容子类关系并给出稳定 code。Repository 的 `_locked_account` 在首锁查询同时筛选账户主键、simulated 类型、调用方 user_id 和 active 状态；filtered query 无行时直接抛此专用异常，不额外查找或泄露其他 owner。执行 UseCase 和 Repository 的单笔事务边界未被本次差异改写。

Bridge 在专用锁内异常分支映射为 `AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE`。对于 Fee V2 查询先于 Repository 锁执行的时序，通用已知预检异常分支现在用同一个已注入 owner reader 重新读取，并与本次尝试开始时固定的 `user_id` 比较。读取抛错、返回非精确正整数或返回不同 owner 时映射同一稳定 stop code；owner 仍相同则保留原 `AUTO_TRADE_SETTLEMENT_PREFLIGHT_BLOCKED`。专用的 readback/settlement result unknown 仍先行传播，不会被改写成已知零写入阻断。

`AccountAutoTradingState.must_stop` 对 effects-indeterminate、既有 `AUTO_TRADE_OWNER_CHANGED` 和新 `AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE` 返回 true。Engine 的 strategy SELL/BUY 与 legacy SELL/BUY 四处调用点均在处理错误后检查该属性并直接返回，不进入当前账户后续订单循环，也不调用尾部 `_record_performance_outcome`。之前已确认的交易计数保留在 state；执行链接失败仍只记录可恢复 issue，不改变新 stop 语义。按这一范围，Root 报告的 owner 二读失败优先测试与 unit GREEN 证据覆盖预期路径；本 memo 不把该运行证据当作本次独立执行。

有一个条件性边界值得明确，但不影响“owner 发生变化/不可读”这两项既定 P2 的关闭：Bridge 的二读依赖现有 `get_owner_id`，而 `DjangoSimulatedAccountRepository.get_owner_id` 只返回按主键读取的 `user_id`。Fee V2 repository 的前置 scope 还要求 `account_type='simulated'`。如果账户在 owner 预读后、Fee V2 `exists()` 前被管理员改为 `real`，Fee V2 会按通用 storage/preflight 错误拒绝；owner 二读仍返回同一 ID，Engine 因而可把它当普通已知阻断并继续到后续订单或绩效处理。账户类型目前可在 Admin 基础信息编辑，模型保存会按 real 账户语义切换现金知识状态。此时没有成交写入，但“所有不可写 scope 均停止后续工作”尚未覆盖同 owner 的类型漂移。如果本批 stop 合同涵盖这一管理员变更，需要让已有 scope reader 同时确认当前账户仍是 active simulated（或增加等价 typed 观察）；当前四处代码没有提供该观察。若本批只承诺处理 owner drift，则将此项作为后续有界边界，不阻断已审查的两个 owner P2。

除上述条件性同 owner 类型漂移外，未发现本次 owner-race 范围内的其他 P1/P2。静态审查不能证明 PostgreSQL 并发运行结果；native transfer candidate 已由 Root 接纳，仍以其后续真实 PostgreSQL 执行为准。
