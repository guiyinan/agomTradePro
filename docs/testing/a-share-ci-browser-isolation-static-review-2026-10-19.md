# CI 批次 2 静态复核

范围：对照 `.tmp/c99/shared-preimages-41/` 中的三份共享 preimage，复核 CI workflow、authority-generation 清理 helper、Fee Admin browser journey，以及新增的 browser setup 单测。当前 helper 后像 SHA-256：`510a237c95714ed7a13e8dd20a612b39bdf4ba80862e890aedb17ca1ec3cbed2`；workflow：`50b6e073e8a49b0fccaa05f9420419bab8cf2e8c8f1c4157280b581d766fdb46`；Fee Admin journey：`b09b735525c74537af896c35aac9060e5a662a98619dd09b873ca6c6d8f985f9`；新 guard 单测：`8d27ce8f0d90e28bcfd4659550dc525fd35705d96814e50b5320f0fc10704411`。

**结论：当前后像没有发现未解决的 P1/P2。** 首轮复核发现 helper 只认 SQLite 内存库，但 CI 的 `development_sqlite` 使用文件型测试库。Root 随后把护栏收敛为仅接受 Django 当前测试库、显式 `TEST.NAME` 和 `_get_test_db_name()` 一致，文件路径解析后必须位于系统临时目录下的 `agomtradepro-test-databases`，文件名必须是当前 PID 对应的 `test_db_<pid>.sqlite3`，并拒绝仓库源数据库。现有 CI 设置满足这组条件；内存 SQLite 仍被保留。该修正覆盖了发现的阻断，没有增加测试数据或放宽到任意文件库。

Workflow 将 `python -m playwright install chromium` 移到 `fast-feedback` job 的首个显式 pytest 步骤之前，且安装步骤没有 `if` 条件。原先 TUI 变更条件和目标 pytest 之后的位置已移除。新增 `tests/unit/ci/test_fast_feedback_browser_setup.py` 检查该 job 内显式 pytest 命令的顺序与无条件安装。它刻意只验证受影响的 `fast-feedback` job；其他 job 的 pytest 不承载这批组件浏览器测试。Node/TUI 运行时仍单独按 TUI 变更选择，不影响 Python Playwright。

清理 helper 只从 Django 生成的 flush 表列表中移除唯一的 `account_authority_generation` 表，并检查生成 SQL 不再包含它；其他业务表仍交给原始 flush 实现，未关闭触发器、重建单例或伪造 generation。flush 前后均从实际连接查询单例行，要求恰有一行且 generation 为有效非负整数，并验证清理后 `after >= before`。PostgreSQL 前后都调用 Native guard，核对活动连接名、明确配置的 `TEST.NAME` 和 `current_database()`；SQLite 则检查活动库等于 Django 测试库目标，并限制到内存库或上述明确的临时测试文件。

Fixture 是模块级 autouse fixture，且 Fee Admin browser journey 显式导入它；没有变为全局 fixture。两个 backend 的 `sql_flush` 和 `execute_sql_flush` 类方法都在 `finally` 恢复。Fee journey 的 `transaction=True`、`live_server` 和原有浏览器/账本断言保持原样；增量只启用该模块清理保护。

本复核为静态检查；按任务约束未运行 pytest、数据库操作、项目导入或 Git 命令。Root 的 SQLite 与 PostgreSQL 实跑仍是运行时证据；本 memo 不把静态结论表述为测试通过。
