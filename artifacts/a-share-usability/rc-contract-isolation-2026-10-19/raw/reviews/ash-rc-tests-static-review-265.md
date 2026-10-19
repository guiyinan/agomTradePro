# RC test-candidate static review

Reviewed the two private test-only packets without running tests, project imports, QA, database access, or Git operations. Both candidate preimages match the current shared files recorded in their manifests.

## Trade knowledge response contract

`.tmp/ash03-rc-trade-knowledge-tests-252/` is internally consistent with the current manual-trade response path. The candidate keeps the exact response-key equality check and adds the seven knowledge keys already emitted by `apps/simulated_trading/interface/views.py` and declared by `TradeResponseSerializer`: fee-known/status, cost-basis-known/status, realized-PnL-known/status, and realized-PnL-percent-known. The serializer’s existing numeric PnL fields remain in the exact set.

The BUY expectations match the settlement repository: an executed BUY has known fees and known cost basis; realized PnL is not applicable and its nullable fields stay `None`. For the seeded SELL, `PositionModel.cost_basis_known` defaults to `None`; the UOW carries that value to the trade, classifies it as unknown, and the interface only exposes realized PnL when both fee and cost-basis knowledge are exactly `True`. The candidate therefore preserves the unknown state and masks PnL and percentage values. It retains the existing authenticated owner, idempotency, real-UOW, and ledger assertions; no assertion is weakened.

One README sentence is imprecise for this exact UOW path: it says a SELL “may retain numeric internal calculations,” while `execution_settlement_uow_repository.py` sets realized PnL to `None` when the position basis is not known. This does not affect the test or its contract; revise or qualify that explanatory sentence if the README is retained.

## Migration-test fixture scope

`.tmp/ash-rc-migration-fixture-259/` only imports the existing `preserve_account_authority_generation` fixture into `tests/migrations/conftest.py`. Pytest will discover the imported autouse fixture for that conftest subtree. Its module scope keeps the operations wrapper active across each test module’s function-scoped serialized rollback and teardown, then its `finally` restores both patched methods. The existing `_preserve_serialized_migration_baseline` fixture is unchanged.

The reused fixture excludes only `account_authority_generation` from the generated flush list, leaves ordinary flushes and source-table triggers active, checks the existing singleton row before and after each guarded flush, and requires a nondecreasing generation. It does not create or reseed the row. Its PostgreSQL test-database check and SQLite memory/file-path checks remain unchanged. Static inspection found no `available_apps` override or explicit account migration target under `tests/migrations`; migration tests that move app state use saved leaf targets and restoration in `finally`. The broader autouse scope is therefore compatible with the visible migration-test pattern. If a future test flushes while the singleton table is absent or uses a non-default alias, the helper fails closed rather than masking that state; that is a bounded suite-integration constraint, not a reason to relax its singleton assertions.

## Reviewed hashes

- Trade packet preimage: `0f44dffb68060eae6f63bfbb703d483ae5559b686fbcc468358c9a44f64ec6b8`
- Trade packet candidate: `307b606ccbe89ad87956a0e2e83d61e1ed387e822246113b9c2628cb42d82332`
- Trade packet patch: `5ea8a9d05a7dc9c3b61ca301978df8265a021ca3d474b80b57bdd038bffbf917`
- Migration-conftest preimage: `4c6dad4c85f55c4bc29d56601167d2469240fac2e0dab795aac8e0c5e3da2ff`
- Migration-conftest candidate: `43d5150e95e3d8aeaf5c90d404f8e62a828351ac853084fd9589c665d778d13b`
- Migration-conftest patch: `75b1c318a5227678af63a4b70067564abbf33d11ebc192937c0d3bc89e633d93`
- Reused support fixture currently reviewed: `510a237c95714ed7a13e8dd20a612b39bdf4ba80862e890aedb17ca1ec3cbed2`

No blocking P1/P2 defect found. This is a static review only; neither candidate has been executed here.
