# ASH03 owner-close 未知可卖量契约验证

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

日期：2026-10-19。范围仅为两条既有 owner-close 集成测试的契约对齐与本地验证记录。

历史五模块回归记录为 90 passed、2 failed；两个失败是旧测试把可卖量未知的持仓仍期待成功平仓。相同的 `SELLABLE_BALANCE_UNKNOWN` 结果也在纯基线 `ed032a79bb015e1ddf1619f8b33cb77bc416e1d6` 上复现。详见主计划 §19.86 与[竞态修复说明](a-share-legacy-position-delete-race-2026-10-19.md)。

两个测试都先由 owner 对 `/api/account/positions/` 发起 GET，以该读取路径触发 legacy adoption；随后核对新映射和统一持仓的经济数量、成本及未知可卖标志。测试在 close POST 前取得快照，覆盖旧持仓、source/target 映射、模拟账户、统一持仓、旧交易及模拟交易；POST 因 `available_quantity_known=False` 返回 HTTP 422 / `SELLABLE_BALANCE_UNKNOWN` 后，逐表快照保持不变。已知可卖量的完整/部分平仓成功控制位于 `tests/integration/account/test_ledger_unification_acceptance.py`，仍按原契约执行，不作放宽。

Root 的 314 固定源码快照运行了相关两个完整模块及两个已知余额控制：**45 passed，0 failed，0 errors，0 skipped**。这些是与旧五模块 90+2 不同的测试范围，不能相加成唯一节点数。314 输入记录称生产文件与上一已验证候选一致，且相邻测试逻辑未改；本批只完成这两条测试契约，不是生产行为修复，也不关闭整个 ASH03（registry 仍为 active），不代表外部券商余额核对、Owner M2/M3、RC/S6 或生产验收。

原始命令回执、JUnit、日志、输入摘要和独立静态评审见[证据索引](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/a-share-usability/ash03-owner-close-contract-2026-10-19/evidence.json")。归档只保存 314 的原始日志/XML/JSON 与评审原件，不复制生产源码。
