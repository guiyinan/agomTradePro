# ASH-03 G2B5：初始估值证明接入首笔 BUY（2026-10-21）

G2B5 将独立初始估值证明接入账户内尚无 `Position` 的首笔 BUY。账户锁内先确认现金和市场聚合已知且一致，再读取注入的 `InitialPositionMarkReader`。证明绑定 `security_id`、`asset_code`、`asset_type`、`market`、`board`，并校验价格、来源/发布/策略摘要、源时钟及显式 TTL；mark 与成交价、限价相互独立，未知的 `source_available_at` 保持未知。缺少 reader 或有效证明时 fail closed。

成交成本计入 Fee V2 增量费用，持仓市值与未实现盈亏使用独立 mark；回执封存初始估值证据，已有持仓成交继续使用 V1。测试包含真实 Position 插入约束失败后的 Trade、回执、账户与 hold 回滚，以及 PostgreSQL 同账户并发首笔 BUY：一条 Position、两笔成交/回执，顺序为 V2 后 V1。结算日历证明和 lag 决定 pending 状态及冻结的预计释放日；实际 V4 到期释放仍未接入。T+1 份额保持 pending。显式零 lag fixture 只验证策略驱动路径，不证明普通 A 股可 T+0。

基于 19 源候选的写入回归中，SQLite 98 项、PostgreSQL 102 项实际均为 0 失败、0 错误、0 跳过，计数含相同的 48 项 G1 回归且不相加。SQLite 首次复合收据因 coverage combine 报 `No data to combine` 而整体标失败；pytest 和 JUnit 已通过，之后 1174 对保存的数据执行 report-only 合并，没有重跑测试。分支模式逐文件覆盖率为 repository 80.31%、ledger storage 72.38%，均高于 60%。19 源格式/lint 和两生产文件增量 mypy 命令通过；同阶段 default-debt 检查超时，稍后的独立 default-debt 命令通过。超时和成功原件均保留于 JSON 索引。

1177 的 reader 测试夹具修正是测试专用变更，保留原有 15 个测试函数且未改生产代码；它不属于 98/102 项选择。该修正后的 row-reader/request-reader 选择随后在 SQLite、PostgreSQL 各运行 32 项，均 0 失败、0 错误、0 跳过。它是独立双库结果，不改写早先 98/102 项的输入身份。

本批 19 源及独立夹具修正已通过9项官方生成/检查命令，其中新鲜度合同覆盖90个surface；ORM未变，数据字典在核对8个生产输入及原产物后复用并通过官方检查。`InitialPositionMarkReader` 和成交 event reader 未接入默认组合根，因此本批不会自动启用市场数据源。V4 pending 释放、G2C 来源资格、邻接读取与重启恢复，以及 ASH-03 原第 2–7 组和 §7 退出条件仍开放；这里的本地证据不代表正式 CI、生产迁移、部署资格或整个 ASH-03 完成。

精确来源、收据、覆盖范围和未完成项见[验收索引](a-share-ash03-g2b-first-buy-writer-2026-10-21.json)。G2B4 原验收文件保持独立且未覆盖；本批仅提交到开发分支；新提交CI需另行取证。
