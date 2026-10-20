"""Native migration guards for durable simulated-order reservation history."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import import_module
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, connections, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.writer import MigrationWriter
from django.db.models import CheckConstraint, F

from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationRequest
from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    OrderReservationPrecisionCheck,
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

_BEFORE_RESERVATION = ("simulated_trading", "0034_automatic_trading_invocation")
_BEFORE_PRECISION = ("simulated_trading", "0036_simulated_order_fill_receipt")
_AFTER = ("simulated_trading", "0037_simulated_order_reservation_sqlite_precision")
_RESERVED_AT = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
_MIGRATION_POLICY_ID = "migration-fixture-fee-policy"


def _canonical_hash(value: object) -> str:
    """Hash one canonical JSON value used by the reservation snapshot."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return sha256(payload).hexdigest()


def _plan_snapshot(
    *,
    account_id: int,
    owner_user_id: int,
    idempotency_key: str,
    quantity: Decimal,
) -> dict[str, object]:
    """Build a canonical row-bound snapshot for the historical migration state."""

    schedule = ExecutionFeeSchedule(
        config_id=1,
        asset_type="equity",
        commission_rate_buy=Decimal("0"),
        commission_rate_sell=Decimal("0"),
        min_commission=Decimal("0"),
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    policy = SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id=_MIGRATION_POLICY_ID,
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=datetime(2026, 10, 15, tzinfo=UTC),
        valid_until=datetime(2026, 10, 17, tzinfo=UTC),
        recorded_at=datetime(2026, 10, 16, 1, 59, 50, tzinfo=UTC),
        transaction_cases=(
            FeeTransactionCase(
                asset_type="equity",
                market="SH",
                board="MAIN",
                side=SimulatedTradeSide.BUY,
                commission=FeeApplicability.APPLIES,
                transfer_fee=FeeApplicability.NOT_APPLICABLE,
                stamp_duty=FeeApplicability.NOT_APPLICABLE,
                slippage=FeeApplicability.NOT_APPLICABLE,
            ),
        ),
    )
    policy_payload = policy.to_payload()
    snapshot: dict[str, object] = {
        "schema": "simulated-order-reservation-plan.v1",
        "plan_type": "SettlementExecutionPlanV3",
        "intent": {
            "account_id": account_id,
            "user_id": owner_user_id,
            "idempotency_key": idempotency_key,
            "side": "buy",
            "security_id": "SH.MIGRATION.SECURITY",
            "asset_code": "600000.SH",
            "asset_name": "Migration fixture",
            "asset_type": "equity",
            "market": "SH",
            "board": "MAIN",
            "quantity": format(quantity, "f"),
            "price": "10.0000",
            "reason": "migration-test",
            "signal_id": None,
        },
        "market_session": "2026-10-16",
        "pre_read_at": "2026-10-16T02:00:00.000000Z",
        "settlement_lag_sessions": 2,
        "settlement_release_date": "2026-10-20",
        "settlement_bundle_id": "migration-fixture-bundle",
        "settlement_bundle_version": "1",
        "settlement_bundle_hash": "1" * 64,
        "settlement_policy_id": "migration-fixture-settlement-policy",
        "settlement_policy_version": "1",
        "settlement_policy_hash": "2" * 64,
        "execution_rule_v2_hash": "3" * 64,
        "bundle_source_observed_at": "2026-10-16T01:59:50.000000Z",
        "bundle_source_available_at": "2026-10-16T01:59:55.000000Z",
        "bundle_effective_from": "2026-10-16T00:00:00.000000Z",
        "bundle_valid_until": "2026-10-17T00:00:00.000000Z",
        "identity_evidence": {},
        "execution_bundle": {},
        "calendar_evidence": {
            "snapshot": {},
            "publication": None,
            "evidence_hash": "4" * 64,
        },
        "fee_policy_v2": policy_payload,
    }
    return snapshot


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


def _create_historical_rows(
    apps: Any,
    *,
    alias: str,
    quantity: Decimal = Decimal("1.000000"),
) -> tuple[int, int]:
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
    notional = (quantity * Decimal("10.0000")).quantize(Decimal("0.01"))
    cash_reserved = notional + Decimal("1.00")
    snapshot = _plan_snapshot(
        account_id=int(account.pk),
        owner_user_id=1,
        idempotency_key="migration-retained-order-key",
        quantity=quantity,
    )
    intent = SimulatedTradeIntent(
        account_id=int(account.pk),
        user_id=1,
        idempotency_key="migration-retained-order-key",
        side=SimulatedTradeSide.BUY,
        security_id="SH.MIGRATION.SECURITY",
        asset_code="600000.SH",
        asset_name="Migration fixture",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=quantity,
        price=Decimal("10.0000"),
        reason="migration-test",
        signal_id=None,
    )
    request = OrderReservationRequest(
        account_id=int(account.pk),
        security_id="SH.MIGRATION.SECURITY",
        idempotency_key="migration-retained-order-key",
        side=SimulatedTradeSide.BUY,
        quantity=quantity,
        limit_price=Decimal("10.0000"),
        asset_type="equity",
        market="SH",
        board="MAIN",
        fee_budget=Decimal("1.00"),
    )
    fee_policy_payload = snapshot["fee_policy_v2"]
    assert type(fee_policy_payload) is dict
    fee_hash = fee_policy_payload["content_hash"]
    assert type(fee_hash) is str
    reservation = reservation_model._base_manager.using(alias).create(
        account_id=account.pk,
        owner_user_id=1,
        idempotency_key="migration-retained-order-key",
        intent_payload_hash=intent.request_payload_hash,
        reservation_request_hash=request.identity(fee_policy_hash=fee_hash).request_payload_hash,
        security_id="SH.MIGRATION.SECURITY",
        asset_code="600000.SH",
        asset_name="Migration fixture",
        side="buy",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=quantity,
        limit_price=Decimal("10.0000"),
        notional=notional,
        fee_estimate=Decimal("0.00"),
        fee_budget=Decimal("1.00"),
        commission_estimate=Decimal("0.00"),
        transfer_fee_estimate=Decimal("0.00"),
        stamp_duty_estimate=Decimal("0.00"),
        slippage_estimate=Decimal("0.00"),
        cash_reserved=cash_reserved,
        shares_reserved=Decimal("0.000000"),
        filled_quantity=Decimal("0.000000"),
        cash_consumed=Decimal("0.00"),
        shares_consumed=Decimal("0.000000"),
        cash_released=Decimal("0.00"),
        shares_released=Decimal("0.000000"),
        fee_policy_id="migration-fixture-fee-policy",
        fee_policy_version=1,
        fee_config_id=1,
        fee_policy_hash=fee_hash,
        plan_snapshot_version=1,
        plan_snapshot=snapshot,
        plan_snapshot_hash=_canonical_hash(snapshot),
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


def test_precision_check_serializes_and_restores_resolved_column_references() -> None:
    """Migration state recreates both the check kind and its field dependencies."""

    expression = OrderReservationPrecisionCheck("amounts_conserved")
    path, args, kwargs = expression.deconstruct()
    module_path, separator, class_name = path.rpartition(".")
    assert separator == "."
    assert class_name == "OrderReservationPrecisionCheck"
    assert args == ("amounts_conserved",)
    assert kwargs == {}
    assert import_module(module_path) is import_module(OrderReservationPrecisionCheck.__module__)
    restored = OrderReservationPrecisionCheck("amounts_conserved")
    source_fields = restored.get_source_expressions()

    assert restored.kind == "amounts_conserved"
    assert tuple(type(child) for child in source_fields) == (F,) * 8
    assert tuple(child.name for child in source_fields) == (
        "filled_quantity",
        "quantity",
        "cash_consumed",
        "cash_reserved",
        "cash_released",
        "shares_consumed",
        "shares_reserved",
        "shares_released",
    )
    serialized, imports = MigrationWriter.serialize(
        CheckConstraint(condition=restored, name="test_simord_amounts_conserved_ck")
    )
    assert "OrderReservationPrecisionCheck" in serialized
    assert "amounts_conserved" in serialized
    assert any("order_reservation_sqlite_precision" in imported for imported in imports)


def test_precision_validate_binds_repeated_values_and_rejects_invalid_counters() -> None:
    """Model constraint validation must not fail open on repeated bound Values."""

    alias = connection.alias
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    historical: Any | None = None
    account_id: int | None = None
    reservation_id: int | None = None
    try:
        executor.migrate([_BEFORE_PRECISION])
        historical = MigrationExecutor(connection).loader.project_state([_BEFORE_PRECISION]).apps
        account_id, reservation_id = _create_historical_rows(historical, alias=alias)
        MigrationExecutor(connection).migrate([_AFTER])
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        migrated = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        reservation_model = migrated.get_model(
            "simulated_trading",
            "SimulatedOrderReservationModel",
        )
        row = reservation_model._base_manager.using(alias).get(pk=reservation_id)

        row.validate_constraints()
        row.cash_consumed = Decimal("12.00")
        with pytest.raises(ValidationError):
            row.validate_constraints()
        row.cash_consumed = Decimal("0.00")
        row.fee_estimate = Decimal("1.00")
        row.fee_budget = Decimal("0.00")
        with pytest.raises(ValidationError):
            row.validate_constraints()
    finally:
        if historical is not None and account_id is not None and reservation_id is not None:
            reservation_model = historical.get_model(
                "simulated_trading",
                "SimulatedOrderReservationModel",
            )
            account_model = historical.get_model(
                "simulated_trading",
                "SimulatedAccountModel",
            )
            deleted_reservations, _ = (
                reservation_model._base_manager.using(alias)
                .filter(pk=reservation_id, account_id=account_id)
                .delete()
            )
            assert deleted_reservations >= 1
            deleted_accounts, _ = (
                account_model._base_manager.using(alias).filter(pk=account_id).delete()
            )
            assert deleted_accounts >= 1
        MigrationExecutor(connection).migrate(leaf_nodes)


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
        executor.migrate([_BEFORE_RESERVATION])
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
        MigrationExecutor(connection).migrate([_BEFORE_PRECISION])
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        assert table_name in connection.introspection.table_names()
        after_precision_reverse = tuple(
            reservation_model._base_manager.using(alias)
            .filter(pk=reservation_id)
            .values_list("account_id", "idempotency_key", "status", "cash_reserved")
            .get()
        )
        assert after_precision_reverse == before
        with pytest.raises(IrreversibleError, match="Cannot drop simulated order reservations"):
            MigrationExecutor(connection).migrate([_BEFORE_RESERVATION])

        assert ("simulated_trading", "0035_simulated_order_reservation") in (
            MigrationRecorder(connection).applied_migrations()
        )
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


def test_precision_migration_preserves_the_supported_quantity_boundary() -> None:
    """The largest supported six-place quantity and unknown source stay exact."""

    alias = connection.alias
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    boundary = Decimal("999999999.999999")
    try:
        executor.migrate([_BEFORE_PRECISION])
        historical = MigrationExecutor(connection).loader.project_state([_BEFORE_PRECISION]).apps
        _, reservation_id = _create_historical_rows(
            historical,
            alias=alias,
            quantity=boundary,
        )
        MigrationExecutor(connection).migrate([_AFTER])
        migrated = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        reservation_model = migrated.get_model(
            "simulated_trading",
            "SimulatedOrderReservationModel",
        )
        row = reservation_model._base_manager.using(alias).get(pk=reservation_id)
        assert row.quantity == boundary
        assert row.shares_reserved == Decimal("0.000000")
        assert row.source_sellable_quantity is None
        assert row.source_book_cash == Decimal("1000.00")
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


def test_precision_migration_fails_closed_above_sqlite_cap_but_preserves_postgresql_range() -> None:
    """SQLite rejects unsupported legacy shares while PostgreSQL keeps full NUMERIC range."""

    alias = connection.alias
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    unsupported_on_sqlite = Decimal("1000000000.000000")
    historical: Any | None = None
    account_id: int | None = None
    reservation_id: int | None = None
    try:
        executor.migrate([_BEFORE_PRECISION])
        historical = MigrationExecutor(connection).loader.project_state([_BEFORE_PRECISION]).apps
        account_id, reservation_id = _create_historical_rows(
            historical,
            alias=alias,
            quantity=unsupported_on_sqlite,
        )
        reservation_model = historical.get_model(
            "simulated_trading",
            "SimulatedOrderReservationModel",
        )
        before = tuple(
            reservation_model._base_manager.using(alias)
            .filter(pk=reservation_id)
            .values_list("quantity", "cash_reserved", "plan_snapshot_hash")
            .get()
        )
        if connection.vendor == "sqlite":
            with pytest.raises(RuntimeError, match="outside the SQLite quantity envelope"):
                MigrationExecutor(connection).migrate([_AFTER])
            assert _AFTER not in MigrationRecorder(connection).applied_migrations()
            after = tuple(
                reservation_model._base_manager.using(alias)
                .filter(pk=reservation_id)
                .values_list("quantity", "cash_reserved", "plan_snapshot_hash")
                .get()
            )
            assert after == before
        else:
            assert connection.vendor == "postgresql"
            MigrationExecutor(connection).migrate([_AFTER])
            migrated = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
            migrated_model = migrated.get_model(
                "simulated_trading",
                "SimulatedOrderReservationModel",
            )
            row = migrated_model._base_manager.using(alias).get(pk=reservation_id)
            assert row.quantity == unsupported_on_sqlite
            assert row.plan_snapshot_hash == before[2]
    finally:
        if historical is not None and account_id is not None and reservation_id is not None:
            reservation_model = historical.get_model(
                "simulated_trading",
                "SimulatedOrderReservationModel",
            )
            account_model = historical.get_model(
                "simulated_trading",
                "SimulatedAccountModel",
            )
            deleted_reservations, _ = (
                reservation_model._base_manager.using(alias)
                .filter(pk=reservation_id, account_id=account_id)
                .delete()
            )
            assert deleted_reservations >= 1
            deleted_accounts, _ = (
                account_model._base_manager.using(alias).filter(pk=account_id).delete()
            )
            assert deleted_accounts >= 1
        MigrationExecutor(connection).migrate(leaf_nodes)


def test_reverse_restores_supported_row_or_refuses_sqlite_float_mismatch_without_data_loss() -> (
    None
):
    """Reversing old REAL arithmetic cannot silently lose a valid fractional cancel."""

    alias = connection.alias
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    historical: Any | None = None
    account_id: int | None = None
    reservation_id: int | None = None
    try:
        executor.migrate([_BEFORE_PRECISION])
        historical = MigrationExecutor(connection).loader.project_state([_BEFORE_PRECISION]).apps
        account_id, reservation_id = _create_historical_rows(historical, alias=alias)
        MigrationExecutor(connection).migrate([_AFTER])
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        migrated = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        reservation_model = migrated.get_model(
            "simulated_trading",
            "SimulatedOrderReservationModel",
        )
        changed = (
            reservation_model._base_manager.using(alias)
            .filter(
                pk=reservation_id,
                account_id=account_id,
            )
            .update(
                status="cancelled",
                cancelled_at=_RESERVED_AT + timedelta(minutes=1),
                cash_consumed=Decimal("0.01"),
                cash_released=Decimal("10.99"),
            )
        )
        assert changed == 1
        before_reverse = tuple(
            reservation_model._base_manager.using(alias)
            .filter(pk=reservation_id, account_id=account_id)
            .values_list(
                "quantity",
                "cash_reserved",
                "cash_consumed",
                "cash_released",
                "status",
                "cancelled_at",
                "plan_snapshot_hash",
            )
            .get()
        )

        if connection.vendor == "sqlite":
            with pytest.raises(DatabaseError):
                MigrationExecutor(connection).migrate([_BEFORE_PRECISION])
            assert _AFTER in MigrationRecorder(connection).applied_migrations()
        else:
            assert connection.vendor == "postgresql"
            MigrationExecutor(connection).migrate([_BEFORE_PRECISION])
            assert _AFTER not in MigrationRecorder(connection).applied_migrations()

        after_reverse = tuple(
            reservation_model._base_manager.using(alias)
            .filter(pk=reservation_id, account_id=account_id)
            .values_list(
                "quantity",
                "cash_reserved",
                "cash_consumed",
                "cash_released",
                "status",
                "cancelled_at",
                "plan_snapshot_hash",
            )
            .get()
        )
        assert after_reverse == before_reverse
    finally:
        if historical is not None and account_id is not None and reservation_id is not None:
            reservation_model = historical.get_model(
                "simulated_trading",
                "SimulatedOrderReservationModel",
            )
            account_model = historical.get_model(
                "simulated_trading",
                "SimulatedAccountModel",
            )
            deleted_reservations, _ = (
                reservation_model._base_manager.using(alias)
                .filter(pk=reservation_id, account_id=account_id)
                .delete()
            )
            assert deleted_reservations >= 1
            deleted_accounts, _ = (
                account_model._base_manager.using(alias).filter(pk=account_id).delete()
            )
            assert deleted_accounts >= 1
        MigrationExecutor(connection).migrate(leaf_nodes)


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
