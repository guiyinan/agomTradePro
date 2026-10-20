# ASH-03 G2B3 原子成交与取消写入（2026-10-20）

G2B3把 fill 写入、hold 消耗、Trade/Position/账户更新和 Fee V2 累计差额置于同一事务，并在取消时先校验完整回执链、只释放未成交余量。SQLite 存储使用公共精度合同的整数单位守卫；PostgreSQL 保留原 NUMERIC 域范围，金融值未被取整改写。

最终同一六文件候选通过 SQLite 85 项和 PostgreSQL 88 项，均为 0 失败、错误或跳过。两组选取都包含 48 项未变的 G1 仓储回归，因此不将 85 与 88 相加。四个生产文件的 pytest-cov 分支模式综合覆盖均在 70.48%–85.67%。4 个生产文件增量 mypy、默认债务、格式/lint 和 7 项官方生成投影检查均通过；生成并纳入本候选的有效投影只有 `governance/module_map.json` 与 `governance/test_tier_inventory.json`，数据字典保持不变。

该结果仅覆盖已有 Position 的 fill 与部分/末笔消费、Fee V2 累计结算及完整取消链。首笔 BUY 尚无 Position 创建路径；未知当前估值阻断；默认 reader 仍为 `None`，没有激活日历/来源组合；V4 pending 释放、读路径邻接和重启恢复仍未完成。ASH-03 原第 2–7 组仍未关闭，也不构成正式 CI、生产迁移或部署资格。

精确候选、分阶段收据、保留失败与两轮夹具修正见[JSON验收索引](a-share-ash03-g2b-writer-2026-10-20.json)。原件仅本机归档：[originals.zip](../../artifacts/ash03-g2b-writer-2026-10-20/originals.zip)，SHA-256 `c9d73ebc69ddf5535fdb218973c161c0e98936ce6f1023338e0b98645c1be586`；归档清单逐项固定原始字节。
