# ASH03 closed-source deletion/adoption candidate — independent static review

## Decision

The 286 candidate closes the bounded stale-read resurrection path on the code path reviewed. I found no P1/P2 that blocks that specific fix under a valid one-to-one legacy-source mapping. The existing-map branch remains an idempotent lookup and does not rewrite unified position economics.

One conditional data-integrity residual remains outside that bounded race fix: deletion does not reject a pre-existing ambiguous reverse position map. Record it as a later integrity case, not as a reason to widen this change or to claim the present race is still open.

## Frozen inputs and hashes

Production packet `.tmp/ash03-closed-source-production-286/`:

- `manifest.json`: `c9a29d0e46a47f9d5312b7790a584d38ecaa789c0cb8c4f5f2b71a19962756b0`
- `patch.diff`: `f444d002639fc23a9b43bf1d7bd35c88dbb9523adde128f5bd186d34fad732f0`
- `portfolio_api_contracts.py` candidate: `9a991844c8a69f88de1be4bb07133d3b05edcbffbdc9a0731a659dcc95cdd9b4`
- `portfolio_api_services.py` candidate: `b8c4460f0cf97aa09ecc83738cdbcf4dc7d98d710146177bad5a6d92d4ddc40c`
- `account_portfolio_repository.py` candidate: `aded11ae6004a6869cfd8539c1c407109be670e37040d4c24e8caf78ffcd6fc3`

At review time all three shared source files still matched the 286 manifest preimages. Test packet `.tmp/ash03-closed-source-race-tests-285b/` has manifest SHA `a550931b07e07b9dc1ca662ca2101ef59e0fb4c880efd563408fb377a1174ad5`, patch SHA `e684be668d9b54dc4de37264479c8219b1ed3027d79f18fbbe432549685e9c44`, and test postimage SHA `59adc1c806447e84980b39f6c869884505712e0d449f6cc20dae4a56e4105467`. The source mutability memo `.tmp/ash03-legacy-source-mutability-283.md` is SHA `52b7e3900c5ea0e791721be3e9ae41d38d0a730f62e6d4a3658f75004ed56aaa`.

## Review findings

The parent/source lock sequence is consistent with the agreed lock order. `legacy_sync_transaction` locks the owned Portfolio first. It makes an initial, non-locking portfolio-map read only to locate the account; then locks the real SimulatedAccount, locks and revalidates the portfolio mapping and reverse account mapping, and locks the exact legacy Position by source ID and portfolio. The Account application then locks and checks that source's position map. The existing adoption repository rechecks account ownership, source-map uniqueness, target account/asset, and the unique reverse position map before returning an existing target. It does not copy the closed legacy object's quantity, cost, price, or dates over the mapped target.

For a closed-source lookup, `_resolve_position_context` now enters that parent transaction and uses the locked Position returned by the repository. A deleted source returns not-found; a changed portfolio/owner/closed status or invalid map conflicts before the adoption call. This closes the 283 interleave where a caller could use a pre-delete legacy object after another caller had removed the source, target, and map.

For deletion, the service first resolves the candidate target/source IDs, then enters the same parent/account transaction. Inside it, the service checks the current target and revalidates the exact locked source and source-to-target map before making any delete. Unified target, target mappings, and legacy source are deleted inside the repository's `transaction.atomic()` scope. The 285b rollback test injects an exception after the real map deletion and compares the full business snapshot; static control flow confirms the exception exits the outer atomic context and rolls back the earlier target delete as well.

The 285b race test performs a deterministic same-test-connection interleave: caller A has read the closed source, the hook runs caller B's real deletion before A enters the original parent context, and A then resumes. It is useful regression coverage for stale-object resurrection, but its README correctly does not claim a two-connection lock-race proof. The positive control keeps the mapped target and full snapshot unchanged.

The interface remains compatible at the application boundary: `legacy_sync_transaction` adds an optional `source_position_id`; the existing portfolio synchronization call omits it and ignores the yielded value. `get_position_mapping_for_source` adds an optional `for_update=False`; ordinary reads retain the old call shape. No endpoint, serializer, model, migration, or schema changes are in this candidate. The Account Application uses its typed repository Protocol; ORM work stays in the Simulated Trading infrastructure repository. No new app-level cycle or Interface-to-Infrastructure import is introduced.

## Conditional reverse-map residual

The map table enforces uniqueness by source `(source_app, source_table, source_id)` but does not enforce uniqueness by `(target_table, target_id)`. `get_legacy_projection_for_unified_position` selects one matching reverse source map with `order_by("-id").first()`. The delete path validates that selected source map, then calls `delete_position_mapping_for_target`, which deletes every matching Account Position map to the target, while deleting only the selected legacy source row.

If damaged or historical data already has two legacy sources mapped to one unified target, deletion can therefore leave the unselected legacy source without its map. This is a conditional, pre-existing ambiguous-map state; adoption already rejects a non-unique reverse map. The smallest later integrity guard is to lock all reverse source maps for the target and require exactly one, matching the selected source map, before the first delete. This is not evidence that the valid one-to-one delete/adoption race remains open and should not expand the current fix.

## Evidence boundary

Root reported that the 285b tests produced two real PostgreSQL RED failures and one passing positive control against the pre-fix source. That is external run evidence, not a test run by this review. Root also reported the private 286 integration had reached formatting/type-check preparation; no candidate GREEN or final QA result was available to this static review. I did not run project imports, tests, QA, database access, or Git commands, and made no shared-source changes.
