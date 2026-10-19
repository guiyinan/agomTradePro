# TUI RC：事务测试恢复顺序

`e9ea1c569103e1acb5b4ef32c65d563181ff2fd8` 的 Fast Feedback `39271458679` 在两个 Python 版本各出现九项 ContentType 唯一键错误。首个错误发生在 reconciliation 事务测试结束后的下一项序列化恢复阶段，测试主体尚未执行。

本批只为 `test_reconciliation_conflict_audit_transaction.py` 的现有 `transaction=True` 标记补充 `serialized_rollback=True`，使清理方式与后续恢复一致；不修改业务代码、断言、隔离 schema 或 authority singleton 保护。

使用正式 `core.settings.development_sqlite` 和每次独立的 `TEMP/agomtradepro-test-databases/test_db_<PID>.sqlite3`，从同一空白迁移库复制后验证：

- 修改前，两项 reconciliation 通过，后一项 forecast preflight 在准备阶段报同一唯一键错误：2 passed / 1 error。
- 修改后，同样三项全部通过：3 passed / 0 errors / 0 skipped；测试源码、迁移基线及源数据库文件元数据均未变。
- Black、isort、Ruff 通过。早期采用 Playwright 共享 NAME/TEST.NAME 的本地复验被 authority 保护拒绝，原件保留；没有放宽保护。

原始失败、两轮正式配置结果、JUnit、候选及源码哈希保存在本机 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/contenttypes-order-red-green/`，索引 SHA-256 为 `beb8311881e273fc530ce4a5ad08c9855eea4b2f72e5007f0c9b680a6c75fe9e`。归档仅本机可用。这一最小回归不代表完整 Fast Feedback、M5、RC 或 S6 已通过。
