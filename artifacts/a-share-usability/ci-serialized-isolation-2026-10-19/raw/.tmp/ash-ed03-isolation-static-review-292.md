# ED-03 migration isolation candidate: static review

## 结论

`.tmp/ash-ed03-isolation-tests-291/` 的改动针对日志中观察到的 interleaver，静态机制是吻合的：只给 `test_fake_agent_full_fill_and_event_replay_persist_once` 加上 `serialized_rollback=True`，并在该测试模块启用现有 `preserve_account_authority_generation` fixture。测试函数体、签名和既有断言均未改。候选没有跳过 AI capability migration 测试，没有删除 content-type 表，也没有预置或伪造 content-type 行。

Django 的 `TransactionTestCase` 在 serialized rollback 模式下于 setup 恢复序列化基线；teardown flush 时，在存在该基线的情况下抑制 `post_migrate`。这正对应 289 诊断里的污染链：普通 transaction-test teardown flush 后重新创建 content types，下一 migration test 再恢复同一批 content types 时唯一键冲突。候选继续正常 flush content types，只避免 teardown 的 `post_migrate` 再造一份。它也让 critical interleaver 与 `tests/migrations/conftest.py` 已使用的回滚模式一致。

导入 fixture 是必要的第二部分：其 module-autouse 生命周期在这一个文件期间挂接到当前数据库 backend operations；flush 时仅从表列表移除 `account_authority_generation`，其余表和触发器保持原有流程。它断言该表恰好出现一次、实际 singleton 已存在且只有一行，并记录 flush 前后的代次。它没有吞掉 flush 异常、禁用触发器或重建 singleton。目标模块只有该一项 `transaction=True` 用例；普通 `django_db` 测试不会走 TransactionTestCase 的全表 teardown。工作流命令未启用 xdist，因此该类级 operations patch 不会与另一测试进程并发。

这仍是静态结论，尚不能声称候选已修复：需要在两种 Python 版本上复跑下面记录的有序三节点和原 10-target 命令。目标用例切换到 serialized restore 后，其 setup 也会恢复数据库基线；有序复跑能验证整个前后生命周期，而不能只验证 teardown。

## 单例 fixture 的明确边界

`AccountAuthorityGenerationModel` 由 Account ORM owner registry 导入并参与迁移；迁移会建立 singleton，`generation` 字段可序列化。Django 序列化恢复会 raw-save 基线对象。因此在 serialized rollback setup 时，既有 singleton 的 `generation` 可能被恢复成测试数据库初始快照值；当前 fixture 只在后续 flush 的 `before`/`after` 间检查不下降，不能据此声称代次跨测试单调。该恢复属于测试隔离的基线重置，不影响测试体内的数据库 trigger；此候选也没有跨测试代次断言。若后续要验证跨测试单调性，需单独设计对序列化恢复的证据，不能把本 fixture 的 flush 观测当成该证明。

`serialized_rollback` 会抑制 teardown 的 `post_migrate`，所以候选不会单独覆盖这个 critical 用例 teardown 中的 `post_migrate` 行为。该用例验证 agent/交易恢复，不验证 post-migrate handler；此抑制与现有 migration 测试的清理语义相同。日志指出的关键错误仍在 AI migration 测试的 serialized setup；候选保留该 setup 和 migration 用例原断言，故它没有把该失败路径改成跳过或吞错。

## Fast Feedback 3.11/3.13 实际 pytest 范围

`.github/workflows/ci-fast-feedback.yml` 的矩阵包含 Python 3.11 与 3.13。两份 288 日志在本轮都执行同一组命令；先运行 8 个 S6 文件系统防护节点，各为 `8 passed, 1 warning`，然后以 `pytest -v --tb=short --durations=15` 运行 10 个选择目标，共收集 241 项。

预先运行的 8 个 node IDs：

1. `tests/unit/data_center/test_financial_scope_capacity_import.py::test_bundle_reader_rejects_symlinked_artifact`
2. `tests/unit/test_release_rehearsal_file_io.py::test_rejects_symlink_target`
3. `tests/unit/test_release_rehearsal_file_io.py::test_rejects_fifo_without_blocking_on_open`
4. `tests/unit/test_release_rehearsal_file_io.py::test_rejects_fifo_swapped_between_stat_and_open`
5. `tests/unit/test_build_release_rehearsal_manifest.py::test_builder_rejects_parent_traversal_and_symlink_artifacts`
6. `tests/unit/test_run_release_rehearsal.py::test_container_input_tree_rejects_nested_symlink`
7. `tests/unit/test_run_release_rehearsal.py::test_container_input_tree_recheck_rejects_mode_drift`
8. `tests/unit/test_run_release_rehearsal.py::test_container_stage_rejects_symlink`

日志中展开的 10 个主 suite 目标（两版本一致）：

1. `tests/api/test_manual_trade_current_reference.py`
2. `tests/critical/`
3. `tests/guardrails/test_alpha_workspace_consistency_guardrail.py`
4. `tests/guardrails/test_api_contract_minimal.py`
5. `tests/guardrails/test_architecture_boundaries.py`
6. `tests/guardrails/test_celery_task_contracts.py`
7. `tests/guardrails/test_logic_guardrails.py`
8. `tests/guardrails/test_no_501_on_primary_paths.py`
9. `tests/guardrails/test_security_hardening_guardrails.py`
10. `tests/migrations/`

原始 3.11 与 3.13 日志都报告 `169 passed, 1 warning, 72 errors`。第一项错误均为 `tests/migrations/test_ai_capability_semantic_governance_migration.py::test_semantic_governance_migration_backfills_collected_key` 在测试体执行前的 serialized restore 遇到 `django_content_type` 唯一键冲突；其后 migration setup errors 是该首个错误后的级联。两份日志显示的前三个相关项顺序一致：strategy allocation migration 通过、critical agent/recovery 用例通过、随后 AI capability migration setup 失败。

工作流另有 Python 3.11 的 `fast-tdd` job（business-configuration guard 自测和 `scripts/run_fast_tests.py`），它不是这两份 Python 3.11/3.13 matrix 日志记录的 10-target suite。TUI metadata 与 browser guard 是 `tui-changed == true` 时的条件步骤；两份 288 日志没有显示这些步骤运行。

## 证据指针与哈希

- 候选 README：`.tmp/ash-ed03-isolation-tests-291/README.md`，SHA-256 `22e62a9f66eb77d86069c51abb114821fc929010a1a7852e12be3372e2557be2`
- 候选 manifest：`.tmp/ash-ed03-isolation-tests-291/manifest.json`，SHA-256 `603cfa1a3cc9dab3b392ea3f8eb9ad34a2887598eb54d5f3517318cf9f98dd2b`
- 候选 patch：`.tmp/ash-ed03-isolation-tests-291/changes.patch`，SHA-256 `9fb44969da84c00875257a2e5e07bb4df3785b414e05811f293129c1878b7783`
- 完整候选 postimage：`candidate_sources/tests/critical/test_agent_and_recovery_safety.py`，SHA-256 `288974ec6f90cae1c7605af625941334f8eff0f8bdd5e0263c2e6e2255d136cd`
- 原始诊断：`.tmp/ash-ed03-migration-isolation-diagnosis-289.md`，SHA-256 `909cb36c3f162749fe0c6abce17cb2d0eb9bed61b8cfa46720601b4c92c55455`
- Python 3.13 日志：`.tmp/ash-ed03-ci-288/117875739284.log`，SHA-256 `c417719547c54543ec2b31648c9555dfeffcb5aa7f463aadb446eb5410201474`
- Python 3.11 日志：`.tmp/ash-ed03-ci-288/117875739359.log`，SHA-256 `34c6e0097c84c721f54d4ac8714f231904fe435bcf31967f21dde4cde54fa6f2`
- 当前 workflow：`.github/workflows/ci-fast-feedback.yml`，SHA-256 `50b6e073e8a49b0fccaa05f9420419bab8cf2e8c8f1c4157280b581d766fdb46`
- 现有 flush fixture：`tests/support/account_authority_generation_flush.py`，SHA-256 `510a237c95714ed7a13e8dd20a612b39bdf4ba80862e890aedb17ca1ec3cbed2`
- migration rollback fixture：`tests/migrations/conftest.py`，SHA-256 `43d5150e95e3d8aeaf5c90d404f8e62a828351ac853084fd9589c665d778d13b`

本 memo 仅基于静态读取；没有运行测试、QA、数据库、项目导入或 Git 命令。
