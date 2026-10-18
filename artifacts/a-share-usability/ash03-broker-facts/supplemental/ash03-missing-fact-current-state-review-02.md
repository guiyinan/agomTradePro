# ASH03 current-state boundary v3 — supplemental static review

Scope is limited to Root's Source91 counter fix and `.tmp/ash03-fact-unavailable-boundary-v3/` TEST ONLY candidate. No tests, imports, DB, QA, or Git were run for this review.

## Source91 check

The current `apps/account/application/manual_trade_sync.py` SHA-256 is `1b9642db3c307ff6749bb5da02c568fe64bfd9cbe86ef4270c8fa641fd6db3da`, matching v3's captured shared-context hash. In the result-building flow, all four counters now come only from `_fact_state_counts(writes=..., current_fact_states=...)`; the subsequent code appends errors/conflict details and returns. It no longer falls back to counting raw `reconciliation.facts`. The remaining `reconciliation.facts` reference at line 898 is the intended initial mapping, filtered to IDs in `records_by_id`. The P2 raw-result fallback is therefore statically removed.

## v3 packet check

- Manifest SHA-256: `021dd26784a86354fbf939663b41119715a54f3d4df0f4c7818cd618feb7e013`.
- Patch SHA-256: `f6752dc4dbbcba7c8809839976dda2e98ae8ce03dad044674a10c39b093762f6`.
- Test candidate SHA-256: `20084f288a115053f979e5f425e1316e19b6ad116be4a0c7a865a7ed9b8f9132` (16,693 bytes); its preimage hash matches the v2 base recorded in the manifest.
- This is test-only and adds no production path.

Coverage matches the requested finite boundary: (1) an actual ORM deletion plus an injected projected result for an unrequested transaction ID checks that no stale raw result can restore a count; (2) a parameterized fresh-read exception and wrong transaction identity both require unavailable status rather than fallback to the original write receipt; (3) the TUI sanitizer helper test checks the human status/recovery guidance, row number, and absence of stable machine code/internal error detail. The original real-deletion tests remain in the candidate.

The TUI case tests the existing sanitizer directly rather than exercising an HTTP/browser route, which is appropriate to the requested sanitizer boundary. The stale-result test isolates an unrequested ID; same-ID repository result freshness still depends on the separately repaired repository return path. The v3 README accurately says no runtime RED is claimed after Source91 and records that only AST parsing was performed by its author. Root remains responsible for runtime QA/admission.

No blocking static issue found in this bounded review.
