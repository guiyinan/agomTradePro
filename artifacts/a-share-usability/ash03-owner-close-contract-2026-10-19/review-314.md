# Static review: owner close with unknown sellable quantity

Review date: 2026-10-19. Scope is limited to the two owner-close tests in the 304 candidate and their final formatted/module-alias source copies recorded by 314. No test, project import, database, QA, or Git command was run for this review.

## Findings

Both updated owner-close cases distinguish authorization from sellability. They authenticate as the portfolio owner, first call the real positions-list API and require HTTP 200, then read the real source-to-unified mapping and assert the adopted position retained `quantity=1000`, `avg_cost=10.5000`, and `total_cost=10500.00` while `available_quantity=0` and `available_quantity_known=False`. Neither case writes or mocks the sellable flag. The close call then requires HTTP 422 with `SELLABLE_BALANCE_UNKNOWN`.

The baseline snapshot is deliberately taken after the priming GET. Its `values()` calls capture complete persisted rows in the affected scope: the legacy position; portfolio/account and source/target position maps; all real accounts for the owner; all positions and simulated trades for the mapped account; and all legacy transactions for the portfolio. Equality after the rejected close therefore checks that the close attempt leaves those rows unchanged while allowing the initial list request to perform legitimate adoption. It is a scoped row comparison, not a claim of database-wide write monitoring.

Successful known-sellable close coverage remains in the unchanged `test_ledger_unification_acceptance.py`: `test_close_via_unified_service_creates_sell_trade` creates a position through the account API, expects HTTP 200, and requires a sell trade; `test_partial_close_leaves_correct_remainder` expects HTTP 200, a 700-share remainder, and a 300-share sell trade. Both nodes appear in the 314 green log. Thus the prior owner-close assertions on legacy-only fixtures were replaced with the correct unknown-sellability expectation without removing the known-balance success controls.

The neighboring observer-denial cases remain intact. `TestObserverAccessPermission.test_observer_cannot_close_position` and `TestPositionObserverAccess.test_observer_cannot_close_position` still assert HTTP 403. An AST comparison between the two 304 candidates and the final 314 source copies, normalizing only the `ledger_models.<Model>` module-alias spelling, found changes only to `_legacy_close_write_snapshot` and each file's existing `test_owner_can_close_position`. Function counts remain 21 and 26 respectively; no other function was added, removed, or changed. The two updated cases have no skip marker/call and use real `APIClient` requests against ORM-backed fixtures; no mocked response or branch bypass was introduced.

No blocking test-contract issue was found within this scope. Root's 314 receipt records the two modules plus the full/partial known-close controls at 45 passed, exit code 0; its formatting receipts record Black, isort, and Ruff exit code 0. These are Root's executions, not executions by this reviewer.

## Evidence index

| Artifact | SHA-256 | Review use |
| --- | --- | --- |
| `.tmp/ash03-owner-close-unknown-tests-304/manifest.json` | `445cb50946cb71a85e5e135980a7832047ac80cbb27c96832ddcec797a295a11` | Original TEST ONLY scope and target postimage hashes |
| `.tmp/ash03-owner-close-unknown-tests-304/patches/candidate.patch` | `427d732aa196572615667446a44fa253f679b1d16d321ee22013b9a17d1bc6d1` | Two-file candidate diff |
| `.tmp/ash03-owner-close-contracts-314/inputs.json` | `8f95599e3eab21261d24b1b9f7ab6065701e00696df354bff3063dc85b7187b1` | Final source directory, base, and recorded production/test source hashes |
| `.tmp/ash03-owner-close-contracts-314/green.result.json` | `a4d37d8bec3b77456848ee0ba03669d66310bccdfe4781369057cdd261771571` | Root's native 45-pass command receipt |
| `.tmp/ash03-owner-close-contracts-314/green.log` | `4c0907b88e639c97a0d594fc5c42b18541a1616a4b40d27cd84d04a4e7398be0` | Named owner, observer, full-close, and partial-close passing nodes |
| `.tmp/ash03-owner-close-contracts-314/green.xml` | `d1b61091d8e5524d49713973211864481008c2e5f8468daec14241a6c4232390` | JUnit result cross-check |
| `.tmp/ash03-owner-close-contracts-314/black.result.json` | `cff76853f9b632b276dc501db8dd867c513f19e3a9f4614078ce02feecbf20c1` | Black check receipt |
| `.tmp/ash03-owner-close-contracts-314/isort.result.json` | `86d6f6165e687d13633f24cd72851bb511341c295140b7914e50d93d217898d8` | isort check receipt |
| `.tmp/ash03-owner-close-contracts-314/ruff.result.json` | `9cea10dd26c4a9db0a87aaac4f81066da228feb1e37537dcab59ec6329989234` | Ruff check receipt |
| 314 source `tests/integration/account/test_observer_permission.py` | `0f8983b5960f59004af536e6302ead48d58b08b60ca31d265c5c922d55e78d6e` | Final alias/format source copy |
| 314 source `tests/integration/test_portfolio_observer_access.py` | `84d994eb9e1d4e648ff281d9524b39cc01e7a3189fc6e437b7a77155a9f665b8` | Final alias/format source copy |
| 314 source `tests/integration/account/test_ledger_unification_acceptance.py` | `8e2a5840fdcd1d9049ad43822935ac620ef0672878dd99154c9d402ac9589957` | Known full/partial close controls |

`inputs.json` records `production_identical_to_309: true`; the reviewed change is test-only. The result receipts establish that the 314 candidate was executed by Root on the isolated source export. They do not constitute a separate run by this reviewer.
