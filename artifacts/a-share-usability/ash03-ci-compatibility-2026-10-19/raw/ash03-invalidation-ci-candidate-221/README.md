# Position invalidation no-trade test correction (private candidate)

This packet contains one complete test-module postimage only. It repairs the spies in `tests/unit/test_position_invalidation_tasks.py` after the automatic Engine and trade-use-case construction moved out of `application.tasks`.

The three existing tests retain their original task results, checker/summary and notification assertions. Each now observes the actual imported builder `tasks.build_auto_trading_engine`, the legacy `ExecuteSellOrderUseCase` where it is defined (`application.use_cases`), and the current settlement entry `ExecuteCurrentReferenceManualTradeUseCase.execute` (`application.manual_trade_execution`). All three seams remain asserted not called, so the tests continue to assert that invalidation and notification do not start an engine or execute a BUY/SELL. No `create=True` is used and no result assertion is weakened.

Preimage SHA-256 and candidate SHA-256/byte counts are recorded in `manifest.json`. `candidate.patch` is a review diff. No project tests, imports, QA, DB, or Git commands were run.
