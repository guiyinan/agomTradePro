# ASH-03 费用入账范围校验（2026-10-23）

本批在普通模拟结算计算 Fee V2 后、资金和持仓写入前，按成交模型实际四个 DecimalField 的验证器检查手续费、过户费、印花税和滑点。越界返回 `SIMULATED_TRADE_FEE_STORAGE_INVALID`；同一事务内已发生的到期结算释放也回滚。费用公式、费率、字段精度、来源和所有者规则均保持原契约。

| 验证 | 实际结果 |
| --- | --- |
| 失败先行 | 旧实现的过户费越界触发 PostgreSQL numeric overflow；另一次佣金反例被已有均价上限以通用错误阻断，不能描述为接受交易。两个失败原件均保留 |
| PostgreSQL 16.15 | 五个完整模块 311/311 passed，0 skipped，475.23 秒；含七个新增费用用例和五个行锁并发场景 |
| SQLite | 两个完整组件模块 74 passed / 5 skipped，294.83 秒；五项为已有 PostgreSQL 行锁专用场景，新增七项均通过 |
| 类型和静态 | 两个生产文件增量 mypy 与默认全库债务均 0；三候选 AST/Black/isort/Ruff 通过。UoW 文件为 1000 条非空行，新校验模块为 47 条，无扩大门槛 |
| 架构和治理 | 完整与增量架构/audit、App 循环和治理一致性均通过；增量实际扫描两个生产文件，零违规 |
| 官方投影 | 隔离生成并检查 module_map 与 test_tier 两项输出，分别仅增加一个 Infrastructure 文件和一个组件测试；外来测试文件未进入投影 |
| 独立复核 | PostgreSQL/SQLite 收集与 JUnit 身份、测试模块来源、13 项源输入及三个 HTTP 边界逐项核对，零未模拟 HTTP 尝试；投影用 99 项 overlay，恢复 10,403 个基线源文件，额外 Python、恢复失败和遗留锁为零 |

七个新增用例覆盖四费用分量溢出、结算释放随失败回滚并重复尝试、最大可存费用 `99999999.99` 的精确持久化与同键重放，以及独立均价上限。使用合成费率与账户，经真实 UseCase/Repository 和正常迁移的独立测试数据库执行，不代表生产费率或账户资格。PG fixture 在首次 schema 写入前复用现有 Native 测试库身份防护。测试期间费用候选与十项依赖前后 hash 一致；独立 TUI manifest/说明提交未改变这些输入。

本机环境为 Python 3.13.5、Django 5.2.12、pytest 8.3.4；不替代新 SHA 的 Linux/Python 3.11 CI。源候选父为 `ff06b7045530513eaa399e63112f0d29e4678328`，整合父为 `7eefdcee2e2f8005d411cd5472cab31766426f7a`；三路径候选 manifest SHA-256：`bf965ffa3fef614aa36251d81d7f14b3846fa7342b93399e5b99aca36dac9313`。普通测试只读取共享树的精确候选，投影独立复用既有隔离 WORK；恢复后由 Root 再次检查全基线和外来 11 项文件/ITA 状态。

同一事项未压缩原件保留于本机 `artifacts/ash03-fee-storage-2026-10-23/`；[INDEX.json](../../artifacts/ash03-fee-storage-2026-10-23/INDEX.json) SHA-256：`08f6b35938a12fbb774b85b6e63a61a65d63d53b743c41876514b1d901fd574e`。索引逐项记录候选、两次失败、最终运行/JUnit/HTTP、类型、架构、投影及恢复原件的位置和哈希；不含缓存、数据库、凭据或完整工作副本，未声明远端已有原件。

本批没有模型或迁移变更、生产配置激活、部署、实盘下单或生产账本写入。不关闭整个 ASH-03、第4组费用冲正与差额、M1 账户613实际验收、M2/M3 或完整 Goal；`acceptance_evidence` 保持空。新提交 CI、同 SHA RC/S6 与生产验收另行完成。
