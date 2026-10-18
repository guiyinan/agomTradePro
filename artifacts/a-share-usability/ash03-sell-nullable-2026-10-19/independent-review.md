# Nullable SELL log candidate review (2026-10-19)

Static-only review of `.tmp/ash03-sell-nullable-log-candidate-v2/manifest.json` against current shared `use_cases.py` and `test_sell_order_nullable_cost_logging.py`. No tests, project imports, QA, database, provider, or Git operations were run.

The production file is byte-identical to the candidate postimage: SHA-256 `40e9205f7168988d5832548160df95b578d95b73bdd7b2882fd0195b4a1df4e1`. Its only production change from the frozen preimage is the final SELL log rendering after `account_repo.save`: nullable realized PnL and PnL percentage render as `未知`; numeric values still render to two decimals. Trade economics, knowledge flags, validation, and repository writes are unchanged. A known zero PnL remains `0.00`; known amount with undefined percentage remains amount plus `(未知)`.

The shared test file is the candidate’s specified coverage with only Black formatting differences (the in-memory `get_by_account` comprehension wraps across lines). It checks `cost_basis_known=False` and `None` on partial and full sells, including PnL nullness, flag propagation, returned trade, and the individual trade/position/account port calls. It separately preserves known-zero-basis full-close behavior (`realized_pnl=1000`, percentage unknown) and known break-even numeric zeros. These tests use in-memory ports and explicitly do not claim database durability, rollback atomicity, or settlement behavior.

No P1/P2 was found in this finite scope. The patch fixes only nullable log formatting; it does not make the legacy use case atomic and does not connect it to the settlement UoW. The test packet has not been executed in this review.
