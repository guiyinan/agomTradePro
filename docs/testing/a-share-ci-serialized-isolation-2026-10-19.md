# Fast 迁移测试的序列化隔离修复

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

`ed032a79b` 的常规 Fast 在 Linux Python 3.11/3.13 均出现 169 passed / 72 errors。最早错误是在 AI capability 迁移测试 setup 恢复序列化基线时重复写入 `django_content_type`。Root 的固定三节点 RED 也复现为 2 passed / 1 setup error，发生于迁移测试主体之前。

本批只调整 `tests/critical/test_agent_and_recovery_safety.py`：为既有 transaction 测试声明 `serialized_rollback=True`，并导入已有 `preserve_account_authority_generation` 夹具保护 flush 生命周期。测试主体、签名和断言不变，没有手工重置权限时钟或关闭触发器；生产文件未改变。

本地完整 Fast 241 项仍在后台运行。本次捕获的有时间戳 partial 日志中，原三节点按相同顺序已实际 PASS；此证据足以验证原交错反例，但不能写成 241 项通过。样式检查通过，独立静态审查同意该单文件修复独立提交并以实际 Linux 3.11/3.13 CI 验收。其余本地节点、S6、完整 RC 和生产资格继续分别记录，不等待它们才允许本测试修复进入开发分支。

序列化 setup 会恢复测试数据库初始基线；现有 flush 夹具的检查不证明跨基线恢复的 authority generation 单调性。这是测试隔离边界，本批没有修改生产单调性合同。原件、部分日志身份、三个通过行及源码哈希见[证据索引](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/a-share-usability/ci-serialized-isolation-2026-10-19/evidence.json")。
