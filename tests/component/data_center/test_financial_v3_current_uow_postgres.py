"""PostgreSQL contract source for E1 v3 current UOW composition.

These tests are prepared for the formal integration run and were not executed
in the isolated candidate review.
"""

from __future__ import annotations

import pytest
from django.db import DEFAULT_DB_ALIAS, connection, transaction

from apps.data_center.infrastructure.financial_v3_current_uow import (
    FinancialV3CurrentUowBlocked,
    financial_v3_current_operation_uow,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center"],
)


@pytest.fixture(autouse=True)
def _require_native_test_database(
    transactional_db: None,
    request: pytest.FixtureRequest,
) -> None:
    """Require applied migrations and the explicit isolated native test database."""

    del transactional_db
    if request.config.getoption("nomigrations", default=False):
        pytest.fail("v3 repository contracts require actual migrations")
    assert_native_postgres_test_database()


def _require_one_rc_uow() -> None:
    """Assert the exact PostgreSQL alias, depth, and isolation contract."""

    assert connection.alias == DEFAULT_DB_ALIAS
    assert connection.vendor == "postgresql"
    assert connection.in_atomic_block
    assert not connection.get_autocommit()
    assert len(connection.atomic_blocks) == 1
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        row = cursor.fetchone()
    assert row == ("read committed",)


def test_v3_current_uow_opens_unique_outer_when_caller_has_none() -> None:
    """No-outer E1 read/write gates receive exactly one default RC UOW."""

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RC UOW contract requires the production backend")
    assert not connection.in_atomic_block
    with financial_v3_current_operation_uow():
        _require_one_rc_uow()
    assert not connection.in_atomic_block


def test_v3_current_uow_joins_existing_outer_without_savepoint() -> None:
    """An existing single caller UOW stays at depth one during verification."""

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RC UOW contract requires the production backend")
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        _require_one_rc_uow()
        with financial_v3_current_operation_uow():
            _require_one_rc_uow()
        _require_one_rc_uow()


def test_v3_current_uow_rejects_existing_nested_savepoint() -> None:
    """A nested caller transaction cannot pass the C2 single-UOW guard."""

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RC UOW contract requires the production backend")
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            with pytest.raises(FinancialV3CurrentUowBlocked):
                with financial_v3_current_operation_uow():
                    pytest.fail("nested caller transaction must be rejected")


def test_v3_current_uow_rejects_non_default_alias() -> None:
    """A valid default connection cannot be relabeled as another authority alias."""

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RC UOW contract requires the production backend")
    with pytest.raises(FinancialV3CurrentUowBlocked):
        with financial_v3_current_operation_uow(using="non_default_alias"):
            pytest.fail("a non-default alias must be rejected before transaction entry")


def test_v3_current_uow_rejects_repeatable_read_isolation() -> None:
    """The current source fence is READ COMMITTED, not a repeatable-read snapshot."""

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RC UOW contract requires the production backend")
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(FinancialV3CurrentUowBlocked):
            with financial_v3_current_operation_uow():
                pytest.fail("repeatable read must not be accepted as the current fence")
