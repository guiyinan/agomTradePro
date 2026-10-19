# M5 local ORM fixture lifecycle — 2026-10-19

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

This batch fixes local browser fixture setup: each complete ORM operation enters the pytest database blocker in its worker thread and closes that thread's connections in `finally`. User-role, ownership, remote-target and write guards remain active. No application behavior or release gate is relaxed.

## Evidence and limits

The isolated preview was exported from `ed032a79bb015e1ddf1619f8b33cb77bc416e1d6` plus the five overlays recorded in [applied.json](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/tui-rc/m5-fixture-lifecycle-2026-10-19/applied.json"). This commit includes only the M5 fixture source; the four dashboard/navigation overlays are separate batches. Preview results therefore do not qualify this commit as a complete release candidate.

Run: 13 selected browser cases, **7 passed, 6 failed, 0 setup errors, 0 skipped; 2 external AI cases deselected**. All 13 fixture setups executed, including detail data seeding. The former 13 setup errors did not recur. Black, isort and Ruff passed for the M5 file; independent static review is preserved. The full M5 suite and RC remain failing.

The six remaining body failures are preserved without rewriting in the JUnit, pytest log and extracted failure report. They cover direct/parameterized read completion timeouts, personal provider creation (server trace shows missing disposable-environment encryption configuration), two successful-write status wording assertions, and a detail-read settlement assertion. Calendar composition errors are also present in server logs but are not proven to cause these six failures. Follow-up must capture actual response and terminal state before changing timeout or success assertions.

Raw files and their SHA-256 values are in [the evidence manifest](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/tui-rc/m5-fixture-lifecycle-2026-10-19/manifest.json"). Artifact-local exact-file `-text` attributes preserve raw bytes; scanner rules are unchanged. Local execution used the existing Python 3.13 environment and disposable SQLite on loopback; Python 3.11/PostgreSQL RC and same-candidate S6 remain pending.

## Completion boundary

The fixture lifecycle repair is delivered independently. Dashboard fallback, navigation diagnostics, ReDoc rendering and signal fixture work require their own regression results and commits. Freeze one final candidate only after these and the remaining M5 failures are resolved, then run the complete RC and fresh S6 against that same SHA. No deployment, production migration, observation T0 or TUI-02 closure is authorized by this evidence.
