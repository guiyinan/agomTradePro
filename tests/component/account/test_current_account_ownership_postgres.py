"""Live physical ownership reads on the dedicated loopback PostgreSQL database."""

from copy import deepcopy
from datetime import timedelta

import pytest
from django.db import connections, transaction
from django.utils import timezone

from apps.simulated_trading.account_ownership_composition import (
    build_current_account_ownership_reader,
)
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)

pytest_plugins = (
    "tests.component.account.test_account_actor_authority_raw_source_publisher_postgres",
)


@pytest.fixture
def ownership_alias(evid06_alias):
    connection = connections[evid06_alias]
    with connection.schema_editor() as editor:
        editor.create_model(SimulatedAccountModel)
    try:
        yield evid06_alias
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(SimulatedAccountModel)


def _row(alias):
    user, _ = _new_user(alias)
    return SimulatedAccountModel._default_manager.using(alias).create(
        user_id=user.pk,
        account_name="local ownership observation",
        account_type="simulated",
        initial_capital=100,
        current_cash=100,
        total_value=100,
        auto_trading_enabled=False,
    )


def test_live_owner_change_missing_and_inactive_never_fall_back(ownership_alias):
    row = _row(ownership_alias)
    reader = build_current_account_ownership_reader(using=ownership_alias)

    def reject_default(execute, sql, params, many, context):
        raise AssertionError("live ownership reader queried default alias")

    with connections["default"].execute_wrapper(reject_default):
        with transaction.atomic(using=ownership_alias):
            observed = reader.read_locked(row_pk=row.pk)
            assert observed.user_id == row.user_id
            assert observed.row_created_at == row.created_at
            assert observed.row_updated_at == row.updated_at
            assert observed.observed_at >= row.updated_at
        SimulatedAccountModel._default_manager.using(ownership_alias).filter(pk=row.pk).update(
            user_id=None,
            is_active=False,
        )
        with transaction.atomic(using=ownership_alias):
            observed = reader.read_locked(row_pk=row.pk)
            assert observed.user_id is None and not observed.is_active
            assert reader.read_locked(row_pk=row.pk + 1000) is None


def test_transaction_isolation_source_clocks_and_lock_contention(ownership_alias):
    row = _row(ownership_alias)
    reader = build_current_account_ownership_reader(using=ownership_alias)
    with pytest.raises(CurrentAccountOwnershipUnavailable, match="transaction"):
        reader.read_locked(row_pk=row.pk)
    with transaction.atomic(using=ownership_alias):
        with connections[ownership_alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(CurrentAccountOwnershipUnavailable, match="READ COMMITTED"):
            reader.read_locked(row_pk=row.pk)

    competing = "evid07_ownership_competing"
    assert competing not in connections.databases
    connections.databases[competing] = deepcopy(connections.databases[ownership_alias])
    try:
        with transaction.atomic(using=competing):
            SimulatedAccountModel._default_manager.using(competing).select_for_update().get(
                pk=row.pk
            )
            with pytest.raises(CurrentAccountOwnershipUnavailable):
                with transaction.atomic(using=ownership_alias):
                    reader.read_locked(row_pk=row.pk)
        with transaction.atomic(using=ownership_alias):
            assert reader.read_locked(row_pk=row.pk).user_id == row.user_id
    finally:
        connections[competing].close()
        connections.databases.pop(competing)

    SimulatedAccountModel._default_manager.using(ownership_alias).filter(pk=row.pk).update(
        updated_at=timezone.now() + timedelta(days=1),
    )
    with pytest.raises(CurrentAccountOwnershipUnavailable, match="invalid"):
        with transaction.atomic(using=ownership_alias):
            reader.read_locked(row_pk=row.pk)
