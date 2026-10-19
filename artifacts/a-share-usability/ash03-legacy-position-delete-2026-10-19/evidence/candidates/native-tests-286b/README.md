# Native PostgreSQL closed-source/delete race candidate

Status: private TEST ONLY candidate; not run. This is a correction packet; the original 286 packet remains unchanged. No shared source, database, QA, or Git state was changed.

The candidate appends one case to the existing native PostgreSQL concurrency module, `tests/component/account/test_broker_fact_reconciliation_concurrency.py`. It reuses the real `baseline_book` fixture, `preserve_account_authority_generation` flush fixture, and `assert_native_postgres_test_database()` guard. The test is marked `django_db(transaction=True)` and skips on non-PostgreSQL databases.

Connection A calls the actual `portfolio_api_services.get_position_payload()` for a closed legacy source position that has a real mapping to a distinct unified position. The test instruments the existing `legacy_sync_transaction` context manager transparently (`**kwargs` are forwarded unchanged), so it does not depend on a future-only argument. It yields the context manager's `LegacyPositionRecord | None` result unchanged: old implementations that yield `None` keep that behavior, while the new locked-source implementation passes the precise row to A and B. While A holds that context, the test verifies the closed source, then starts the actual `portfolio_api_services.delete_position()` call in a worker thread. Django gives the worker its own thread-local connection. The test records distinct backend PIDs and requires PostgreSQL to show that B is blocked by A on a `portfolio ... FOR UPDATE` query before allowing A to continue.

The assertions check that all legacy-position, unified-position, mapping, and trade row values stay unchanged while A owns the lock; A still receives the mapped target; and after A releases the lock, B completes deletion and no source position, target position, map, or trade remains. The source helper handles a source/target primary-key collision by re-creating the fixture source with a distinct ID before the race begins.

Both worker lock and statement timeouts are bounded. Each `pg_stat_activity` poll first calls `pg_stat_clear_snapshot()` because PostgreSQL can reuse a statistics snapshot within the transaction; the official PostgreSQL 16 monitoring-statistics documentation describes this behavior and reset function: [Monitoring Statistics](https://www.postgresql.org/docs/16/monitoring-stats.html). The worker connection closes in `finally`, the future has a bounded result wait, and the test does not modify database aliases, flush scope, or fixture lifecycle. This is an application/ORM-level two-connection PostgreSQL lock proof, not an HTTP test or a general concurrency harness. It verifies this precise delete/adoption ordering only.

Expected baseline RED against the pre-286 implementation, inferred from source and not yet executed: the test cannot observe B blocked by A on the portfolio parent row. A child-row wait, a completed delete, or a timeout does not satisfy the test. Root owns the actual RED/GREEN run.

## Candidate contents

- `candidate_sources/tests/component/account/test_broker_fact_reconciliation_concurrency.py`: complete postimage for one existing native concurrency test module.
- `candidate.patch`: unified diff from the recorded shared preimage to the candidate postimage.
- `manifest.json`: target preimage/postimage hashes and sizes, evidence source hashes, and execution boundary.

