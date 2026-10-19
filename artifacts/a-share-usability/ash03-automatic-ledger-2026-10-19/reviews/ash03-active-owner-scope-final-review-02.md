# ASH03 active simulated owner scope — final static review 02

## Scope and evidence

This review covers the owner reader, its Application Protocol, stop-state mapping, and the existing bridge/settlement/Engine consumer path. Hashes are SHA-256 over each file's raw bytes. I did not run pytest, imports, database operations, QA, or Git.

| Path | Raw SHA-256 |
|---|---|
| `apps/simulated_trading/infrastructure/account_repository.py` | `017c1ebba56fc98c3db2bdef0d6a629b05a5ea6552dc612c2e23f6f18effc682` |
| `apps/simulated_trading/application/automatic_trade_execution.py` | `9af9e8ef00a35066184e8e131ce99de80ca42bea8a3563bdb13ae7e9d77b0ad5` |
| `apps/simulated_trading/application/auto_trading_outcome_state.py` | `1552f1056a417adb2f9c1e4fc4cc4353b588def17f3862997762af5a53b04b54` |
| `apps/simulated_trading/infrastructure/execution_settlement_uow_repository.py` (lock-scope cross-check) | `67534c32c35713e7890a6150289645c24bee0dd37f491af2495049114cb14468` |
| `apps/simulated_trading/application/auto_trading_engine.py` (four consumer checks) | `ab2165d8ac0882b824bb056bf7bd3e5c18439de57352ac65ab33760fa37fc5da` |
| `tests/component/simulated_trading/test_auto_trading_active_owner_reader.py` | `5a0a4e513bed1e8935e8e723e027bb49666d5382b6ffd4f29991dc4a38b55b21` |
| `tests/unit/simulated_trading/test_auto_trading_unknown_stop.py` | `5beacf08a25aba8c4aaf66eb97a6cde276ad2c7e8c5ca26c83445d0428609874` |

## Findings and prior memo disposition

The active-scope reader change closes the earlier same-owner account-type drift boundary. `DjangoSimulatedAccountRepository.get_owner_id` now filters by `pk`, `account_type="simulated"`, and `is_active=True` before reading `user_id`; it still returns only an exact positive `int`. Its docstring explicitly says this is the owner of an active simulated account and that the writer rechecks under lock. The Application Protocol now agrees: it returns the active simulated account's persisted owner, or `None` outside that scope.

The locked writer remains authoritative. `_locked_account` uses `select_for_update()` and filters the account primary key, simulated type, fixed `user_id`, and active status when `require_active=True`. Thus a transfer/type/status change after the preliminary reader cannot pass through on the stale owner read. If a known preflight rejection occurs before that lock, the Bridge's existing second read uses the newly scoped reader; a missing/inactive/real account maps to `AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE` rather than being treated as an ordinary same-owner preflight block.

The other previously open stop boundary is closed in `AccountAutoTradingState.must_stop`: it now recognizes `AUTO_TRADE_OWNER_UNAVAILABLE` as a stop condition alongside `AUTO_TRADE_OWNER_CHANGED` and `AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE`, while keeping the stable issue code. The Bridge maps thrown, missing, boolean/non-positive, or otherwise invalid initial owner reads to `AUTO_TRADE_OWNER_UNAVAILABLE`. Engine checks `must_stop` in all four strategy/legacy BUY/SELL loops before continuing current-account orders or writing tail performance. Already-confirmed trade counts remain in the accumulated state; this does not reclassify a known block as an indeterminate write.

The earlier memo `.tmp/ash03-auto-owner-scope-final-static-review-01.md` (SHA-256 `1872d0c3a6f46a28901d1c6c0820390fe802874d6132df1ba66b1f35048139ff`) remains unchanged. Its conditional same-owner `account_type` drift concern is resolved by the new reader scope; the lock-time scope check and its prior disposition remain valid.

Root reported a real-ORM RED for the two active-reader cases before the filter change, and a four-branch RED for owner-unavailable continuation before the `must_stop` update. This memo does not claim the post-change tests passed; Root's current PostgreSQL and final gates remain the verification source.

No P1/P2 remains in this bounded owner-scope change. This is a static review, not PostgreSQL concurrency or release acceptance.