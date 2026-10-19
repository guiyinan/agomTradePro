# Publication read deadline — 2026-10-19

`consistent_publication_read()` accepts an optional absolute monotonic lock
deadline. Each PostgreSQL table-lock attempt keeps the stricter caller timeout,
the existing five-second ceiling and the remaining shared budget. Exhausted or
sub-millisecond budgets fail closed; savepoint rollback restores the original
timeout and leaves the parent transaction usable. Existing callers retain their
previous behavior. This batch provides the deadline port; the multi-dataset
valuation caller belongs to the subsequent independent batch.

The adopted source and tests match the bound private candidate byte for byte.
The 29 snapshot unit cases passed as part of the 128-case combined regression.
Four real PostgreSQL component cases passed on a newly initialized, dedicated
loopback cluster, including the new 150 ms deadline, stricter caller timeout,
read-only read-committed rejection and repeatable-read reuse. The cluster stopped
successfully; its postmaster PID file is absent. A-share's database was not used.
Private candidate formatting and nine-file incremental/full production mypy
checks passed with zero regression, legacy or debt errors. The final combined
shared-source checks and same-candidate release gates remain separate requirements.

The original fake-PG-only checks, failed fixture attempts and earlier source
identities are retained. Actual source bytes, commands, JUnit and logs for the
128-case regression and four PostgreSQL cases are archived locally at
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/typed-combined128-and-native-pg4/`.
Its `index.json` SHA-256 is
`384c9b324767d02ae0a0923c11db9e70f2558627135064a0b05c36a3e7c7a785`.
This archive has not been uploaded. No deployment, production migration, RC/S6
qualification or production-data authority is claimed.
