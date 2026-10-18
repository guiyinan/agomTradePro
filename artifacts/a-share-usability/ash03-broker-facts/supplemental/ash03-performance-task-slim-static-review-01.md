# Static review: ASH03 performance task slim candidate 81

Candidate manifest: `.tmp/ash03-performance-task-slim-candidate-81/manifest.json` (SHA-256 `e6536308daa81c3333e0c10a9038255c729bf157210b85ac529a4f888d9d6242`). Candidate patch SHA-256: `f235afa42a667f417b7868a9958e76b9a729ed8f6956ae95e4cb32745061a0b5`.

The frozen two-file patch moves the existing performance summary construction and email formatting into typed helpers in `task_notifications.py`. `tasks.py` still iterates accounts in the same order, collects per-account exceptions in the existing error list, builds the same summary fields, and sends using the same notification service, recipients, counters, and outcome path. The changed hunks do not alter retry, send-result, or task-result handling. The candidate reduces `tasks.py` from 1267 to 1163 nonempty lines.

The helper preserves the existing knowledge gates: account total value becomes null when cash or any current position valuation is unknown; return, drawdown, and Sharpe remain null unless current values and closed-trade costs are known; win rate remains independent of current cash/valuation and becomes null when trade-cost evidence is incomplete. The existing Chinese unknown-value messages and percentage formatting are retained. `PerformanceSummary` and `PerformanceSummaryEntry` are `TypedDict`s with typed helper signatures. The use-case result type is imported only under `TYPE_CHECKING`, so this refactor adds no runtime dependency cycle.

The `send_mail` function is relocated with the same body and remains imported by `tasks.py` under the same patch seam. Subject and body now share one `date.today()` value instead of sampling the date separately; this avoids a midnight mismatch and does not alter task outcome or delivery semantics. I found no P1/P2 blocker in the reviewed scope. Root should retain the existing real task-contract test for admission; this review did not execute it.

Static-only boundary: candidate preimages are Source80 and the manifest records exact file hashes. No tests/QA, project imports, database access, or Git commands were run for this review.
