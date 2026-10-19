# RC PostgreSQL migration flush diagnosis

This is a read-only diagnosis of `.tmp/ash-combined-ci-251/117858887771.log` and the five migration test modules below. No project imports, tests, QA, database access, or Git operations were run.

## Finding

The first underlying PostgreSQL exception is the account authority-generation guard firing during Django test teardown, not a failed migration assertion. In the log, the migration test bodies report `PASSED`; then teardown begins at pytest output line 1937. The first psycopg exception at line 1943 is `CheckViolation: account authority generation singleton row is missing`, with PL/pgSQL context `public.account_authority_generation_bump()` line 7. The stack proceeds through `django/core/management/commands/flush.py` and becomes Django's generic `CommandError: Database ... couldn't be flushed` (lines 1947–1965). The same underlying exception repeats for all six teardown errors (log lines 1988, 2039, 2090, 2141, and 2192).

The PostgreSQL server log confirms the first failing statement at log line 2366 (server timestamp 02:25:59.536 UTC) is Django's multi-table `TRUNCATE`, whose table list includes `account_authority_generation`. Migration `apps/account/migrations/0065_account_authority_generation.py` installs `BEFORE TRUNCATE` statement triggers on each authority source table. Those triggers call `account_authority_generation_bump()`, which increments the singleton row and deliberately raises SQLSTATE 23514 when that row is absent (migration lines 56–85, 87–102). The cleanup statement includes the singleton itself, so the source-table trigger's required generation row is missing during flush. This is the exact class of issue handled by the existing `preserve_account_authority_generation` test fixture.

There are eight collected test cases across five files; all eight test bodies pass, while six transaction-test teardowns error. The affected six are the state-transfer case, retention-plan case, decision-state case, Qlib-profile case, and both runtime-retirement cases. The two non-transaction migration-inspection cases in `test_research_integrity_migrations.py` pass without teardown errors.

The PostgreSQL `duplicate key ... dc_ret_plan_member_payload_uniq` event at log line 2417 is separate and expected: `test_data_center_retention_plan_migration.py:91` deliberately inserts a duplicate `(plan_id, payload_id)` inside `pytest.raises(IntegrityError)`. That test body passes. It is not the cause of the six flush failures and does not indicate a broken retention constraint.

## Minimal test-isolation fix

The safe fixture already exists at `tests/support/account_authority_generation_flush.py:23`. Its module-scoped autouse wrapper excludes only `account_authority_generation` from Django's generated `sql_flush` table list, runs the original flush for all remaining tables with source triggers still enabled, then verifies the singleton remains present and its generation did not decrease. It also asserts a native PostgreSQL test database before reading that database.

The five affected test modules do not import this fixture, and `tests/migrations/conftest.py` currently only applies serialized migration-baseline rollback. The smallest coherent repair is to expose the existing fixture from `tests/migrations/conftest.py` (for example, import it there with the existing `# noqa: F401` convention), so its module-scoped autouse protection applies to all migration tests in that directory. An equivalent per-module import would work but repeats the same test-isolation wiring five times. Do not remove the generation table, disable its triggers, or weaken the singleton invariant; the fixture preserves the intended guard while making test cleanup compatible with it.

## Exact files inspected

- `.tmp/ash-combined-ci-251/117858887771.log` — SHA-256 `66a55cdff1f695cdbe8bb6fa556ed6260b5d0d552831f27c817f345cba97b539`
- `tests/support/account_authority_generation_flush.py` — SHA-256 `510a237c95714ed7a13e8dd20a612b39bdf4ba80862e890aedb17ca1ec3cbed2`
- `tests/migrations/conftest.py` — SHA-256 `4c6dad4c85f55c4bc29d56601167d2469240fac2ae0dab795aac8e0c5e3da2ff`
- `tests/migrations/test_research_integrity_migrations.py` — SHA-256 `65a839d53f9553b180e3efcfc97491602d32fb9cd82b6ff5eb7b23d6ecdb3d2f`
- `tests/migrations/test_data_center_retention_plan_migration.py` — SHA-256 `33133745fb98ddfcc22a5ae2376da05d894097f17f29546b2a58707342cab361`
- `tests/migrations/test_config_center_decision_state_materialization.py` — SHA-256 `b8e8ebf58b362de8a04ee4a2ad4c545e826fe1b520b7da8abf9b12bb9798687a`
- `tests/migrations/test_config_center_qlib_runtime_materialization.py` — SHA-256 `e75e82210c14dc33d0e953250163726bd5939a425dde12dab885b4204576c06c`
- `tests/migrations/test_config_center_runtime_retirement_materialization.py` — SHA-256 `5a2c92c34a9f8a0db6728341f7b6aa9c6031fc609b6ad948fb423eaf00c5b035`
- `apps/account/migrations/0065_account_authority_generation.py` — SHA-256 `ab7026874db2330defca04f38df633fda8059476a832d3d9412ff61cb3fb0d78`
