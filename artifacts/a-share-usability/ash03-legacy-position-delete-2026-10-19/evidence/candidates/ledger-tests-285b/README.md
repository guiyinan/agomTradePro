# ASH03 closed-source race tests — 285b

Status: private TEST ONLY candidate; not executed. This is a revised companion packet. The original 285 packet remains frozen and unchanged. It contains one appended integration-test candidate, no production postimage, and no shared-tree edits.

The race test hooks `PortfolioApiRepository.legacy_sync_transaction`, the existing parent-context entry used by the adoption path. By the time the hook runs, caller A has loaded the closed legacy source and reached the parent-context entry, but has not entered the original context. The one-shot hook calls the real `portfolio_api_services.delete_position()` as caller B, verifies B removed the unified target, mapping, and source, and snapshots the complete business state. It then forwards every keyword unchanged to the captured original transaction method. This keeps the hook compatible with the current signature and a signature that adds an optional keyword such as `for_update`; the test does not require the correct implementation to read a mapping before the lock.

Caller A then continues through the real API. The assertions require a stable 404/not-found or 409/reconciliation-conflict response, no recreated source, target, or map, and an unchanged post-delete portfolio/ledger snapshot. This is a deterministic same-test-connection interleaving, not a two-connection lock-race proof.

The positive control verifies that an existing valid mapping returns its unified target and leaves its quantity and full business snapshot unchanged. The rollback case injects a failure after the real mapping deletion and requires the source, target, map, and full snapshot to be restored. The injected exception description refers to mapping deletion, which is the actual fault point.

The fixture gives the target a primary key different from the legacy source ID so the API enters the legacy-source path. The source remains marked closed with its loaded positive quantity to represent A's cached source snapshot. No test is run as part of this packet; Root owns execution and QA.
