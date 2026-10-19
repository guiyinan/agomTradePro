# Static review memo: position invalidation task tests

The private candidate updates only `tests/unit/test_position_invalidation_tasks.py`. The source preimage is 4,821 bytes with SHA-256 `8368057a6055bcc3e66ed9f9112c839f476c0e1fe707013b7db6b073b3354ccd`; the candidate is 5,730 bytes with SHA-256 `483f77ea6458f3db9c33b9fdb5086ead3986e53d8b3deba9a7aa0156df7e77c6`. `manifest.json` records both values and the patch digest.

The stale patch points are no longer members of `application.tasks`. That module imports `build_auto_trading_engine` from `application.interface_services`; the automatic task's local builder calls it to create an Engine. The invalidation and notification tasks call their checker/summary entry points instead. The candidate therefore spies on `tasks.build_auto_trading_engine` and keeps the no-engine assertion at the real task composition seam.

The legacy `ExecuteSellOrderUseCase` is defined in `application.use_cases`, so the candidate patches that defining module. The current settlement route is `ExecuteCurrentReferenceManualTradeUseCase.execute` in `application.manual_trade_execution`; the candidate also asserts that it is not called. These observations preserve the original intent that invalidation/notification tasks only report or notify and never initiate a sell. Existing response, checker, summary, notification, and zero-position assertions remain unchanged. No `create=True` was added for any removed symbol.

Reviewed source hashes: `application/tasks.py` `41829f4b8bca0e77b4ea26af2211067cb46154d8ca17f9fe3af5a69dbdc419ae`; `application/interface_services.py` `64c7a447f503f05efb14be091a5b41547ab70b9763a82ef6124e4255fce150cf`; `application/use_cases.py` `40e9205f7168988d5832548160df95b578d95b73bdd7b2882fd0195b4a1df4e1`; and `application/manual_trade_execution.py` `fa70698e749050d53f08e2f724067cffd3e3e363ad57e468f0f20259400e756a`.

The candidate was not imported or executed. No tests, QA, database operations, Git operations, or shared-source edits were performed.
