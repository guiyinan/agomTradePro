# ASH-03 G2B3 测试隔离修正（2026-10-20）

0036 迁移反向保护测试降级后未恢复最新结构，导致后续 SQLite 部分成交撤单误用旧约束。现以 `finally` 中的新 `MigrationExecutor` 恢复原迁移叶节点。两个重置用例先取消空回执链，再插入专门验证保留性的合成历史，避免准备阶段被严格撤单校验拦截。生产成交、撤单、重置保护及财务约束均未改。

旧源码按真实顺序运行七项，得到 4 通过、3 失败，三项均为 `simord_state_conservation_ck`。最终同一三文件候选在 SQLite 的 75 项与 PostgreSQL 的 11 项通过，均无失败、错误或跳过；两组选取有重合，不相加。重置 API 仍验证真实 owner 请求的 422、JSON Content-Type、阻断代码和账本不变。Black/isort/Ruff 与测试分层清单检查通过，迁移修复经独立静态复核。

保留首轮 SQLite 清理阶段失败：75 项通过后出现两个临时数据库目录安全断言错误。修正 QA 配置为项目标准 PID 临时目录后重跑，没有修改该安全断言。具体源码、命令、实际收据和失败记录见[JSON 索引](a-share-ash03-g2b-ci-fixtures-2026-10-20.json)。

原件仅本机归档：[originals.zip](../../artifacts/ash03-g2b-ci-fixtures-2026-10-20/originals.zip)，SHA-256 `3d03b9c8a8a860266aad3d6b8b6fb25547fbc2b6b82b15e3cada4fcc6d62d017`。当前开发基线是 `bf3e1d33f1a7c042c0be18cb9904f4e31fd4ed7c`；此批本地通过不替代原冻结 bf3 的 RC 失败，也不表示新提交 CI、生产资格或 ASH-03 整单元通过。
