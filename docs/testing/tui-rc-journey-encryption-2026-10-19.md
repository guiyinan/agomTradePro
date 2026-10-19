# Disposable journey encryption configuration — 2026-10-19

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

The existing personal AI provider browser lifecycle failed because the isolated journey environment did not configure `AGOMTRADEPRO_ENCRYPTION_KEY`. Production encryption checks are preserved. The CI journey shell now generates one ephemeral Fernet key and exports it to its existing server/pytest child processes. It does not read production keys, change secret interfaces, log the key, or persist it through `GITHUB_ENV` or a key file.

The unchanged existing provider create/detail/update/delete case passed: **1 passed, 0 failed, 0 errors, 0 skipped** (18.28 seconds in pytest). This targeted reproduction used the ed032a plus seven-overlay private source recorded by phase2, an independent disposable SQLite backup and a separate loopback server; it is not a full M5 or release pass. The server was stopped afterward. Bash syntax and YAML parsing passed; removing the three added shell lines restores the entire previous workflow structure, including all required gates, no-skip policy, markers and budgets. Independent review approved the change.

Raw evidence hashes are in [the manifest](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/tui-rc/journey-encryption-2026-10-19/evidence-manifest.json"). This batch changes only journey environment preparation. Remaining M5 failures, signal fixture, full same-candidate RC/S6, and deployment confirmation remain separate. No VPS deployment, observation T0 or TUI-02 closure occurred.
