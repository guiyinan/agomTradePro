# Static review receipt: nullable-cost CI fixture corrections

Review date: 2026-10-19

## Scope and result

I statically reviewed the currently shared postimages of `tests/api/test_simulated_trading_api_edges.py` and `tests/component/simulated_trading/test_execution_settlement_uow.py`, against the cost/fee knowledge fields, trade-list serializer, and settlement UoW. I found no P1 or P2 issue in the two test changes. This is not a test result: I did not run tests, imports, QA, or database commands. Root's SQLite module run was in progress and is not represented here as passed.

Root's owned RED receipt at `.tmp/ash03-fixture-133/red.result.json` records the two original failures with `exit_code: 1` and `source_unchanged: true`. I read that receipt; I did not reproduce the run.

## Review findings

The API known-zero fixture explicitly marks both `cost_basis_known` and `fee_amounts_known` as `True`, while retaining the original zero realized-PnL assertions. It continues to assert the unpaginated total trade, buy, and sell counts with `limit=1`, plus the zero aggregate and row value. The new cases independently vary cost-basis and fee knowledge across both `False` and `None`. They retain stored numeric zero placeholders, assert the API returns null/unknown for row PnL and PnL percentage and for aggregate PnL, and assert the persisted trade remains zero-valued. The counts remain asserted across the limited response. This covers the distinction between zero and unknown without weakening the pagination or known-zero behavior.

The UoW case retains the exact known-basis partial and full SELL formulas, including the combined proceeds/fees/basis conservation equation. Its `False` and `None` cases perform both partial and final SELLs, preserve the original flag on each trade, assert null realized PnL and percentage, and keep `winning_trades` at zero. The remaining basis after the partial sale is asserted as `2003.33`, with `1001.67 + 2003.33 == 3005.00`. This is consistent with the UoW contract: it allocates stored basis independently of whether that basis is trusted for PnL, calculates fees as known under the configured fee policy, and increments wins only for positive non-null PnL.

The production interfaces support these expectations. `Position.cost_basis_known` and the trade cost/fee flags are tri-state (`bool | None`); ORM fields are nullable with `None` defaults. The trade-list path reports PnL only when cost basis and fees are exactly known and a PnL value exists, and computes counts/aggregate over the filtered set before applying the page limit. The settlement UoW emits null PnL unless position cost knowledge is exactly `True`, retains the basis flag on the SELL row, and does not count a null PnL as a win.

## Evidence and artifact note

Current shared file hashes:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tests/api/test_simulated_trading_api_edges.py` | 15,811 | `580d822ed04f6b4cb3c03d50b0ad10c0019274eb011f8c9eb9f6efa9da2455a1` |
| `tests/component/simulated_trading/test_execution_settlement_uow.py` | 140,913 | `983e4ba4e8947996b5e5fba95256bceaeb6c6bb7de547080577ea4d6a66b135b` |

Production contract files inspected:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `apps/simulated_trading/domain/entities.py` | 17,491 | `aa71d611d3513b3dff03fce94d67d714969cc2f187248e2f8bb6f1fc63066ed9` |
| `apps/simulated_trading/infrastructure/simulated_account_trade_models.py` | 27,021 | `a6189de5a40a66a00738be399ada43438b03bc192f75fe22e05787ffb06a047f` |
| `apps/simulated_trading/interface/_portfolio_views.py` | 13,858 | `92259219f0f4a1f86fd32cdbf85b8e68cf81319569493ff2540948377f0f91b0` |
| `apps/simulated_trading/infrastructure/execution_settlement_uow_repository.py` | 48,869 | `3e9ab324fa432e13dd505c953d39745558d91380c7bc73b8805a5ddd69c27f33` |

The v1 private fixture packet's UoW postimage hash matches the current shared UoW test. Its API postimage hash does not match the current shared API file because Root added the `APIClient` and model annotations plus a docstring after adopting the candidate. A static line comparison shows only those typing/documentation additions and argument reordering in that new test; the assertions and setup are otherwise the same. Treat the v1 manifest's API postimage hash as stale for the current shared file, not as a behavioral review finding.

No source or shared files were changed for this receipt. No local test, QA, project import, database access, or Git operation was performed.
