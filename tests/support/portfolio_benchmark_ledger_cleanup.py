"""Clean only native rehearsal rows while keeping immutable production ledgers guarded."""

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.db import connection, transaction

from tests.support.native_postgres_database import assert_native_postgres_test_database

_TABLES = (
    "portfolio_benchmark_statement_revocation",
    "portfolio_benchmark_approval_event",
    "portfolio_benchmark_daily_valuation",
    "portfolio_benchmark_valuation_epoch",
)


@pytest.fixture
def isolated_benchmark_ledger(
    transactional_db: None, request: pytest.FixtureRequest
) -> Iterator[None]:
    """Clear the named test's ledgers inside one exclusive transaction before Django flushes."""
    if settings.SETTINGS_MODULE != "core.settings.critical_postgres_test":
        yield
        return
    signed_order = request.node.nodeid == (
        "tests/component/broker_execution/test_signed_order_checkpoints.py::test_signed_account_order_checkpoints"
    )
    prefix = "test_ash09_rehearsal_" if signed_order else "test_portfolio_benchmark_"
    protected_tables = (*_TABLES, "broker_execution_order_scope") if signed_order else _TABLES
    if not str(connection.settings_dict["TEST"].get("NAME", "")).startswith(prefix):
        pytest.skip("requires a dedicated Portfolio benchmark test database")
    name = assert_native_postgres_test_database(database=connection)
    assert name.startswith(prefix)
    assert connection.settings_dict["HOST"] in {"127.0.0.1", "::1"}
    with connection.cursor() as cursor:
        cursor.execute("SELECT inet_server_addr()::text")
        assert cursor.fetchone()[0].split("/")[0] in {"127.0.0.1", "::1"}
        for table in protected_tables:
            cursor.execute(f"SELECT EXISTS (SELECT FROM {connection.ops.quote_name(table)})")
            assert cursor.fetchone() == (False,), "rehearsal ledger must start empty"
    try:
        yield
    finally:
        with transaction.atomic(), connection.cursor() as cursor:
            assert_native_postgres_test_database(expected_name=name, database=connection)

            tables = ", ".join(connection.ops.quote_name(t) for t in protected_tables)
            cursor.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE NOWAIT")
            cursor.execute(
                """
                SELECT c.relname, t.tgname, t.tgenabled FROM pg_catalog.pg_trigger t
                JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
                WHERE c.relname=ANY(%s) AND c.relnamespace=current_schema()::regnamespace
                  AND NOT t.tgisinternal AND t.tgtype::integer & 32 = 32
                ORDER BY c.relname, t.tgname
            """,
                [list(protected_tables)],
            )
            guards = cursor.fetchall()
            expected = {
                ("portfolio_benchmark_statement_revocation", "pf_bm_statement_truncate", "A"),
                ("portfolio_benchmark_approval_event", "pf_bm_event_truncate", "A"),
                ("portfolio_benchmark_daily_valuation", "pf_bench_valuation_truncate", "A"),
                ("portfolio_benchmark_valuation_epoch", "pf_bench_valuation_truncate", "A"),
            }
            if signed_order:
                expected.add(
                    ("broker_execution_order_scope", "broker_execution_order_scope_truncate", "A")
                )
            assert set(guards) == expected, "unexpected native rehearsal truncate fences"
            for table, trigger, enabled in guards:
                assert table in protected_tables and enabled == "A"
                sql_table, sql_trigger = map(connection.ops.quote_name, (table, trigger))
                cursor.execute(f"ALTER TABLE {sql_table} DISABLE TRIGGER {sql_trigger}")
            cursor.execute(f"TRUNCATE {tables}")
            for table, trigger, _ in guards:
                sql_table, sql_trigger = map(connection.ops.quote_name, (table, trigger))
                cursor.execute(f"ALTER TABLE {sql_table} ENABLE ALWAYS TRIGGER {sql_trigger}")
                cursor.execute(
                    """
                    SELECT tgenabled FROM pg_catalog.pg_trigger
                    WHERE tgrelid=%s::regclass AND tgname=%s
                """,
                    [table, trigger],
                )
                assert cursor.fetchone() == ("A",)
