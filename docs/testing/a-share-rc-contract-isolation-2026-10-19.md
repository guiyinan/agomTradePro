# A-share RC contract and migration isolation follow-up

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

This test-only batch is based on `2a9b1f6e656c1b1e6c261fd41288b1a73069315d`. All five ordinary push workflows succeeded, while RC `39189473887` failed. Its actual PostgreSQL critical-reliability job passed 18 tests and its dependency installation succeeded; these do not make the full RC successful.

The registered current-data run failed two manual BUY/SELL assertions because their exact response field set omitted seven existing financial knowledge fields. The test now retains exact equality, verifies known fees and BUY basis, and keeps the fixture SELL's unknown basis and null PnL. Root first reproduced both failures in a pure committed-source export, then the full module passed 11 tests on native PostgreSQL. No owner/account, idempotency, UoW or ledger assertion was weakened.

The migration job had eight passing calls and six flush teardown errors: multi-table TRUNCATE removed the migration-owned authority singleton while its source triggers still required it. Migration conftest now imports the existing module-autouse preservation fixture. This keeps source triggers active, flushes business rows normally, checks the existing singleton and nondecreasing generation, and never creates or repairs the clock. The five original RC migration modules were rerun with this fixture; the exact result and command are in the retained JUnit/receipt.

Only two test files change. Production source, migrations, runtime configuration and admission rules stay at committed 2a9 in the isolated verification; uncommitted ASH04 is excluded. Black/isort/Ruff and an independent Luna max static review passed. These are Windows/Python3.13 local results; the new commit's Linux CI must be recorded separately.

RC's other failures remain open: Classic dashboard/redoc journeys, asynchronous ORM fixture setup, and 4,932 unclassified full-history secret findings. This batch grants no RC/S6, Owner or deployment qualification. Raw evidence and original-failure provenance are indexed at [evidence.json](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/a-share-usability/rc-contract-isolation-2026-10-19/evidence.json").

The RC Fast Feedback comparison used base `96354c9ceba0ca46d49f667554a3498ffb286d20`. Its incremental size result does not establish that cumulative production-file growth from main has been resolved; the release freeze still needs its actual main-based check.
