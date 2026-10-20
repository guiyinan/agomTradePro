"""Native migration guards for append-only simulated-order fill receipts."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from typing import cast

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, connections, models, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
    _current_v3_plan,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.isolated_schema import isolated_schema

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)

_BEFORE = ("simulated_trading", "0035_simulated_order_reservation")
_AFTER = ("simulated_trading", "0036_simulated_order_fill_receipt")
_BEFORE_RECEIPT_VERSION = (
    "simulated_trading",
    "0037_simulated_order_reservation_sqlite_precision",
)
_AFTER_RECEIPT_VERSION = ("simulated_trading", "0038_simulated_order_fill_initial_mark")
_EVENT_TIME = datetime(2026, 10, 16, 2, 1, tzinfo=UTC)
_HASH_SOURCE = "a" * 64
_HASH_REQUEST = "b" * 64
_HASH_ECONOMICS = "c" * 64
_HASH_PLAN = "d" * 64
_HASH_SOURCE_SNAPSHOT = "e" * 64
_HASH_RECEIPT = "f" * 64
_HASH_BINDING = "0" * 64


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(
    transactional_db: None,
    django_db_use_migrations: bool,
) -> Iterator[None]:
    """Expose migration dependencies without widening pytest's database flush scope."""

    del transactional_db
    if not django_db_use_migrations:
        pytest.skip("fill receipt migration tests require the real migration graph")
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


def _receipt_model() -> type[models.Model]:
    """Resolve the historical-current model in a way migration tests can inspect."""

    try:
        model = django_apps.get_model(
            "simulated_trading",
            "SimulatedOrderFillReceiptModel",
        )
    except LookupError:
        pytest.fail("SimulatedOrderFillReceiptModel is not registered")
    return cast(type[models.Model], model)


@pytest.fixture(autouse=True)
def _isolated_receipts_after_parent_ledger(
    _full_app_registry_for_migration_loader: None,
    reservation_harness: _Harness,
) -> Iterator[None]:
    """Clean child receipts before their reservation and trade parent fixtures."""

    del _full_app_registry_for_migration_loader, reservation_harness
    with isolated_schema((_receipt_model(),)):
        yield


def _create_v3_trade(harness: _Harness, *, key: str) -> SimulatedTradeModel:
    """Create a real V3 ledger row through the existing current-purpose UoW."""

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    plan, bundle, _ = _current_v3_plan(
        repository=repository,
        intent=_intent_for(harness, key=key),
        as_of=AS_OF,
        source_exchange="SH",
    )
    result = repository.execute_trade(plan=plan, execution_bundle=bundle, clock=_Clock(AS_OF))
    row = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert row.settlement_plan_binding_version == 3
    return row


def _create_reservation(harness: _Harness, *, key: str) -> SimulatedOrderReservationModel:
    """Create an actual G1 reservation that a future receipt would reference."""

    harness.reserve.execute(
        _intent_for(harness, key=key),
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    return SimulatedOrderReservationModel.objects.get(
        account=harness.account,
        idempotency_key=key,
    )


def _binding_payload(
    reservation: SimulatedOrderReservationModel,
    *,
    namespace: str,
    event_id: str,
    sequence: int,
) -> dict[str, object]:
    """Build a V4 envelope using stable event identity instead of a Receipt PK."""

    return {
        "schema": "simulated-order-fill-binding.v4",
        "reservation_id": reservation.pk,
        "intent_payload_hash": reservation.intent_payload_hash,
        "reservation_request_hash": reservation.reservation_request_hash,
        "plan_snapshot_hash": reservation.plan_snapshot_hash,
        "fee_policy_hash": reservation.fee_policy_hash,
        "source_namespace": namespace,
        "source_version": "parser-v1",
        "source_event_id": event_id,
        "fill_sequence": sequence,
        "side": reservation.side,
        "source_event_payload_hash": _HASH_SOURCE,
        "source_event_snapshot_hash": _HASH_SOURCE_SNAPSHOT,
        "economic_request_hash": _HASH_REQUEST,
        "economics_snapshot_hash": _HASH_ECONOMICS,
        "receipt_hash": _HASH_RECEIPT,
    }


def _promote_to_v4(
    trade: SimulatedTradeModel,
    reservation: SimulatedOrderReservationModel,
    *,
    namespace: str,
    event_id: str,
    sequence: int = 1,
) -> SimulatedTradeModel:
    """Set a structurally complete V4 marker before its Receipt row is inserted."""

    updated = SimulatedTradeModel.objects.filter(pk=trade.pk).update(
        request_payload_hash=_HASH_RECEIPT,
        settlement_plan_binding_version=4,
        settlement_plan_binding_payload=_binding_payload(
            reservation,
            namespace=namespace,
            event_id=event_id,
            sequence=sequence,
        ),
        settlement_plan_binding_hash=_HASH_BINDING,
    )
    assert updated == 1
    trade.refresh_from_db()
    return trade


def _source_payload(
    reservation: SimulatedOrderReservationModel,
    *,
    namespace: str,
    event_id: str,
) -> dict[str, object]:
    """Build the full event-shape keys required by the receipt-table guard."""

    return {
        "source_namespace": namespace,
        "source_version": "parser-v1",
        "source_event_id": event_id,
        "event_payload_hash": _HASH_SOURCE,
        "source_snapshot_id": "migration-matcher-snapshot",
        "source_snapshot_hash": "1" * 64,
        "reservation_id": reservation.pk,
        "account_id": reservation.account_id,
        "user_id": reservation.owner_user_id,
        "order_idempotency_key": reservation.idempotency_key,
        "intent_payload_hash": reservation.intent_payload_hash,
        "reservation_request_hash": reservation.reservation_request_hash,
        "plan_snapshot_hash": reservation.plan_snapshot_hash,
        "security_id": reservation.security_id,
        "asset_code": reservation.asset_code,
        "side": "buy",
        "event_kind": "fill",
        "quantity": "1.000000",
        "price": "10.0000",
        "occurred_at": _EVENT_TIME.isoformat(),
        "source_observed_at": _EVENT_TIME.isoformat(),
        "source_available_at": _EVENT_TIME.isoformat(),
        "recorded_at": _EVENT_TIME.isoformat(),
    }


def _economics_payload(event_id: str) -> dict[str, object]:
    """Build enough complete economics structure for a migration reverse test."""

    zero_fees = {
        "commission": "0.00",
        "transfer_fee": "0.00",
        "stamp_duty": "0.00",
        "slippage": "0.00",
        "total_fee": "0.00",
    }
    zero_state = {
        "fill_count": 0,
        "cumulative_quantity": "0.000000",
        "cumulative_gross": "0.00",
        "cumulative_fees": zero_fees,
    }
    return {
        "schema": "simulated-order-reservation-fill.v1",
        "fill_event_id": event_id,
        "reservation_identity": {
            "account_id": 1,
            "security_id": "SH.MIGRATION.SECURITY",
            "idempotency_key": "migration-receipt-order",
            "request_payload_hash": "2" * 64,
        },
        "user_id": 1,
        "intent_payload_hash": "3" * 64,
        "fee_policy_hash": "4" * 64,
        "side": "buy",
        "asset_code": "600000.SH",
        "asset_type": "equity",
        "market": "SH",
        "board": "MAIN",
        "limit_price": "10.0000",
        "fill_occurred_at": _EVENT_TIME.isoformat(),
        "close_order": False,
        "quantity": "1.000000",
        "price": "10.0000",
        "gross_amount": "10.00",
        "prior": zero_state,
        "cumulative_state": {
            "fill_count": 1,
            "cumulative_quantity": "1.000000",
            "cumulative_gross": "10.00",
            "cumulative_fees": zero_fees,
        },
        "incremental_fees": zero_fees,
        "payload_hash": _HASH_REQUEST,
    }


def _create_receipt(
    reservation: SimulatedOrderReservationModel,
    trade: SimulatedTradeModel,
    *,
    namespace: str,
    event_id: str,
    sequence: int = 1,
    receipt_model: type[models.Model] | None = None,
    receipt_version: int = 1,
    initial_position_mark_evidence: dict[str, object] | None = None,
) -> models.Model:
    """Persist one structurally valid receipt linked to its actual parent rows."""

    model_type = receipt_model or _receipt_model()
    model_fields = {field.name for field in model_type._meta.fields}
    values: dict[str, object] = {
        "reservation_id": reservation.pk,
        "trade_id": trade.pk,
        "fill_sequence": sequence,
        "source_namespace": namespace,
        "source_version": "parser-v1",
        "source_event_id": event_id,
        "event_kind": "fill",
        "source_event_payload": _source_payload(
            reservation,
            namespace=namespace,
            event_id=event_id,
        ),
        "source_event_payload_hash": _HASH_SOURCE,
        "source_event_snapshot_hash": _HASH_SOURCE_SNAPSHOT,
        "economic_request_hash": _HASH_REQUEST,
        "economics_snapshot_hash": _HASH_ECONOMICS,
        "plan_snapshot_hash": reservation.plan_snapshot_hash,
        "economics_payload": _economics_payload(event_id),
        "receipt_hash": _HASH_RECEIPT,
    }
    if "receipt_version" in model_fields:
        values["receipt_version"] = receipt_version
        values["initial_position_mark_evidence"] = initial_position_mark_evidence
    else:
        assert receipt_version == 1 and initial_position_mark_evidence is None
    return model_type._base_manager.using(connection.alias).create(
        **values,
    )


def _trade_snapshot(trade_id: int) -> tuple[object, ...]:
    """Read V3 economic and binding columns to prove migration leaves them intact."""

    return tuple(
        SimulatedTradeModel.objects.filter(pk=trade_id)
        .values_list(
            "account_id",
            "action",
            "quantity",
            "price",
            "amount",
            "commission",
            "transfer_fee",
            "stamp_duty",
            "slippage",
            "total_cost",
            "fee_amounts_known",
            "cost_basis_known",
            "realized_pnl",
            "realized_pnl_pct",
            "order_date",
            "execution_date",
            "execution_time",
            "idempotency_key",
            "request_payload_hash",
            "settlement_plan_binding_version",
            "settlement_plan_binding_payload",
            "settlement_plan_binding_hash",
        )
        .get()
    )


def _reservation_snapshot(reservation_id: int) -> dict[str, object]:
    """Read every reservation column to prove migrations never rewrite its ledger state."""

    return dict(SimulatedOrderReservationModel.objects.filter(pk=reservation_id).values().get())


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
    """Attempt an independent read while the migration's table fence remains held."""

    connections.close_all()
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '500ms'")
                quoted = connections[alias].ops.quote_name(table_name)
                cursor.execute(f"SELECT 1 FROM {quoted} LIMIT 1")
                cursor.fetchone()
        return "read", None
    except DatabaseError as error:
        return "database_error", _sqlstate(error)
    finally:
        connections.close_all()


def test_0036_round_trip_keeps_v3_trade_and_does_not_backfill_receipts(
    reservation_harness: _Harness,
) -> None:
    """The new table starts empty and reversing its empty state preserves V3 rows."""

    alias = connection.alias
    generation_before = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    trade = _create_v3_trade(reservation_harness, key="fill-migration-v3-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="fill-migration-v3-order",
    )
    trade_before = _trade_snapshot(int(trade.pk))
    reservation_before = tuple(
        SimulatedOrderReservationModel.objects.filter(pk=reservation.pk)
        .values_list(
            "account_id",
            "owner_user_id",
            "idempotency_key",
            "quantity",
            "limit_price",
            "filled_quantity",
            "cash_reserved",
            "cash_consumed",
            "shares_reserved",
            "shares_consumed",
            "status",
            "plan_snapshot_hash",
            "source_snapshot_at",
        )
        .get()
    )

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([_BEFORE])
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        assert "simulated_order_fill_receipt" not in connection.introspection.table_names()
        assert _trade_snapshot(int(trade.pk)) == trade_before

        MigrationExecutor(connection).migrate([_AFTER])
        migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        receipt_state_model = migration_apps.get_model(
            "simulated_trading",
            "SimulatedOrderFillReceiptModel",
        )
        assert receipt_state_model._base_manager.using(alias).count() == 0
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        assert "simulated_order_fill_receipt" in connection.introspection.table_names()
        assert _trade_snapshot(int(trade.pk)) == trade_before
        assert (
            tuple(
                SimulatedOrderReservationModel.objects.filter(pk=reservation.pk)
                .values_list(
                    "account_id",
                    "owner_user_id",
                    "idempotency_key",
                    "quantity",
                    "limit_price",
                    "filled_quantity",
                    "cash_reserved",
                    "cash_consumed",
                    "shares_reserved",
                    "shares_consumed",
                    "status",
                    "plan_snapshot_hash",
                    "source_snapshot_at",
                )
                .get()
            )
            == reservation_before
        )

        MigrationExecutor(connection).migrate([_BEFORE])
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        assert "simulated_order_fill_receipt" not in connection.introspection.table_names()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)

    generation_after = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    assert generation_after == generation_before


@pytest.mark.parametrize(
    ("has_v4_trade", "has_receipt"),
    [(True, False), (False, True), (True, True)],
    ids=["v4-binding-only", "receipt-row-always-blocks", "valid-v4-and-receipt"],
)
def test_0036_reverse_refuses_any_trade_or_receipt_history(
    reservation_harness: _Harness,
    has_v4_trade: bool,
    has_receipt: bool,
) -> None:
    """The receipt table and V4 marker are protected even when either exists alone."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([_AFTER])
        trade = _create_v3_trade(
            reservation_harness,
            key=f"fill-migration-guard-trade-{has_v4_trade}-{has_receipt}",
        )
        reservation = _create_reservation(
            reservation_harness,
            key=f"fill-migration-guard-order-{has_v4_trade}-{has_receipt}",
        )
        if has_v4_trade:
            _promote_to_v4(
                trade,
                reservation,
                namespace="migration-matcher",
                event_id="migration-event",
            )
        if has_receipt:
            if has_v4_trade:
                trade.refresh_from_db()
            receipt_model = (
                MigrationExecutor(connection)
                .loader.project_state([_AFTER])
                .apps.get_model(
                    "simulated_trading",
                    "SimulatedOrderFillReceiptModel",
                )
            )
            _create_receipt(
                reservation,
                trade,
                namespace="migration-matcher",
                event_id="migration-event",
                receipt_model=receipt_model,
            )

        receipt_count = _receipt_model()._base_manager.using(connection.alias).count()
        v4_count = SimulatedTradeModel.objects.filter(settlement_plan_binding_version=4).count()
        assert receipt_count == int(has_receipt)
        assert v4_count == int(has_v4_trade)

        before = _trade_snapshot(int(trade.pk))
        with pytest.raises(IrreversibleError, match="Cannot drop simulated order fill history"):
            MigrationExecutor(connection).migrate([_BEFORE])

        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        assert "simulated_order_fill_receipt" in connection.introspection.table_names()
        assert _receipt_model()._base_manager.using(connection.alias).count() == receipt_count
        assert _trade_snapshot(int(trade.pk)) == before
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="The reverse guard's ACCESS EXCLUSIVE table fence is PostgreSQL-specific.",
)
def test_0036_reverse_guard_holds_trade_and_receipt_table_fence(
    reservation_harness: _Harness,
) -> None:
    """Concurrent readers cannot pass while the PostgreSQL refusal check is held."""

    trade = _create_v3_trade(reservation_harness, key="fill-migration-lock-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="fill-migration-lock-order",
    )
    _promote_to_v4(
        trade,
        reservation,
        namespace="migration-lock-matcher",
        event_id="migration-lock-event",
    )
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    migration = import_module("apps.simulated_trading.migrations.0036_simulated_order_fill_receipt")
    trade_table = SimulatedTradeModel._meta.db_table
    receipt_table = _receipt_model()._meta.db_table

    with transaction.atomic(using=connection.alias):
        with connections[connection.alias].schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError):
                migration.refuse_to_drop_simulated_order_fills(migration_apps, schema_editor)
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome = executor.submit(
                _read_table_with_short_lock_timeout,
                connection.alias,
                trade_table,
            ).result(timeout=5)
            receipt_outcome = executor.submit(
                _read_table_with_short_lock_timeout,
                connection.alias,
                receipt_table,
            ).result(timeout=5)

    assert outcome == ("database_error", "55P03")
    assert receipt_outcome == ("database_error", "55P03")


def test_v4_binding_constraint_matches_registered_model_and_migration_state() -> None:
    """Keep the registered trade model and 0036 historical state in lockstep."""

    constraint_name = "sim_trade_plan_binding_pair_ck"
    runtime_constraints = tuple(
        constraint
        for constraint in SimulatedTradeModel._meta.constraints
        if constraint.name == constraint_name
    )
    assert len(runtime_constraints) == 1

    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    historical_trade_model = migration_apps.get_model(
        "simulated_trading",
        "SimulatedTradeModel",
    )
    historical_constraints = tuple(
        constraint
        for constraint in historical_trade_model._meta.constraints
        if constraint.name == constraint_name
    )
    assert len(historical_constraints) == 1
    assert runtime_constraints[0].deconstruct() == historical_constraints[0].deconstruct()


@pytest.mark.parametrize(
    ("receipt_version", "mark_evidence", "accepted"),
    [
        pytest.param(1, None, True, id="v1-sql-null"),
        pytest.param(1, {"snapshot_id": "mark-v1"}, False, id="v1-evidence-rejected"),
        pytest.param(2, None, False, id="v2-sql-null-rejected"),
        pytest.param(2, {"snapshot_id": "mark-v1"}, True, id="v2-evidence"),
        pytest.param(0, None, False, id="zero-version-rejected"),
        pytest.param(3, {"snapshot_id": "mark-v1"}, False, id="unknown-version-rejected"),
    ],
)
def test_receipt_version_constraint_accepts_only_the_two_paired_shapes(
    reservation_harness: _Harness,
    receipt_version: int,
    mark_evidence: dict[str, object] | None,
    accepted: bool,
) -> None:
    """The database accepts only legacy V1/SQL NULL and evidence-bearing V2 rows."""

    key = f"receipt-version-pair-{receipt_version}-{accepted}-{mark_evidence is not None}"
    trade = _create_v3_trade(reservation_harness, key=f"{key}-trade")
    reservation = _create_reservation(reservation_harness, key=f"{key}-order")
    if accepted:
        receipt = _create_receipt(
            reservation,
            trade,
            namespace="receipt-version-schema-test",
            event_id=key,
            receipt_version=receipt_version,
            initial_position_mark_evidence=mark_evidence,
        )
        receipt.refresh_from_db()
        assert receipt.receipt_version == receipt_version
        assert receipt.initial_position_mark_evidence == mark_evidence
    else:
        with pytest.raises(IntegrityError):
            with transaction.atomic(using=connection.alias):
                _create_receipt(
                    reservation,
                    trade,
                    namespace="receipt-version-schema-test",
                    event_id=key,
                    receipt_version=receipt_version,
                    initial_position_mark_evidence=mark_evidence,
                )
        assert _receipt_model()._base_manager.using(connection.alias).count() == 0


def test_receipt_version_and_mark_remain_immutable_after_insert(
    reservation_harness: _Harness,
) -> None:
    """The new schema fields inherit the receipt model's append-only write guard."""

    trade = _create_v3_trade(reservation_harness, key="receipt-version-immutable-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="receipt-version-immutable-order",
    )
    receipt = _create_receipt(
        reservation,
        trade,
        namespace="receipt-version-immutable",
        event_id="immutable-v1",
    )
    receipt_id = int(receipt.pk)
    before = (
        _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).values().get()
    )

    receipt.receipt_version = 2
    receipt.initial_position_mark_evidence = {"snapshot_id": "changed"}
    with pytest.raises(ValidationError, match="不可通过实例 save 修改"):
        receipt.save()
    with pytest.raises(ValidationError, match="不能通过 QuerySet.update"):
        _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).update(
            receipt_version=2,
            initial_position_mark_evidence={"snapshot_id": "changed"},
        )

    after = (
        _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).values().get()
    )
    assert after == before


def test_receipt_version_constraint_matches_registered_model_and_migration_state() -> None:
    """Keep the V1/V2 SQL NULL contract aligned in runtime and historical state."""

    model_type = _receipt_model()
    runtime_version = model_type._meta.get_field("receipt_version")
    runtime_mark = model_type._meta.get_field("initial_position_mark_evidence")
    assert runtime_version.default == 1
    assert runtime_mark.null is True
    constraint_name = "simfill_version_mark_pair_ck"
    runtime_constraints = tuple(
        constraint
        for constraint in model_type._meta.constraints
        if constraint.name == constraint_name
    )
    assert len(runtime_constraints) == 1

    migration_apps = (
        MigrationExecutor(connection).loader.project_state([_AFTER_RECEIPT_VERSION]).apps
    )
    historical_model = migration_apps.get_model(
        "simulated_trading",
        "SimulatedOrderFillReceiptModel",
    )
    assert (
        historical_model._meta.get_field("receipt_version").deconstruct()
        == runtime_version.deconstruct()
    )
    assert (
        historical_model._meta.get_field("initial_position_mark_evidence").deconstruct()
        == runtime_mark.deconstruct()
    )
    historical_constraints = tuple(
        constraint
        for constraint in historical_model._meta.constraints
        if constraint.name == constraint_name
    )
    assert len(historical_constraints) == 1
    assert historical_constraints[0].deconstruct() == runtime_constraints[0].deconstruct()


def test_0038_v1_receipt_round_trip_preserves_receipt_and_financial_rows(
    reservation_harness: _Harness,
) -> None:
    """Up/down migration adds V1/NULL to old rows and preserves every prior column."""

    alias = connection.alias
    trade = _create_v3_trade(reservation_harness, key="receipt-version-v1-roundtrip-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="receipt-version-v1-roundtrip-order",
    )
    trade_before = _trade_snapshot(int(trade.pk))
    reservation_before = _reservation_snapshot(int(reservation.pk))
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([_BEFORE_RECEIPT_VERSION])
        assert _AFTER_RECEIPT_VERSION not in MigrationRecorder(connection).applied_migrations()
        old_apps = (
            MigrationExecutor(connection).loader.project_state([_BEFORE_RECEIPT_VERSION]).apps
        )
        old_receipt_model = old_apps.get_model(
            "simulated_trading",
            "SimulatedOrderFillReceiptModel",
        )
        receipt = _create_receipt(
            reservation,
            trade,
            namespace="receipt-version-v1-roundtrip",
            event_id="legacy-v1",
            receipt_model=old_receipt_model,
        )
        receipt_id = int(receipt.pk)
        legacy_before = (
            old_receipt_model._base_manager.using(alias).filter(pk=receipt_id).values().get()
        )

        MigrationExecutor(connection).migrate([_AFTER_RECEIPT_VERSION])
        assert _AFTER_RECEIPT_VERSION in MigrationRecorder(connection).applied_migrations()
        versioned_apps = (
            MigrationExecutor(connection).loader.project_state([_AFTER_RECEIPT_VERSION]).apps
        )
        versioned_model = versioned_apps.get_model(
            "simulated_trading",
            "SimulatedOrderFillReceiptModel",
        )
        upgraded = versioned_model._base_manager.using(alias).filter(pk=receipt_id).values().get()
        assert upgraded["receipt_version"] == 1
        assert upgraded["initial_position_mark_evidence"] is None
        assert {
            key: value for key, value in upgraded.items() if key in legacy_before
        } == legacy_before
        assert _trade_snapshot(int(trade.pk)) == trade_before
        assert _reservation_snapshot(int(reservation.pk)) == reservation_before

        MigrationExecutor(connection).migrate([_BEFORE_RECEIPT_VERSION])
        assert _AFTER_RECEIPT_VERSION not in MigrationRecorder(connection).applied_migrations()
        downgraded_apps = (
            MigrationExecutor(connection).loader.project_state([_BEFORE_RECEIPT_VERSION]).apps
        )
        downgraded_model = downgraded_apps.get_model(
            "simulated_trading",
            "SimulatedOrderFillReceiptModel",
        )
        assert (
            downgraded_model._base_manager.using(alias).filter(pk=receipt_id).values().get()
            == legacy_before
        )
        assert _trade_snapshot(int(trade.pk)) == trade_before
        assert _reservation_snapshot(int(reservation.pk)) == reservation_before

        MigrationExecutor(connection).migrate([_AFTER_RECEIPT_VERSION])
        assert _AFTER_RECEIPT_VERSION in MigrationRecorder(connection).applied_migrations()
        final_apps = (
            MigrationExecutor(connection).loader.project_state([_AFTER_RECEIPT_VERSION]).apps
        )
        final_model = final_apps.get_model("simulated_trading", "SimulatedOrderFillReceiptModel")
        final_row = final_model._base_manager.using(alias).filter(pk=receipt_id).values().get()
        assert final_row["receipt_version"] == 1
        assert final_row["initial_position_mark_evidence"] is None
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


def test_0038_reverse_refuses_v2_evidence_and_preserves_ledger_rows(
    reservation_harness: _Harness,
) -> None:
    """A schema-only V2 evidence row blocks reversal without changing its parents."""

    trade = _create_v3_trade(reservation_harness, key="receipt-version-v2-reverse-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="receipt-version-v2-reverse-order",
    )
    receipt = _create_receipt(
        reservation,
        trade,
        namespace="receipt-version-v2-reverse",
        event_id="v2-evidence-row",
        receipt_version=2,
        initial_position_mark_evidence={"snapshot_id": "schema-only-evidence"},
    )
    receipt_id = int(receipt.pk)
    receipt_before = (
        _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).values().get()
    )
    trade_before = _trade_snapshot(int(trade.pk))
    reservation_before = _reservation_snapshot(int(reservation.pk))

    with pytest.raises(IrreversibleError, match="Cannot drop simulated fill receipt version"):
        MigrationExecutor(connection).migrate([_BEFORE_RECEIPT_VERSION])

    assert _AFTER_RECEIPT_VERSION in MigrationRecorder(connection).applied_migrations()
    assert (
        _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).values().get()
        == receipt_before
    )
    assert _trade_snapshot(int(trade.pk)) == trade_before
    assert _reservation_snapshot(int(reservation.pk)) == reservation_before


@pytest.mark.skipif(
    connection.vendor != "sqlite", reason="Corrupt-pair injection is SQLite-specific."
)
@pytest.mark.parametrize(
    ("receipt_version", "mark_evidence"),
    [
        pytest.param(2, None, id="corrupt-v2-sql-null"),
        pytest.param(1, {"snapshot_id": "corrupt-v1-evidence"}, id="corrupt-v1-nonnull"),
    ],
)
def test_0038_reverse_refuses_corrupt_version_mark_rows(
    reservation_harness: _Harness,
    receipt_version: int,
    mark_evidence: dict[str, object] | None,
) -> None:
    """Corrupt legacy pairs still block reversal even if an out-of-band writer bypassed CHECK."""

    trade = _create_v3_trade(
        reservation_harness, key=f"receipt-version-corrupt-{receipt_version}-trade"
    )
    reservation = _create_reservation(
        reservation_harness,
        key=f"receipt-version-corrupt-{receipt_version}-order",
    )
    receipt = _create_receipt(
        reservation,
        trade,
        namespace="receipt-version-corrupt",
        event_id=f"corrupt-{receipt_version}",
    )
    receipt_id = int(receipt.pk)
    table = connection.ops.quote_name(_receipt_model()._meta.db_table)
    mark_value = (
        json.dumps(mark_evidence, separators=(",", ":")) if mark_evidence is not None else None
    )
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA ignore_check_constraints = ON")
        cursor.execute(
            f"UPDATE {table} SET receipt_version = %s, initial_position_mark_evidence = %s WHERE id = %s",
            [receipt_version, mark_value, receipt_id],
        )
        cursor.execute("PRAGMA ignore_check_constraints = OFF")
    corrupted_before = (
        _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).values().get()
    )
    trade_before = _trade_snapshot(int(trade.pk))
    reservation_before = _reservation_snapshot(int(reservation.pk))

    try:
        with pytest.raises(IrreversibleError, match="Cannot drop simulated fill receipt version"):
            MigrationExecutor(connection).migrate([_BEFORE_RECEIPT_VERSION])
        assert _AFTER_RECEIPT_VERSION in MigrationRecorder(connection).applied_migrations()
        assert (
            _receipt_model()
            ._base_manager.using(connection.alias)
            .filter(pk=receipt_id)
            .values()
            .get()
            == corrupted_before
        )
        assert _trade_snapshot(int(trade.pk)) == trade_before
        assert _reservation_snapshot(int(reservation.pk)) == reservation_before
    finally:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA ignore_check_constraints = ON")
            cursor.execute(
                f"UPDATE {table} SET receipt_version = 1, initial_position_mark_evidence = NULL WHERE id = %s",
                [receipt_id],
            )
            cursor.execute("PRAGMA ignore_check_constraints = OFF")


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="The reverse guard's ACCESS EXCLUSIVE table fence is PostgreSQL-specific.",
)
def test_0038_reverse_guard_holds_receipt_table_fence(
    reservation_harness: _Harness,
) -> None:
    """Concurrent readers cannot pass the PostgreSQL version check's table fence."""

    trade = _create_v3_trade(reservation_harness, key="receipt-version-lock-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="receipt-version-lock-order",
    )
    _create_receipt(
        reservation,
        trade,
        namespace="receipt-version-lock",
        event_id="lock-v2",
        receipt_version=2,
        initial_position_mark_evidence={"snapshot_id": "lock-test"},
    )
    migration_apps = (
        MigrationExecutor(connection).loader.project_state([_AFTER_RECEIPT_VERSION]).apps
    )
    migration = import_module(
        "apps.simulated_trading.migrations.0038_simulated_order_fill_initial_mark"
    )
    receipt_table = _receipt_model()._meta.db_table

    with transaction.atomic(using=connection.alias):
        with connections[connection.alias].schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError):
                migration.refuse_to_drop_initial_mark_evidence(migration_apps, schema_editor)
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome = executor.submit(
                _read_table_with_short_lock_timeout,
                connection.alias,
                receipt_table,
            ).result(timeout=5)

    assert outcome == ("database_error", "55P03")


def test_v1_json_null_mark_evidence_is_rejected_as_non_sql_null(
    reservation_harness: _Harness,
) -> None:
    """V1 permits SQL NULL only; a JSON null value must fail the DB pair check."""

    trade = _create_v3_trade(reservation_harness, key="receipt-v1-json-null-trade")
    reservation = _create_reservation(
        reservation_harness,
        key="receipt-v1-json-null-order",
    )
    receipt = _create_receipt(
        reservation,
        trade,
        namespace="receipt-v1-json-null",
        event_id="json-null-is-not-sql-null",
        receipt_version=1,
        initial_position_mark_evidence=None,
    )
    receipt_id = cast(int, receipt.pk)
    model_type = _receipt_model()
    table = connection.ops.quote_name(model_type._meta.db_table)
    evidence_column = connection.ops.quote_name(
        model_type._meta.get_field("initial_position_mark_evidence").column
    )
    primary_key_column = connection.ops.quote_name(model_type._meta.pk.column)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {evidence_column} IS NULL FROM {table} " f"WHERE {primary_key_column} = %s",
            [receipt_id],
        )
        assert cursor.fetchone() == (True,)

    if connection.vendor == "sqlite":
        update_sql = (
            f"UPDATE {table} SET {evidence_column} = json('null') "
            f"WHERE {primary_key_column} = %s"
        )
        update_params: tuple[object, ...] = (receipt_id,)
    elif connection.vendor == "postgresql":
        update_sql = (
            f"UPDATE {table} SET {evidence_column} = %s::jsonb " f"WHERE {primary_key_column} = %s"
        )
        update_params = ("null", receipt_id)
    else:
        pytest.fail(f"JSON-null receipt test does not support {connection.vendor}")

    with pytest.raises(IntegrityError):
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                cursor.execute(update_sql, update_params)

    receipt.refresh_from_db()
    assert receipt.receipt_version == 1
    assert receipt.initial_position_mark_evidence is None
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {evidence_column} IS NULL FROM {table} " f"WHERE {primary_key_column} = %s",
            [receipt_id],
        )
        assert cursor.fetchone() == (True,)
    assert _receipt_model()._base_manager.using(connection.alias).filter(pk=receipt_id).count() == 1
