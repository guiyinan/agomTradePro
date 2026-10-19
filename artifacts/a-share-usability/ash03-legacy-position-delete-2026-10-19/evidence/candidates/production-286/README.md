# ASH03 closed legacy source race candidate (286)

This is a private candidate only. It does not modify shared source and has not been run through project imports, tests, QA, a database, or Git.

## Bounded change

The existing transaction already locks the owned Portfolio, validates its portfolio-to-real-account mapping, and locks the SimulatedAccount in that order. The candidate extends that same transaction with an optional exact legacy source id and re-reads that Position under `select_for_update(of=("self",))`, filtered to the locked portfolio. The closed-source fallback now consumes only this locked row, rechecks owner/portfolio/closed status, and locks/revalidates the source map before calling the existing adoption service. A valid map still follows the existing adoption repository's idempotent branch and returns its mapped unified target without copying legacy economics.

`delete_position` now uses the same portfolio/account transaction. It re-reads the target and, when a legacy source mapping exists, locks and verifies the exact source and map before deleting the unified target, map rows, and legacy source. An exception rolls all three deletes back together. This closes the stale-snapshot interleave where deletion could previously remove target/map/source outside one common transaction while a waiting closed-source fallback later recreated a target from its earlier read.

The lock order stays Portfolio -> portfolio/account mapping -> SimulatedAccount -> legacy Position -> legacy source mapping -> unified position/adoption checks. The optional source row is locked only after the existing parent/account validation. No model, migration, new state, or ledger was added.

## Review seams for Root

Before admission, exercise native PostgreSQL cases through the real Account application/repository boundary:

1. Hold the parent/account transaction in deletion, remove target/map/source, then let a request that captured the closed source before deletion proceed. It must return not-found/conflict and create no unified position or map.
2. Between the initial closed-source read and lock acquisition, delete the source, move it to another portfolio, reopen it, or remove/retarget its source map. The locked re-read must fail before ledger writes.
3. Keep a valid closed source and valid map. The existing target id and its economic fields must remain unchanged (the adoption path remains idempotent).
4. Force a failure after the first delete and verify the unified target, all mapping rows, and legacy source remain because the transaction rolls back.

The package does not claim to serialize unrelated legacy writers that do not use `legacy_sync_transaction` (for example other close/admin mutation paths); Root should decide whether those are part of the present acceptance contract. It also does not change the mapping's database schema or add FK semantics.

## Files

`candidate_sources/` contains full proposed postimages; `preimages/` contains the exact captured shared before-images; `patch.diff` is their unified diff; `manifest.json` records SHA-256 and byte counts. No tests were added or run in this production candidate.
