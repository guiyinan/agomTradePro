"""Native migration guards for durable simulated-order reservation history."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import import_module
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.db import DatabaseError, connection, connections, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)

_BEFORE = ("simulated_trading", "0034_automatic_trading_invocation")
_AFTER = ("simulated_trading", "0035_simulated_order_reservation")
_RESERVED_AT = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(
    transactional_db: None, django_db_use_migrations: bool
) -> Iterator[None]:
    """Expose migration dependencies without widening pytest's database flush scope."""

    del transactional_db
    if not django_db_use_migrations:
        pytest.skip("reservation migration tests require the real migration graph")
    expected_partial_names = tuple(sorted(_PARTIAL_APP_NAMES))
    popped_layers: list[tuple[str, ...]] = []
    try:
        for _ in range(4):
            current_names = tuple(sorted(config.name for config in django_apps.get_app_configs()))
            assert current_names == expected_partial_names
            django_apps.unset_available_apps()
            popped_layers.append(current_names)
            if django_apps.is_installed("apps.strategy"):
                break
        assert django_apps.is_installed("apps.strategy")
        yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


def _create_historical_rows(apps: Any, *, alias: str) -> tuple[int, int]:
    """Seed one valid account and reservation through the selected migration state."""

    account_model = apps.get_model("simulated_trading", "SimulatedAccountModel")
    reservation_model = apps.get_model("simulated_trading", "SimulatedOrderReservationModel")
    account = account_model._default_manager.using(alias).create(
        user=None,
        account_name="order-reservation-migration-fixture",
        account_type="simulated",
        initial_capital=Decimal("1000.00"),
        current_cash=Decimal("1000.00"),
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
        current_market_value=Decimal("0.00"),
        total_value=Decimal("1000.00"),
    )
    reservation = reservation_model._base_manager.using(alias).create(
        account_id=account.pk,
        owner_user_id=1,
        idempotency_key="migration-retained-order-key",
        intent_payload_hash="a" * 64,
        reservation_request_hash="b" * 64,
        security_id="SH.MIGRATION.SECURITY",
        asset_code="600000.SH",
        asset_name="Migration fixture",
        side="buy",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("1.000000"),
        limit_price=Decimal("10.0000"),
        notional=Decimal("10.00"),
        fee_estimate=Decimal("0.00"),
        fee_budget=Decimal("1.00"),
        commission_estimate=Decimal("0.00"),
        transfer_fee_estimate=Decimal("0.00"),
        stamp_duty_estimate=Decimal("0.00"),
        slippage_estimate=Decimal("0.00"),
        cash_reserved=Decimal("11.00"),
        shares_reserved=Decimal("0.000000"),
        filled_quantity=Decimal("0.000000"),
        cash_consumed=Decimal("0.00"),
        shares_consumed=Decimal("0.000000"),
        cash_released=Decimal("0.00"),
        shares_released=Decimal("0.000000"),
        fee_policy_id="migration-fixture-fee-policy",
        fee_policy_version=1,
        fee_config_id=1,
        fee_policy_hash="c" * 64,
        plan_snapshot_version=1,
        plan_snapshot={"fixture": "valid database row for reverse guard"},
        plan_snapshot_hash="d" * 64,
        source_book_cash=Decimal("1000.00"),
        source_sellable_quantity=None,
        source_snapshot_at=_RESERVED_AT,
        market_session=date(2026, 10, 16),
        settlement_lag_sessions=2,
        settlement_release_date=date(2026, 10, 20),
        reserved_at=_RESERVED_AT,
        status="active",
        cancelled_at=None,
    )
    return int(account.pk), int(reservation.pk)


def _sqlstate(error: BaseException) -> str | None:
    """Return the SQLSTATE carried by a Django database error chain."""

    current: BaseException | None = error
    while current is not None:
        for attribute in ("sqlstate", "pgcode"):
            code = getattr(current, attribute, None)
            if isinstance(code, str):
                return code
        current = current.__cause__
    return None


def _read_table_with_short_lock_timeout(alias: str, table_name: str) -> tuple[str, str | None]:
    """Try an independent read while the reverse guard owns its table lock."""

    connections.close_all()
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '500ms'")
                cursor.execute(
                    f"SELECT 1 FROM {connections[alias].ops.quote_name(table_name)} LIMIT 1"
                )
                cursor.fetchone()
        return "read", None
    except DatabaseError as error:
        return "database_error", _sqlstate(error)
    finally:
        connections.close_all()


def test_migration_round_trip_allows_empty_reverse_and_retains_any_row() -> None:
    """Empty reservation history can reverse; one durable key blocks table removal."""

    alias = connection.alias
    generation_before = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([_BEFORE])
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        assert "simulated_order_reservation" not in connection.introspection.table_names()

        MigrationExecutor(connection).migrate([_AFTER])
        applied = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        reservation_model = applied.get_model(
            "simulated_trading",
            "SimulatedOrderReservationModel",
        )
        assert reservation_model._base_manager.using(alias).count() == 0
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        table_name = reservation_model._meta.db_table
        assert table_name in connection.introspection.table_names()
        with connection.cursor() as cursor:
            columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, table_name)
            }
        assert {
            "idempotency_key",
            "cash_reserved",
            "shares_reserved",
            "plan_snapshot_hash",
        } <= columns

        _, reservation_id = _create_historical_rows(applied, alias=alias)
        before = tuple(
            reservation_model._base_manager.using(alias)
            .filter(pk=reservation_id)
            .values_list("account_id", "idempotency_key", "status", "cash_reserved")
            .get()
        )
        with pytest.raises(IrreversibleError, match="Cannot drop simulated order reservations"):
            MigrationExecutor(connection).migrate([_BEFORE])

        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        assert table_name in connection.introspection.table_names()
        after = tuple(
            reservation_model._base_manager.using(alias)
            .filter(pk=reservation_id)
            .values_list("account_id", "idempotency_key", "status", "cash_reserved")
            .get()
        )
        assert after == before
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)

    generation_after = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    assert generation_after == generation_before


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="The reverse guard's ACCESS EXCLUSIVE table lock is PostgreSQL-specific.",
)
def test_reverse_guard_holds_access_exclusive_lock_while_history_is_present() -> None:
    """A concurrent reader cannot pass the PostgreSQL reverse guard's table lock."""

    alias = connection.alias
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    _, _ = _create_historical_rows(migration_apps, alias=alias)
    migration = import_module("apps.simulated_trading.migrations.0035_simulated_order_reservation")
    reservation_model = migration_apps.get_model(
        "simulated_trading",
        "SimulatedOrderReservationModel",
    )
    table_name = reservation_model._meta.db_table

    with transaction.atomic(using=alias):
        with connections[alias].schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError):
                migration.refuse_to_drop_order_reservations(migration_apps, schema_editor)
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome = executor.submit(
                _read_table_with_short_lock_timeout,
                alias,
                table_name,
            ).result(timeout=5)

    assert outcome == ("database_error", "55P03")
